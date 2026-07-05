from __future__ import annotations


def detect_regions(text: str, config: dict) -> str:
    lowered = (text or "").lower()
    hits = []
    for key in ("regions", "cities"):
        for value in config.get(key, []):
            if value.lower() in lowered:
                hits.append(value)
    return ", ".join(dict.fromkeys(hits))
