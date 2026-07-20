import re
import html
import ftfy
from collections import Counter
from datatrove.pipeline.base import PipelineStep
from helpers.main_helpers.utils import iter_pages


ftfy_config = ftfy.TextFixerConfig(
    unescape_html="auto",
    remove_terminal_escapes=True,
    fix_encoding=True,
    restore_byte_a0=True,
    replace_lossy_sequences=True,
    decode_inconsistent_utf8=True,
    fix_c1_controls=True,
    fix_latin_ligatures=False,
    fix_character_width=False,
    uncurl_quotes=False,
    fix_line_breaks=True,
    fix_surrogates=True,
    remove_control_chars=True,
    normalization=None,
)

PREFIX_RE = re.compile(
    r'^(?P<lead>[ \t]*)'
    r'(?P<prefix>(?:\S(?: \S)*)(?: {2,}\S(?: \S)*)*:?)'
)
JOIN_SINGLE = re.compile(r'(?<=\S) (?=\S)')
TABLE_RE = re.compile(r'^\s*(<docling_table>)?\s*\|.*\|\s*(</docling_table>)?\s*$')

PUNCTUATION = "\"!:【，】；\"„';:\"`．？！：〉,&?。…,'"
TERMINAL_PUNCTUATION = {
    "؟", "-", ".", "!", ":", "؛", "。", "…", "॥", "।"
}
_PUNCT_SET = set(PUNCTUATION) | set(TERMINAL_PUNCTUATION)

_WEIRD_SPACES_RE = re.compile(r"\t\r \xa0[^\S\n]*")
_BMP_PUA_RE = re.compile(r'[\uE000-\uF8FF]')
_SUPP_PUA_RE = re.compile(r'[\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]')
_REPLACEMENT_CHAR_RE = re.compile(r'�')
_WHITESPACE_RE = re.compile(r"\s+")
_TWO_PLUS_SPACES_RE = re.compile(r" {2,}")
_TWO_PLUS_NEWLINES_RE = re.compile(r"\n{2,}")

DOCLING_TAGS = re.compile(
    r'<docling_formula>|</docling_formula>|<docling_image>|</docling_image>|'
    r'<docling_picture_annotation(?:_non_text)?>|</docling_picture_annotation(?:_non_text)?>|'
    r'<docling_page_number>|</docling_page_number>|<docling_table>|</docling_table>'
)
FAILED_PAGE_RE = re.compile(r'<failed_page>.*?</failed_page>', re.DOTALL)
CORRUPTED_PAGE_RE = re.compile(r'<corrupted_page>.*?</corrupted_page>', re.DOTALL)

DASHES = {'-', '‐', '‒', '–', '—'}

# Structured OCR HTML parsing
DIV_BLOCK_RE = re.compile(r'(?is)<div\b([^>]*)>(.*?)</div>')
ATTR_LABEL_RE = re.compile(r'data-label\s*=\s*"([^"]+)"', re.I)
BR_RE = re.compile(r'(?i)<\s*br\s*/?\s*>')
P_RE_OPEN = re.compile(r'(?i)<\s*p[^>]*>')
P_RE_CLOSE = re.compile(r'(?i)<\s*/\s*p\s*>')
H_RE_OPEN = re.compile(r'(?i)<\s*h[1-6][^>]*>')
H_RE_CLOSE = re.compile(r'(?i)<\s*/\s*h[1-6]\s*>')
LI_RE_OPEN = re.compile(r'(?i)<\s*li[^>]*>')
LI_RE_CLOSE = re.compile(r'(?i)<\s*/\s*li\s*>')
TR_RE_OPEN = re.compile(r'(?i)<\s*tr[^>]*>')
TR_RE_CLOSE = re.compile(r'(?i)<\s*/\s*tr\s*>')
TDTH_RE_OPEN = re.compile(r'(?i)<\s*t[dh][^>]*>')
TDTH_RE_CLOSE = re.compile(r'(?i)<\s*/\s*t[dh]\s*>')
IMG_RE = re.compile(r'(?is)<img\b[^>]*>')
TAG_RE = re.compile(r'(?is)<[^>]+>')

ALLOWED_OCR_LABELS = {
    "Text",
    "Section-Header",
    "Title",
    "Caption",
    "List-Item",
    "Text-Block",
    "Paragraph",
}
SKIP_OCR_LABELS = {
    "Page-Footer",
    "Page-Header",
    "Footer",
    "Header",
}

FOOTER_URL_RE = re.compile(
    r"^(https?://)?(www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s]*)?$"
)

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)


