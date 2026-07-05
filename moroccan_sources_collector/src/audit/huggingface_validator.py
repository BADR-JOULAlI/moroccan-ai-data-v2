from __future__ import annotations

from urllib.parse import urlparse

from src.audit.replacement_extractor import extract_concrete_links


def validate_huggingface(url: str, title: str, text: str, html: str, max_results: int = 20) -> dict:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if "huggingface.co" not in parsed.netloc.lower():
        return {}
    if parts and parts[0] in {"datasets", "models"} and parsed.query:
        replacements = extract_concrete_links(url, html, max_results)
        return {
            "Type_URL": "PAGE_RECHERCHE",
            "Nombre_resultats": len(replacements),
            "URL_remplacement": "\n".join(replacements),
            "Decision_hint": "REMPLACER" if replacements else "REJETER",
            "Raison_hint": "PAGE_RECHERCHE_AVEC_RESULTATS" if replacements else "ZERO_RESULTAT",
        }
    if len(parts) >= 3 and parts[0] == "datasets":
        return {"Type_URL": "PAGE_DATASET", "Nombre_resultats": 0, "URL_remplacement": "", "Decision_hint": "", "Raison_hint": ""}
    return {}
