from __future__ import annotations

from urllib.parse import urlparse

from src.audit.replacement_extractor import extract_concrete_links


def validate_kaggle(url: str, title: str, text: str, html: str, max_results: int = 20) -> dict:
    parsed = urlparse(url)
    if "kaggle.com" not in parsed.netloc.lower():
        return {}
    if "/search" in parsed.path.lower():
        replacements = extract_concrete_links(url, html, max_results)
        return {
            "Type_URL": "PAGE_RECHERCHE",
            "Nombre_resultats": len(replacements),
            "URL_remplacement": "\n".join(replacements),
            "Decision_hint": "REMPLACER" if replacements else "A_RECONTROLER",
            "Raison_hint": "PAGE_RECHERCHE_AVEC_RESULTATS" if replacements else "JS_OU_LOGIN_POSSIBLE",
        }
    if "/datasets/" in parsed.path.lower():
        return {"Type_URL": "PAGE_DATASET", "Nombre_resultats": 0, "URL_remplacement": "", "Decision_hint": "", "Raison_hint": ""}
    return {}
