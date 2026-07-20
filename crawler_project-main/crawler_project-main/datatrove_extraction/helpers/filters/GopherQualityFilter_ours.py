import numpy as np

from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.utils.text import PUNCTUATION_SET, split_into_words
from datatrove.utils.typeshelper import Languages





class GopherQualityFilter(BaseFilter):
    name = "🥇 Gopher Quality (Darija)"

    def __init__(
        self,
        min_doc_words: int | None =10,
        max_doc_words: int | None = None,
        min_avg_word_length: int | None = 2,  # Court pour Darija mixte
        max_avg_word_length: int | None = None,  # Plus long car mélange arabe/français  (it was 18)
        max_symbol_word_ratio: float | None = 0.2,
        max_bullet_lines_ratio: float | None = None,
        max_ellipsis_lines_ratio: float | None = None,
        max_non_alpha_words_ratio: float | None = 0.8,  # Plus flexible pour Darija
    
        exclusion_writer: DiskWriter = None,
        language: str = Languages.moroccan_arabic ,  # Utilise arabic pour l'analyse
    ):
        """
        Filter to apply Gopher's quality heuristic rules for Darija (Moroccan Arabic).
        Darija can be written in Arabic script, Latin script, or a mix of both.
        
        Reference: https://arxiv.org/pdf/2112.11446.pdf

        Args:
            min_doc_words: Minimum number of words (default: 50)
            max_doc_words: Maximum number of words (default: 100000)
            min_avg_word_length: Minimum average word length (default: 2)
            max_avg_word_length: Maximum average word length (default: 18)
            max_symbol_word_ratio: Maximum symbol to word ratio (default: 0.1)
            max_bullet_lines_ratio: Maximum bullet lines ratio (default: 0.9)
            max_ellipsis_lines_ratio: Maximum ellipsis lines ratio (default: 0.3)
            max_non_alpha_words_ratio: Maximum non-alpha words ratio (default: 0.75)
            exclusion_writer: Writer for excluded documents
            language: Language code for tokenization
        """
        super().__init__(exclusion_writer)
        self.min_doc_words = min_doc_words
        self.max_doc_words = max_doc_words
        self.min_avg_word_length = min_avg_word_length
        self.max_avg_word_length = max_avg_word_length
        self.max_symbol_word_ratio = max_symbol_word_ratio
        self.max_bullet_lines_ratio = max_bullet_lines_ratio
        self.max_ellipsis_lines_ratio = max_ellipsis_lines_ratio
        self.max_non_alpha_words_ratio = max_non_alpha_words_ratio
       
        self.language = language

    def _is_arabic_char(self, char: str) -> bool:
        """Check if character is Arabic script"""
        arabic_ranges = [
            (0x0600, 0x06FF),  # Arabic
            (0x0750, 0x077F),  # Arabic Supplement
            (0x08A0, 0x08FF),  # Arabic Extended-A
        ]
        code = ord(char)
        return any(start <= code <= end for start, end in arabic_ranges)


    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        """
        Applies the heuristics rules to decide if a document should be REMOVED

        Args:
            doc: Document to filter

        Returns: 
            True if document passes filter (keep it)
            False with reason if document fails filter (remove it)
        """
        text = doc.text
        
        words = split_into_words(text, self.language)
        n_words = len(words)

        if n_words == 0:
            return False, "gopher_no_words"

        non_symbol_words = [w for w in words if any(ch not in PUNCTUATION_SET for ch in w)]
        n_non_symbol_words = len(non_symbol_words)

        # Check document length
        if self.min_doc_words and n_non_symbol_words < self.min_doc_words:
            return False, "gopher_short_doc"
        if self.max_doc_words and n_non_symbol_words > self.max_doc_words:
            return False, "gopher_long_doc"

        # Check average word length
        if n_non_symbol_words > 0:
            avg_n_words = np.mean([len(w) for w in non_symbol_words])
            if self.min_avg_word_length and avg_n_words < self.min_avg_word_length:
                return False, "gopher_below_avg_threshold"
            if self.max_avg_word_length and avg_n_words > self.max_avg_word_length:
                return False, "gopher_above_avg_threshold"

        # Check symbol-to-word ratio (with zero-division protection)
        if self.max_symbol_word_ratio and n_words > 0:
            hash_ratio = text.count("#") / n_words
            if hash_ratio > self.max_symbol_word_ratio:
                return False, "gopher_too_many_hashes"
            
            ellipsis_ratio = (text.count("...") + text.count("…")) / n_words
            if ellipsis_ratio > self.max_symbol_word_ratio:
                return False, "gopher_too_many_ellipsis"

        # Check bullet points and ellipsis in lines
        lines = text.splitlines()
        if len(lines) > 0:
            if (
                self.max_bullet_lines_ratio
                and sum(s.lstrip().startswith("•") or s.lstrip().startswith("-") for s in lines) / len(lines)
                > self.max_bullet_lines_ratio
            ):
                return False, "gopher_too_many_bullets"
            if (
                self.max_ellipsis_lines_ratio
                and sum(s.rstrip().endswith("...") or s.rstrip().endswith("…") for s in lines) / len(lines)
                > self.max_ellipsis_lines_ratio
            ):
                return False, "gopher_too_many_end_ellipsis"

        # Calculate non-alpha words ratio correctly
        alpha_words_count = sum([any((c.isalpha() or self._is_arabic_char(c) for c in w)) for w in words])
        non_alpha_words_count = n_words - alpha_words_count
        non_alpha_ratio = non_alpha_words_count / n_words if n_words > 0 else 0

        # Reject if non-alpha ratio exceeds threshold
        if self.max_non_alpha_words_ratio and non_alpha_ratio > self.max_non_alpha_words_ratio:
            return False, "gopher_too_many_non_alpha"

      

        return True