"""Module d?audit technique des URLs et des fichiers Excel g?n?r?s."""

from __future__ import annotations

from urllib.parse import urlparse

from src.audit.replacement_extractor import extract_concrete_links


def validate_zenodo(url: str, title: str, text: str, html: str, max_results: int = 20) -> dict:
    """Valide une ressource selon les r?gles m?tier ou techniques du projet."""
    parsed = urlparse(url)
    if "zenodo.org" not in parsed.netloc.lower():
        return {}
    if "/search" in parsed.path.lower():
        replacements = extract_concrete_links(url, html, max_results)
        return {
            "Type_URL": "PAGE_RECHERCHE",
            "Nombre_resultats": len(replacements),
            "URL_remplacement": "\n".join(replacements),
            "Decision_hint": "REMPLACER" if replacements else "REJETER",
            "Raison_hint": "PAGE_RECHERCHE_AVEC_RESULTATS" if replacements else "ZERO_RESULTAT",
        }
    if "/records/" in parsed.path.lower():
        return {"Type_URL": "PAGE_DATASET", "Nombre_resultats": 0, "URL_remplacement": "", "Decision_hint": "", "Raison_hint": ""}
    return {}
