import re
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.data import Document
from datatrove.pipeline.writers.disk_base import DiskWriter


class ArabicNormalizationFilter(BaseFilter):
    """Normalize Arabic text before quality filtering.
    
    Supports multiple normalization options:
    - Remove diacritics (tashkeel)
    - Normalize Arabic characters (alef variations: آ, أ, إ, ٱ → ا)
    - Remove zero-width characters (ZWNJ, ZWJ, directional marks, etc.)
    - Remove tatweel (elongation character: ـ)
    - Normalize whitespace (with option to preserve newlines)
    - Normalize numbers (optional: Eastern Arabic ٠-٩ → Western 0-9)
    
    Reference: https://en.wikipedia.org/wiki/Arabic_script_in_Unicode
    """
    
    name = "🔤 Arabic Normalization"
    
    def __init__(
        self,
        exclusion_writer: DiskWriter = None,
        remove_diacritics: bool = False,
        normalize_whitespace: bool = True,
        normalize_arabic_chars: bool = True,
        remove_zero_width: bool = True,
        remove_tatweel: bool = True,
        normalize_numbers: bool = False,
        preserve_newlines: bool = True,
    ):
        """Initialize Arabic normalization filter.
        
        Args:
            exclusion_writer: Writer for documents that become empty after normalization
            remove_diacritics: Remove Arabic diacritics (tashkeel) - Unicode \u064B-\u065F\u0670
            normalize_whitespace: Normalize whitespace (collapse multiple spaces)
            normalize_arabic_chars: Normalize alef variations (آ, أ, إ, ٱ) to standard alef (ا)
            remove_zero_width: Remove zero-width characters (ZWNJ, ZWJ, LRM, RLM, etc.)
            remove_tatweel: Remove tatweel (elongation character: ـ)
            normalize_numbers: Convert Eastern Arabic numerals (٠-٩) to Western (0-9)
            preserve_newlines: If True, only normalize spaces/tabs, keep newlines. 
                              If False, normalize all whitespace including newlines.
        """
        super().__init__(exclusion_writer)
        self.remove_diacritics = remove_diacritics
        self.normalize_whitespace = normalize_whitespace
        self.normalize_arabic_chars = normalize_arabic_chars
        self.remove_zero_width = remove_zero_width
        self.remove_tatweel = remove_tatweel
        self.normalize_numbers = normalize_numbers
        self.preserve_newlines = preserve_newlines
        
        # Compile regex patterns for performance
        if remove_diacritics:
            # Arabic diacritics (tashkeel): Fathatan, Dammatan, Kasratan, Fatha, Damma, Kasra, etc.
            self.diacritics_regex = re.compile(r'[\u064B-\u065F\u0670]')
        
        if normalize_arabic_chars:
            # Normalize alef variations to standard alef (ا)
            # آ (U+0622 - Alef with Madda), أ (U+0623 - Alef with Hamza above)
            # إ (U+0625 - Alef with Hamza below), ٱ (U+0671 - Alef wasla)
            self.alef_variations = re.compile(r'[\u0622\u0623\u0625\u0671]')
        
        if remove_zero_width:
            # Zero-width characters:
            # \u200B-\u200D: ZWSP, ZWNJ, ZWJ
            # \uFEFF: Zero-width no-break space (BOM)
            # \u200E, \u200F: LRM, RLM (left-to-right/right-to-left marks)
            # \u202A-\u202E: Directional formatting marks
            # \u2066-\u2069: Additional directional isolates
            self.zero_width_regex = re.compile(
                r'[\u200B-\u200D\uFEFF\u200E\u200F\u202A-\u202E\u2066-\u2069]'
            )
        
        if remove_tatweel:
            # Tatweel (elongation character): ـ (U+0640)
            self.tatweel_regex = re.compile(r'\u0640')
        
        if normalize_numbers:
            # Create translation table for Eastern Arabic to Western numerals
            # ٠١٢٣٤٥٦٧٨٩ → 0123456789
            self.arabic_to_western = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        """Normalize Arabic text in document.
        
        Applies normalization steps in order:
        1. Remove diacritics
        2. Normalize Arabic characters (alef variations)
        3. Remove zero-width characters
        4. Remove tatweel
        5. Normalize numbers (if enabled)
        6. Normalize whitespace
        
        Args:
            doc: Document to normalize
            
        Returns:
            True if document passes (keep it)
            False with reason if document should be rejected (empty after normalization)
        """
        text = doc.text
        
        # Check if key exists (works for both dict and object)
        if 'original_text_normalized' not in doc.metadata:
            doc.metadata['original_text_normalized'] = text
        
        # Step 1: Remove diacritics (tashkeel)
        if self.remove_diacritics:
            text = self.diacritics_regex.sub('', text)
        
        # Step 2: Normalize Arabic characters (alef variations to standard alef)
        if self.normalize_arabic_chars:
            text = self.alef_variations.sub('\u0627', text)  # Standard alef (ا)
        
        # Step 3: Remove zero-width characters
        if self.remove_zero_width:
            text = self.zero_width_regex.sub('', text)
        
        # Step 4: Remove tatweel (elongation)
        if self.remove_tatweel:
            text = self.tatweel_regex.sub('', text)
        
        # Step 5: Normalize numbers (optional - usually keep Arabic numbers)
        if self.normalize_numbers:
            text = text.translate(self.arabic_to_western)
        
        # Step 6: Normalize whitespace
        if self.normalize_whitespace:
            if self.preserve_newlines:
                text = re.sub(r'[ \t]+', ' ', text)
            else:
                # Normalize all whitespace (including newlines)
                text = re.sub(r'\s+', ' ', text)
            text = text.strip()
        
        # Update document text
        doc.text = text
        
        # Check if document is empty after normalization
        if not doc.text or len(doc.text.strip()) == 0:
            self.stat_update("empty_after_normalization")
            # Write rejected document to exclusion writer
            if self.exclusion_writer:
                self.exclusion_writer.write(doc, rank=0)
            return False, "empty_after_normalization"
        
        return True