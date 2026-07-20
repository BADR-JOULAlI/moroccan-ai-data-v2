import io
import base64
import re

import pymupdf
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.data import Document
from datatrove.pipeline.writers.disk_base import DiskWriter


class ArabicScriptFilter(BaseFilter):
    """Filter digital PDFs based on whether their text is Arabic/Darija.

    Non-Arabic documents (Latin, etc.) pass through to Docling extraction.
    Arabic/Darija documents are sent to the exclusion writer for OCR processing.
    """

    name = "🔡 Arabic Script Filter"

    # Arabic Unicode ranges: Basic Arabic, Supplement, Extended-A/B,
    # Arabic Presentation Forms A & B
    _ARABIC_RE = re.compile(
        r"[\u0600-\u06FF"       # Arabic
        r"\u0750-\u077F"        # Arabic Supplement
        r"\u08A0-\u08FF"        # Arabic Extended-A
        r"\uFB50-\uFDFF"        # Arabic Presentation Forms-A
        r"\uFE70-\uFEFF]"       # Arabic Presentation Forms-B
    )

    def __init__(
        self,
        exclusion_writer: DiskWriter = None,
        arabic_threshold: float = 0.3,
        max_pages_to_sample: int = 5,
    ):
        """
        Args:
            exclusion_writer: Writer for Arabic/Darija documents (routed to OCR).
            arabic_threshold: Minimum fraction of letter characters that must
                be Arabic for the document to be considered Arabic/Darija.
            max_pages_to_sample: Number of pages to sample for script detection.
        """
        super().__init__(exclusion_writer)
        self.arabic_threshold = arabic_threshold
        self.max_pages_to_sample = max_pages_to_sample

    @staticmethod
    def _get_media_bytes(media: dict) -> bytes | None:
        content_b64 = media.get("metadata", {}).get("content_bytes")
        if not content_b64:
            return None
        return base64.b64decode(content_b64)

    def _arabic_ratio(self, text: str) -> float:
        """Return the fraction of letter characters that are Arabic script."""
        letter_count = sum(1 for ch in text if ch.isalpha())
        if letter_count == 0:
            return 0.0
        arabic_count = len(self._ARABIC_RE.findall(text))
        return arabic_count / letter_count

    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        if not doc.media:
            self.stat_update("no_media")
            return False, "no_media"

        media_bytes = self._get_media_bytes(doc.media[0])
        if not media_bytes:
            self.stat_update("no_content_bytes")
            return False, "no_content_bytes"

        try:
            pdf_doc = pymupdf.open(stream=io.BytesIO(media_bytes), filetype="pdf")
        except Exception:
            self.stat_update("pdf_open_error")
            return False, "pdf_open_error"

        total_pages = len(pdf_doc)
        if total_pages == 0:
            self.stat_update("empty_pdf")
            return False, "empty_pdf"

        pages_to_check = min(self.max_pages_to_sample, total_pages)
        step = max(1, total_pages // pages_to_check)
        sampled_indices = list(range(0, total_pages, step))[:pages_to_check]

        sampled_text = []
        for idx in sampled_indices:
            try:
                page = pdf_doc.load_page(idx)
                sampled_text.append(
                    page.get_text("text", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
                )
            except Exception:
                continue

        combined_text = "\n".join(sampled_text)
        if not combined_text.strip():
            self.stat_update("no_extractable_text")
            return False, "no_extractable_text"

        ratio = self._arabic_ratio(combined_text)
        doc.metadata["arabic_char_ratio"] = round(ratio, 4)

        if ratio >= self.arabic_threshold:
            self.stat_update("arabic_darija")
            return False, "arabic_darija"
        else:
            self.stat_update("non_arabic")
            return True