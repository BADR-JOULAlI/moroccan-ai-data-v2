"""Content-based eligibility for the website collector's linguistic shortlist."""

from __future__ import annotations

import math
import re
import unicodedata

from src.analysis.darija_detector import detect_darija


NON_TEXT_CONTENT_TYPES = {"pdf", "json", "xml", "audio", "video"}
CULTURAL_CATEGORIES = {
    "culture", "culture_marocaine", "traditions", "patrimoine_materiel",
    "patrimoine_immateriel", "gastronomie", "artisanat", "musique", "cinema",
    "litterature", "histoire", "geographie", "archives", "bibliotheques",
    "proverbes", "contes",
}
MOROCCAN_CONTEXT = re.compile(
    r"\b(?:maroc(?:ain(?:e)?s?)?|morocco|moroccan|المغرب|المغربي|المغربية|مغربي|مغربية)\b"
)
CULTURAL_CONTENT = re.compile(
    r"\b(?:culture\w*|tradition\w*|patrimoine|heritage|gastronom\w*|cuisine|"
    r"artisan\w*|musiqu\w*|music\w*|cinema\w*|litter\w*|histoir\w*|histor\w*|"
    r"architecture|archeolog\w*|proverb\w*|conte\w*|folklore|"
    r"التراث|الثقافة|التقاليد|العادات|الموسيقى|التاريخ|الطبخ|المطبخ|الحرف)\b"
)


def _fold_text(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


def _is_moroccan_culture(record: dict, text: str) -> bool:
    category = _fold_text(str(record.get("Categorie_principale") or "")).replace(" ", "_")
    content = _fold_text(text)
    return bool(
        category in CULTURAL_CATEGORIES
        and MOROCCAN_CONTEXT.search(content)
        and CULTURAL_CONTENT.search(content)
    )


def apply_darija_threshold(record: dict, threshold: float) -> dict:
    """Return a copy with explicit linguistic eligibility and its reason.

    Density is the detector's capped lexical-token ratio on ``Texte_extrait``
    alone. Unlike the short-title score, it has no Moroccan-context floor and
    never uses the URL, seed name, title or description as substitute content.

    A positive threshold selects Darija content above the threshold, with
    exceptions for standard Arabic, confirmed French-Darija parallel content
    and Moroccan cultural content. Other candidates stay available for review
    with ``Eligible_collecte=False``; an existing no-signal ``Exclure`` decision
    is retained. Known non-HTML resources without extracted text remain
    eligible for manual validation and later extraction, not auto-approved.

    Zero disables this density filter. No value grants network access or
    overrides robots, domain exclusions, licences or human validation.
    """
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Le seuil de densité Darija doit être compris entre 0 et 1.")

    result = dict(record)
    text = str(record.get("Texte_extrait") or "").strip()
    analysis = detect_darija(text) if text else None
    density = analysis["Densite_darija"] if analysis is not None else None
    result.update({"Densite_darija": density, "Seuil_darija": threshold})

    def decide(eligible: bool, decision: str, reason: str) -> dict:
        result.update({
            "Eligible_collecte": eligible,
            "Decision_linguistique": decision,
            "Motif_selection": reason,
        })
        return result

    if threshold == 0:
        return decide(True, record.get("Decision_linguistique") or "A_recontroler", "filtre_densite_desactive")

    if analysis is None:
        content_type = str(record.get("Type_contenu") or "").casefold()
        if content_type in NON_TEXT_CONTENT_TYPES:
            return decide(True, "A_recontroler", "contenu_non_textuel_a_valider")
        return decide(False, "A_recontroler", "texte_extrait_absent")

    if record.get("Contenu_parallele") == "Oui" or record.get("Langue_principale") == "francais_darija":
        return decide(True, "Conserver", "exception_francais_darija_parallele")

    if analysis["Langue_principale"] in {"arabe_standard", "arabe_standard_probable"}:
        return decide(True, "Conserver", "exception_arabe_standard")

    if _is_moroccan_culture(record, text):
        return decide(True, "Conserver", "exception_culture_marocaine")

    if density >= threshold and analysis["Tokens_darija_detectes"] > 0:
        return decide(True, "Conserver", "densite_darija_suffisante")

    decision = "A_recontroler"
    if (
        record.get("Decision_linguistique") == "Exclure"
        and not analysis["Tokens_darija_detectes"]
        and analysis["Arabizi_detecte"] != "Oui"
    ):
        decision = "Exclure"
    return decide(False, decision, "densite_darija_insuffisante")
