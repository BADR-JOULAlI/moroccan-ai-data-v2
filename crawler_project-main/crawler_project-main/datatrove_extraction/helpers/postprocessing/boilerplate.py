from datatrove.data import Document
import re
from typing import List, Tuple
from collections import Counter
from datatrove.pipeline.base import PipelineStep
from typing import Iterable
from loguru import logger

def detect_boilerplate(
    document: Document,
    is_ocr: bool = False,
    drop: bool = False,
    min_threshold: float = 0.25,
    max_threshold: float = 1,
    min_pages_with_pattern: int = 5
) -> list[str]:
    """
    Detect boilerplate using normalized deduplication method.

    Args:
        document: Document object with text and metadata
        min_threshold: Minimum fraction of pages that must have the pattern (inclusive)
        max_threshold: Maximum fraction of pages that can have the pattern (inclusive)
        min_pages_with_pattern: Minimum absolute number of pages that must have the pattern

    Returns:
        List of pages with detected boilerplate wrapped in <docling_boilerplate_top/bottom> tags or removed
    """
    original_text = document.text

    # CHANGED: metadata access via dict
    page_offsets = document.media[0]["metadata"]["page_offsets"]

    pages = []
    start = 0
    for offset in page_offsets:
        pages.append(original_text[start:offset])
        start = offset

    if len(pages) < 2:
        return pages

    original_pages_lines = []
    normalized_pages_lines = []

    for page_idx, page in enumerate(pages):
        if not is_ocr:
            clean_page = re.sub(r"(</docling_page_number>)|(<docling_page_number>)", "", page)
        else:
            clean_page = re.sub(r"<corrupted_page></corrupted_page>|<failed_page></failed_page>", "", page)

        lines = clean_page.strip().split('\n')
        original_lines = page.strip().split('\n')

        original_pages_lines.append(original_lines)

        normalized_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith('|') and stripped_line.endswith('|'):
                normalized_line = f"__MARKDOWN_TABLE_PAGE_{page_idx}__" + stripped_line
            else:
                normalized_line = re.sub(r'\d', '0', line)
                normalized_line = normalized_line.replace(' ', '')
            normalized_lines.append(normalized_line)

        normalized_pages_lines.append(normalized_lines)

    top_common_lines, top_duplicates = find_common_lines_from_top(
        normalized_pages_lines,
        min_threshold=min_threshold,
        max_threshold=max_threshold,
        min_pages_with_pattern=min_pages_with_pattern
    )

    bottom_common_lines, bottom_duplicates = find_common_lines_from_bottom(
        normalized_pages_lines,
        min_threshold=min_threshold,
        max_threshold=max_threshold,
        min_pages_with_pattern=min_pages_with_pattern
    )

    pages = [
        apply_boilerplate_tags(
            original_page_lines,
            top_common_lines if top_duplicate else 0,
            bottom_common_lines if bottom_duplicate else 0,
            drop=drop,
        )
        for original_page_lines, top_duplicate, bottom_duplicate in zip(
            original_pages_lines, top_duplicates, bottom_duplicates
        )
    ]

    return pages


def apply_boilerplate_tags(
    original_page_lines: List[str],
    top_common_lines: int,
    bottom_common_lines: int,
    drop: bool = False
) -> str:
    delimiter = '\n'

    if len(original_page_lines) <= top_common_lines + bottom_common_lines:
        if drop:
            return ""
        else:
            original_text = delimiter.join(original_page_lines)
            return f"<docling_boilerplate_top>{original_text}</docling_boilerplate_top>"

    text = delimiter.join(
        original_page_lines[
            top_common_lines:(-bottom_common_lines if bottom_common_lines > 0 else len(original_page_lines))
        ]
    )

    if drop:
        return text
    else:
        if top_common_lines > 0:
            top_text = f"<docling_boilerplate_top>{delimiter.join(original_page_lines[:top_common_lines])}</docling_boilerplate_top>"
            text = top_text + delimiter + text
        if bottom_common_lines > 0:
            bottom_text = f"<docling_boilerplate_bottom>{delimiter.join(original_page_lines[-bottom_common_lines:])}</docling_boilerplate_bottom>"
            text = text + delimiter + bottom_text

    return text


