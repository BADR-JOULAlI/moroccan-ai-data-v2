"""Module d?audit technique des URLs et des fichiers Excel g?n?r?s."""

from __future__ import annotations

import re

from src.analysis.darija_detector import detect_darija

DARJA = ["الدارجة", "اللهجة المغربية", "moroccan arabic", "moroccan darija", "darija", "chno", "wach", "3lach", "kifach", "bzaf", "daba", "dyal", "bghit"]
CULTURE = ["الثقافة المغربية", "التراث المغربي", "العادات المغربية", "التقاليد المغربية", "المطبخ المغربي", "الموسيقى المغربية", "تاريخ المغرب", "moroccan culture", "moroccan heritage", "culture marocaine", "patrimoine marocain", "morocco", "maroc"]
FR_DARIJA = ["français darija", "francais darija", "dictionnaire français darija", "dictionnaire francais darija", "traduction français darija", "french darija", "darija dictionary", "darija translation", "darija phrases", "darija dialogue"]


def _score_terms(text: str, terms: list[str], weight: int) -> int:
    """D?crit le fonctionnement de `_score_terms` et retourne le r?sultat attendu par le module."""
    lower = text.lower()
    hits = sum(1 for term in terms if term.lower() in lower)
    return min(100, hits * weight)


def relevance_scores(title: str, description: str, text: str, url: str = "") -> dict:
    """D?crit le fonctionnement de `relevance_scores` et retourne le r?sultat attendu par le module."""
    combined = " ".join([title or "", description or "", text or "", url or ""])
    darija = detect_darija(combined[:8000])
    darija_score = int(darija.get("Score_darija") or 0)
    culture_score = _score_terms(combined, CULTURE, 20)
    fr_darija_score = _score_terms(combined, FR_DARIJA, 25)
    direct_darija_terms = _score_terms(combined, DARJA, 18)
    relevance = min(100, max(darija_score, direct_darija_terms) + min(30, culture_score) + min(35, fr_darija_score))
    return {
        "Langue_principale": darija.get("Langue_principale", "indeterminee"),
        "Score_darija": darija_score,
        "Score_culture_marocaine": culture_score,
        "Score_francais_darija": fr_darija_score,
        "Score_pertinence": min(100, relevance),
    }


def is_relevant_resource(scores: dict, type_url: str) -> bool:
    """Retourne un bool?en indiquant si la valeur respecte une condition pr?cise."""
    if type_url in {"PAGE_DATASET", "PAGE_REPOSITORY", "PAGE_PUBLICATION"} and scores["Score_pertinence"] >= 30:
        return True
    return scores["Score_pertinence"] >= 50
