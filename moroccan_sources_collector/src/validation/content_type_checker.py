from __future__ import annotations


def normalize_content_type(value: str | None) -> str:
    return (value or "unknown").split(";")[0].strip().lower() or "unknown"


def content_kind(content_type: str, url: str = "") -> str:
    ct = normalize_content_type(content_type)
    lower = url.lower()
    if "html" in ct:
        return "HTML"
    if "pdf" in ct or lower.endswith(".pdf"):
        return "PDF"
    if "json" in ct:
        return "JSON"
    if "xml" in ct:
        return "XML"
    if ct.startswith("audio"):
        return "Audio"
    if ct.startswith("video"):
        return "Video"
    return "Autre"
