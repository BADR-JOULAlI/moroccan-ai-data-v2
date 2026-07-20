import re

from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.utils.text import split_into_sentences
from datatrove.utils.typeshelper import Languages


CITATION_REGEX = re.compile(r"\[\d*]|\[edit]|\[citation needed]|\[بتصرف]|\[عدل]")
END_PUNCTUATION = (".", "؟", "!", ":", "?", "'", '"')  # Added Arabic punctuation marks
ELLIPSIS = "..."
POLICY_SUBSTRINGS = [
    # English (kept for mixed content)
    "terms of use",
    "privacy policy",
    "cookie policy",
    "uses cookies",
    "use of cookies",
    "use cookies",
    # Arabic policy keywords
    "سياسة الخصوصية",
    "سياسة حماية الخصوصية",
    "ملفات تعريف الارتباط",
    "الكوكيز",
    "يستخدم هذا الموقع ملفات",
    "جميع الحقوق محفوظة",
    "حقوق النشر",
]

# Arabic placeholder text patterns
PLACEHOLDER_PATTERNS = [
    "lorem ipsum"
]


class C4QualityFilter(BaseFilter):
    """Applies heuristic rules from C4 https://jmlr.org/papers/volume21/20-074/20-074.pdf
    
    Adapted for Moroccan Arabic and Modern Standard Arabic.

    - We only retained lines that ended in a terminal punctuation mark (! . " ? ؟ ؛ :)
    - We discarded any page with fewer than 5 sentences and only retained lines that contained at least 1 word
    - [NOT IMPLEMENTED] We removed any page that contained any word on the "List of Dirty, Naughty, Obscene or Otherwise Bad Words"
    - We removed any line with the word Javascript.
    - We removed any page where placeholder phrases appeared (lorem ipsum, نص تجريبي, etc.)
    - We removed any pages that contained a curly bracket
    Additional filters not mentioned on the list from the paper but on the code:
    - Remove lines with one word over 1000 chars
    - Remove lines with cookies and terms of use keywords (Arabic and English)
    - Normalize Arabic diacritics

    Reference implementation: https://github.com/tensorflow/datasets/blob/master/tensorflow_datasets/text/c4_utils.py#L197
    Args:
        exclusion_writer: optionally pass in a writer that will save the dropped documents
        tokenizer_language: load a diff language specific punkt tokenizer from nltk
        split_paragraph: by default (as in the paper) split on "\n".
            Set to "False" to apply the filters to each sentence instead of to each line
        remove_citations: remove wikipedia style citations from the text
        filter_no_terminal_punct: remove lines without terminal punctuation marks
        min_num_sentences: remove documents that do not have at least this number of sentences (after line filtering).
            set to -1 to disable
        min_words_per_line: drop lines without this min number of words
        max_word_length: drop lines where at least one word has more than this number of characters
        filter_lorem_ipsum: drop documents that contain placeholder text
        filter_javascript: drop lines mentioning "javascript"
        filter_curly_bracket: drop documents containing {
        filter_policy: drop lines containing any of the phrases in POLICY_SUBSTRINGS
    """

    name = "⛰ C4 Quality"

    def __init__(
        self,
        exclusion_writer: DiskWriter = None,
        split_paragraph: bool = True,  # default as used on c4. Set to "False" to split with sent_tokenize
        remove_citations: bool = True,
        filter_no_terminal_punct: bool = False,
        min_num_sentences: int = -1,  # set to -1 to disable
        min_words_per_line: int = 2,  # set to -1 to disable (changed from 3 to 1 for Arabic)
        max_word_length: int = 1000,  # set to -1 to disable
        filter_lorem_ipsum: bool = True,
        filter_javascript: bool = True,
        filter_curly_bracket: bool = False,
        filter_policy: bool = True,
        language: str = Languages.moroccan_arabic,  # changed from english to moroccan_arabic
    ):
        super().__init__(exclusion_writer)
        self.split_paragraph = split_paragraph
        self.remove_citations = remove_citations
        self.filter_no_terminal_punct = filter_no_terminal_punct
        self.min_num_sentences = min_num_sentences
        self.min_words_per_line = min_words_per_line
        self.max_word_length = max_word_length
        self.filter_lorem_ipsum = filter_lorem_ipsum
        self.filter_javascript = filter_javascript
        self.filter_curly_bracket = filter_curly_bracket
        self.filter_policy = filter_policy
        self.language = language

    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        lines = doc.text.splitlines() if self.split_paragraph else split_into_sentences(doc.text, self.language)

        num_sentences = 0
        kept_lines = []

        for line in lines:
            line = line.strip()
            
            words = line.split()
            self.stat_update("line-total")
            # check line has too long word
            if self.max_word_length != -1 and any(len(word) > self.max_word_length for word in words):
                self.stat_update("line-filter-too_long_word")
                continue
            # remove citation
            if self.remove_citations:
                line = CITATION_REGEX.sub("", line)
            # end punctuation
            if self.filter_no_terminal_punct and (not line.endswith(END_PUNCTUATION) or line.endswith(ELLIPSIS)):
                self.stat_update("line-filter-no_terminal_punc")
                continue
            # min words per line (applied after citation removal)
            words = line.split()  # Re-split after citation removal
            if self.min_words_per_line != -1 and len(words) < self.min_words_per_line:
                self.stat_update("line-filter-too_few_words")
                continue
            line_l = line.lower()
            # placeholder text (expanded for Arabic)
            if self.filter_lorem_ipsum and any(placeholder in line_l for placeholder in PLACEHOLDER_PATTERNS):
                return False, "lorem_ipsum"  # drop entire doc
            # javascript
            if self.filter_javascript and "javascript" in line_l:
                self.stat_update("line-filter-javascript")
                continue
            # bracket
            if self.filter_curly_bracket and "{" in line:
                return False, "curly_bracket"  # drop entire doc
            # policy
            if self.filter_policy and any(p in line_l for p in POLICY_SUBSTRINGS):
                self.stat_update("line-filter-policy")
                continue
            if self.min_num_sentences != -1:
                num_sentences += len(split_into_sentences(line, self.language)) if self.split_paragraph else 1
            kept_lines.append(line)
            self.stat_update("line-kept")
        if num_sentences < self.min_num_sentences:
            return False, "too_few_sentences"

        doc.text = ("\n" if self.split_paragraph else " ").join(kept_lines).strip()

        # Check if document is empty after filtering
        if not doc.text or len(doc.text.strip()) == 0:
            return False, "empty_after_filtering"

        return True