def find_common_lines_from_top(
    normalized_pages_lines: List[List[str]],
    min_threshold: float,
    max_threshold: float,
    min_pages_with_pattern: int
) -> Tuple[int, List[bool]]:
    if not normalized_pages_lines:
        return 0, []

    common_lines = 0
    candidate_page_indices = list(range(len(normalized_pages_lines)))
    max_lines = max(len(page) for page in normalized_pages_lines)

    for i in range(1, max_lines + 1):
        patterns = []
        for page_idx in candidate_page_indices:
            page = normalized_pages_lines[page_idx]
            if len(page) >= i:
                pattern = tuple(page[:i])
                patterns.append((page_idx, pattern))
            else:
                patterns.append((page_idx, None))

        pattern_counts = Counter(p[1] for p in patterns if p[1] is not None)
        if not pattern_counts:
            break

        most_common_pattern, most_common_count = pattern_counts.most_common(1)[0]

        if (
            most_common_count / len(normalized_pages_lines) >= min_threshold
            and most_common_count / len(normalized_pages_lines) <= max_threshold
            and most_common_count >= min_pages_with_pattern
        ):
            new_candidate_indices = []
            for page_idx, pattern in patterns:
                if pattern == most_common_pattern:
                    new_candidate_indices.append(page_idx)

            if len(new_candidate_indices) >= len(candidate_page_indices) or i == 1:
                common_lines = i
                candidate_page_indices = new_candidate_indices
            else:
                break
        else:
            break

    page_has_pattern = [False] * len(normalized_pages_lines)
    if common_lines > 0:
        for page_idx in candidate_page_indices:
            page_has_pattern[page_idx] = True

    return common_lines, page_has_pattern


def find_common_lines_from_bottom(
    normalized_pages_lines: List[List[str]],
    min_threshold: float,
    max_threshold: float,
    min_pages_with_pattern: int
) -> Tuple[int, List[bool]]:
    if not normalized_pages_lines:
        return 0, []

    common_lines = 0
    candidate_page_indices = list(range(len(normalized_pages_lines)))
    max_lines = max(len(page) for page in normalized_pages_lines)

    for i in range(1, max_lines + 1):
        patterns = []
        for page_idx in candidate_page_indices:
            page = normalized_pages_lines[page_idx]
            if len(page) >= i:
                pattern = tuple(page[-i:])
                patterns.append((page_idx, pattern))
            else:
                patterns.append((page_idx, None))

        pattern_counts = Counter(p[1] for p in patterns if p[1] is not None)
        if not pattern_counts:
            break

        most_common_pattern, most_common_count = pattern_counts.most_common(1)[0]

        if (
            most_common_count / len(normalized_pages_lines) >= min_threshold
            and most_common_count / len(normalized_pages_lines) <= max_threshold
            and most_common_count >= min_pages_with_pattern
        ):
            new_candidate_indices = []
            for page_idx, pattern in patterns:
                if pattern == most_common_pattern:
                    new_candidate_indices.append(page_idx)

            if len(new_candidate_indices) >= len(candidate_page_indices) or i == 1:
                common_lines = i
                candidate_page_indices = new_candidate_indices
            else:
                break
        else:
            break

    page_has_pattern = [False] * len(normalized_pages_lines)
    if common_lines > 0:
        for page_idx in candidate_page_indices:
            page_has_pattern[page_idx] = True

    return common_lines, page_has_pattern


class TagBoilerplateFormatter(PipelineStep):
    name: str = "TagBoilerplateFormatter"
    type: str = "Formatter"

    def __init__(self, is_ocr: bool = False, drop: bool = False):
        super().__init__()
        self.is_ocr = is_ocr
        self.drop = drop

    def run(self, data: Iterable[Document], rank: int = 0, world_size: int = 1):
        for document in data:
            if not document.text:
                yield document
                continue

            try:
                pages = detect_boilerplate(document, is_ocr=self.is_ocr, drop=self.drop)

                if pages:
                    document.text = ""
                    page_offsets = []
                    current_offset = 0

                    for page in pages:
                        document.text += page
                        current_offset += len(page)
                        page_offsets.append(current_offset)

                    # CHANGED: metadata access via dict
                    document.media[0]["metadata"]["page_offsets"] = page_offsets

                yield document
            except Exception as e:
                logger.warning(f"Failed to detect boilerplate for document {document.id}: {e}")
                yield document