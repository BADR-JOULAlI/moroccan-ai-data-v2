"""Module d?analyse linguistique ou m?tier utilis? pendant la transformation des donn?es."""

from __future__ import annotations

from langdetect import LangDetectException, detect

from src.analysis.darija_detector import detect_darija


def detect_language(text: str) -> dict:
    """D?tecte un signal linguistique, technique ou m?tier et retourne un r?sultat structur?."""
    darija = detect_darija(text)
    if darija["Langue_principale"] != "indeterminee":
        return darija
    try:
        code = detect(text[:3000]) if text and len(text.strip()) > 20 else "unknown"
    except LangDetectException:
        code = "unknown"
    mapping = {"ar": "arabe_standard", "fr": "autre_langue", "en": "autre_langue", "es": "autre_langue"}
    darija["Langue_principale"] = mapping.get(code, "indeterminee")
    darija["Decision_linguistique"] = "Conserver" if code == "ar" else "A_recontroler"
    return darija
