"""An explicit Unicode word profile for model-free extraction runs."""

import re

from datatrove.utils.word_tokenizers import WordTokenizer


class UnicodeWordTokenizer(WordTokenizer):
    """Split Unicode words and punctuation without native NLP dependencies.

    This profile is deterministic, but is not equivalent to spaCy's language
    tokenization. Runs record the selected profile in their configuration.
    """

    def __init__(self):
        super().__init__(language="unicode")

    def word_tokenize(self, text):
        return re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)

    def span_tokenize(self, text):
        return [
            (match.start(), match.end())
            for match in re.finditer(r".+?(?:[.!?؟]+\s*|\n+|$)", text, flags=re.DOTALL)
            if match.group().strip()
        ]

    def sent_tokenize(self, text):
        return [text[start:end].strip() for start, end in self.span_tokenize(text)]
