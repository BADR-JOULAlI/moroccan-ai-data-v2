from __future__ import annotations

import re
import unicodedata
from html import unescape

ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
SPACE_RE = re.compile(r"\s+")
ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
TATWEEL = "\u0640"


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", unescape(text or "")).strip()


def normalize_arabic_text(text: str) -> str:
    value = unescape(text or "")
    value = ARABIC_DIACRITICS_RE.sub("", value)
    value = value.replace(TATWEEL, "")
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    return clean_text(value)


def normalize_latin_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", unescape(text or "")).lower()
    value = re.sub(r"https?://\S+|www\.\S+", " ", value)
    value = re.sub(r"[^a-z0-9'\s]", " ", value)

    def reduce_repeats(match: re.Match[str]) -> str:
        char = match.group(1)
        return char * 2

    value = re.sub(r"([a-z])\1{2,}", reduce_repeats, value)
    # Common Darija normalizations where long vowels are often exaggerated.
    value = value.replace("bezzaf", "bezzaf").replace("bzzaaf", "bzaaf")
    return clean_text(value)


def arabic_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return round(sum(1 for ch in letters if ARABIC_RE.match(ch)) / len(letters) * 100, 2)


def latin_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return round(sum(1 for ch in letters if LATIN_RE.match(ch)) / len(letters) * 100, 2)


def has_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text or ""))


def truncate(text: str, limit: int = 5000) -> str:
    return clean_text(text)[:limit]
