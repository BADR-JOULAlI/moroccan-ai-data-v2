"""Module d?audit technique des URLs et des fichiers Excel g?n?r?s."""

from __future__ import annotations

from urllib.parse import urlparse

from src.audit.replacement_extractor import extract_concrete_links


def is_github_search(url: str) -> bool:
    """Retourne un bool?en indiquant si la valeur respecte une condition pr?cise."""
    parsed = urlparse(url)
    return "github.com" in parsed.netloc.lower() and parsed.path.lower() == "/search"


def validate_github(url: str, title: str, text: str, html: str, max_results: int = 20) -> dict:
    """Valide une ressource selon les r?gles m?tier ou techniques du projet."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if is_github_search(url):
        replacements = extract_concrete_links(url, html, max_results)
        zero = "your search did not match any repositories" in (text + html).lower() or "0 results" in (text + html).lower()
        return {
            "Type_URL": "PAGE_RECHERCHE",
            "Nombre_resultats": len(replacements),
            "URL_remplacement": "\n".join(replacements),
            "Decision_hint": "REJETER" if zero and not replacements else "REMPLACER",
            "Raison_hint": "ZERO_RESULTAT" if zero and not replacements else "PAGE_RECHERCHE_AVEC_RESULTATS",
        }
    if len(parts) == 2 and parts[0] not in {"topics", "login", "signup"}:
        return {"Type_URL": "PAGE_REPOSITORY", "Nombre_resultats": 0, "URL_remplacement": "", "Decision_hint": "", "Raison_hint": ""}
    if parts and parts[0] in {"login", "signup"}:
        return {"Type_URL": "PAGE_CONNEXION", "Nombre_resultats": 0, "URL_remplacement": "", "Decision_hint": "A_RECONTROLER", "Raison_hint": "PAGE_CONNEXION"}
    return {}