def get_media_metadata(document):
    if not document.media:
        raise ValueError("document.media is empty")

    media0 = document.media[0]

    if isinstance(media0, dict):
        media0.setdefault("metadata", {})
        return media0["metadata"]

    if not hasattr(media0, "metadata") or media0.metadata is None:
        media0.metadata = {}

    return media0.metadata


def _clean_inline_html(fragment: str) -> str:
    if not fragment:
        return ""

    fragment = fragment.replace("\r\n", "\n").replace("\r", "\n")
    fragment = BR_RE.sub("\n", fragment)
    fragment = P_RE_OPEN.sub("", fragment)
    fragment = P_RE_CLOSE.sub("\n", fragment)
    fragment = H_RE_OPEN.sub("", fragment)
    fragment = H_RE_CLOSE.sub("\n", fragment)
    fragment = LI_RE_OPEN.sub("• ", fragment)
    fragment = LI_RE_CLOSE.sub("\n", fragment)
    fragment = TR_RE_OPEN.sub("", fragment)
    fragment = TR_RE_CLOSE.sub("\n", fragment)
    fragment = TDTH_RE_OPEN.sub("", fragment)
    fragment = TDTH_RE_CLOSE.sub(" ", fragment)
    fragment = IMG_RE.sub("", fragment)
    fragment = TAG_RE.sub("", fragment)

    fragment = html.unescape(fragment)
    fragment = fragment.replace("\xa0", " ")
    fragment = re.sub(r"[ \t]+", " ", fragment)

    lines = [line.strip() for line in fragment.split("\n")]
    lines = [line for line in lines if line]

    return "\n".join(lines).strip()

