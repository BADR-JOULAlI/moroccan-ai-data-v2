"""Module d?analyse linguistique ou m?tier utilis? pendant la transformation des donn?es."""

from __future__ import annotations


def detect_regions(text: str, config: dict) -> str:
    """D?tecte un signal linguistique, technique ou m?tier et retourne un r?sultat structur?."""
    lowered = (text or "").lower()
    hits = []
    for key in ("regions", "cities"):
        for value in config.get(key, []):
            if value.lower() in lowered:
                hits.append(value)
    return ", ".join(dict.fromkeys(hits))