def html_ocr_to_plain_text(text: str) -> str:
    """
    Convert structured OCR HTML into plain text.
    General strategy:
    - keep only useful text-like blocks
    - remove headers/footers/images by structural labels
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if "<div" not in text and "<p" not in text and "<br" not in text:
        text = html.unescape(text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        lines = [line.strip() for line in text.split("\n")]
        lines = [line for line in lines if line]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    parts = []
    found_structured_div = False

    for attrs, inner in DIV_BLOCK_RE.findall(text):
        found_structured_div = True

        m = ATTR_LABEL_RE.search(attrs)
        label = m.group(1).strip() if m else ""

        if label in SKIP_OCR_LABELS:
            continue

        if label and label not in ALLOWED_OCR_LABELS:
            continue

        inner_wo_imgs = IMG_RE.sub("", inner)
        block_text = _clean_inline_html(inner_wo_imgs)
        if not block_text:
            continue

        parts.append(block_text)

    if found_structured_div:
        cleaned = "\n\n".join(parts)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    text = _clean_inline_html(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_page_number(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return (
        re.fullmatch(r"\d+", s) is not None
        or re.fullmatch(r"[Pp]age\s+\d+", s) is not None
        or re.fullmatch(r"\d+\s*/\s*\d+", s) is not None
    )


def _looks_like_isolated_contact_or_url(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return FOOTER_URL_RE.fullmatch(s) is not None or EMAIL_RE.fullmatch(s) is not None


def _normalize_line_for_repetition(line: str) -> str:
    s = line.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\d+", "#", s)
    return s


def remove_ocr_noise_lines(text: str) -> str:
    """
    General cleanup:
    - remove standalone page numbers
    - remove standalone URLs/emails
    - remove very short repeated lines that are likely headers/footers
    """
    if not text:
        return ""

    raw_lines = text.splitlines()
    normalized_non_empty = [
        _normalize_line_for_repetition(line)
        for line in raw_lines
        if line.strip()
    ]
    counts = Counter(normalized_non_empty)

    cleaned_lines = []
    for line in raw_lines:
        s = line.strip()

        if not s:
            cleaned_lines.append("")
            continue

        if _looks_like_page_number(s):
            continue

        if _looks_like_isolated_contact_or_url(s):
            continue

        norm = _normalize_line_for_repetition(s)

        # remove repeated short lines likely to be running headers/footers
        # but do not drop longer content lines
        if counts[norm] >= 2 and len(s) <= 80:
            # keep if line looks like a real sentence/paragraph
            if not re.search(r"[.!?؟؛:]", s) and len(s.split()) <= 8:
                continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _word_char_ratio_ok(chunk: str, threshold_8: float = 0.65, threshold_0: float = 1.0) -> bool:
    no_spaces = _WHITESPACE_RE.sub("", chunk)
    if not no_spaces:
        return False

    alpha_count = sum(c.isalpha() for c in no_spaces)
    alpha_ratio = alpha_count / len(no_spaces)

    if len(no_spaces) <= 8:
        return alpha_ratio >= threshold_0
    return alpha_ratio >= threshold_8


def fix_split_any_at_line_start(
    text: str,
    min_word_letters: int = 4,
    min_total_letters: int = 10
) -> str:
    out = []

    for line in text.splitlines():
        if TABLE_RE.match(line):
            out.append(line)
            continue

        m = PREFIX_RE.match(line)
        if not m:
            out.append(line)
            continue

        raw_prefix = m.group("prefix")
        words = [w for w in _TWO_PLUS_SPACES_RE.split(raw_prefix.strip()) if w]
        counts = [len(w.split(" ")) for w in words]
        largest = max(counts) if counts else 0
        total_letters = sum(counts)

        if not (
            (largest >= min_word_letters or (total_letters >= min_total_letters and len(words) >= 2))
            and _word_char_ratio_ok(raw_prefix)
        ):
            out.append(line)
            continue

        fixed_prefix = JOIN_SINGLE.sub("", raw_prefix)
        fixed_prefix = _TWO_PLUS_SPACES_RE.sub(" ", fixed_prefix)

        rest = line[m.end():]
        if (
            rest
            and not rest[0].isspace()
            and fixed_prefix
            and not fixed_prefix[-1].isspace()
            and not fixed_prefix.endswith(":")
        ):
            rest = " " + fixed_prefix[-1] + rest
            fixed_prefix = fixed_prefix[:-1]

        out.append(m.group("lead") + fixed_prefix + rest)

    return "\n".join(out)


def _is_punct_only(s: str) -> bool:
    s = s.strip()
    if len(s) == 0:
        return False
    return all(ch in _PUNCT_SET for ch in s)


def fix_ocr_punctuation_lines(text: str) -> str:
    lines = text.splitlines()
    out = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if _is_punct_only(line):
            if out:
                out_i = len(out) - 1
                while out_i >= 0 and len(out[out_i].strip()) == 0:
                    out_i -= 1

                if out_i >= 0 and (
                    out[out_i][-1].isspace()
                    or out[out_i][-1].isalpha()
                    or out[out_i][-1].isdigit()
                ):
                    out = out[:out_i + 1]
                    out[-1] = out[-1] + line
                else:
                    out.append(line)
            else:
                out.append(line)
        else:
            out.append(line)

        i += 1

    return "\n".join(out)


def normalize_weird_spaces(text: str) -> str:
    return _WEIRD_SPACES_RE.sub(" ", text)


def normalize_text(text: str) -> str:
    text = _BMP_PUA_RE.sub('', text)
    text = _SUPP_PUA_RE.sub('', text)
    text = _REPLACEMENT_CHAR_RE.sub('', text)
    return text


def clean_pdf_page(text: str) -> str:
    text = html_ocr_to_plain_text(text)
    text = remove_ocr_noise_lines(text)
    text = normalize_weird_spaces(text)
    text = fix_ocr_punctuation_lines(text)
    text = fix_split_any_at_line_start(text)
    text = normalize_text(text)
    text = _TWO_PLUS_NEWLINES_RE.sub("\n\n", text)
    return text.strip()


def remove_tags(text: str, is_from_docling: bool = False) -> str:
    if not is_from_docling:
        text = FAILED_PAGE_RE.sub("", text)
        text = CORRUPTED_PAGE_RE.sub("", text)
    else:
        text = DOCLING_TAGS.sub("", text)
    return text


def pages_to_text(pages: list[str]) -> tuple[str, list[int], list[int]]:
    non_empty_pages_with_indices = [(i, page.strip()) for i, page in enumerate(pages) if page.strip()]
    if not non_empty_pages_with_indices:
        return "", [], []

    pages = [page for _, page in non_empty_pages_with_indices]
    page_indices = [i for i, _ in non_empty_pages_with_indices]

    result_text = ftfy.fix_text(pages[0], config=ftfy_config)
    page_offsets = [len(result_text)]

    for i in range(1, len(pages)):
        current_page = ftfy.fix_text(pages[i], config=ftfy_config)

        if result_text.endswith(tuple(DASHES)) and len(result_text) >= 2 and result_text[-2].isalpha():
            result_text = result_text[:-1] + current_page
        else:
            result_text += "\n\n" + current_page

        page_offsets.append(len(result_text))

    return result_text, page_offsets, page_indices


class Normalize(PipelineStep):
    def __init__(self, is_from_docling: bool = False):
        self.is_from_docling = is_from_docling
        super().__init__()

    def run(self, data, rank: int = 0, world_size: int = 1):
        for document in data:
            pages = [
                clean_pdf_page(remove_tags(page, is_from_docling=self.is_from_docling))
                for page in iter_pages(document)
            ]

            text, page_offsets, page_indices = pages_to_text(pages)
            document.text = text

            metadata = get_media_metadata(document)
            metadata["page_offsets"] = page_offsets
            metadata["page_indices"] = page_indices

            yield document