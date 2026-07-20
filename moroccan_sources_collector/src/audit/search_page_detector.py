"""Module d?audit technique des URLs et des fichiers Excel g?n?r?s."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def platform_for_url(url: str) -> str:
    """D?crit le fonctionnement de `platform_for_url` et retourne le r?sultat attendu par le module."""
    host = urlparse(url).netloc.lower()
    if "github.com" in host:
        return "GitHub"
    if "huggingface.co" in host:
        return "Hugging Face"
    if "kaggle.com" in host:
        return "Kaggle"
    if "zenodo.org" in host:
        return "Zenodo"
    if "arxiv.org" in host:
        return "arXiv"
    if "aclanthology.org" in host:
        return "ACL Anthology"
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    if "facebook.com" in host:
        return "Facebook"
    return host.removeprefix("www.")


def is_search_page(url: str) -> bool:
    """Retourne un bool?en indiquant si la valeur respecte une condition pr?cise."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    if "github.com" in host and path == "/search":
        return True
    if "huggingface.co" in host and path in {"/datasets", "/models"} and "search=" in query:
        return True
    if "kaggle.com" in host and "/search" in path:
        return True
    if "zenodo.org" in host and "/search" in path:
        return True
    if "arxiv.org" in host and "/search" in path:
        return True
    if "aclanthology.org" in host and "/search" in path:
        return True
    if "youtube.com" in host and "/results" in path:
        return True
    if "facebook.com" in host and "/search/" in path:
        return True
    return False


def query_for_url(url: str) -> str:
    """D?crit le fonctionnement de `query_for_url` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("q", "query", "search", "search_query"):
        if query.get(key):
            return query[key][0]
    return ""


def concrete_type_for_url(url: str) -> str | None:
    """D?crit le fonctionnement de `concrete_type_for_url` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if "github.com" in host:
        if len(parts) == 2 and parts[0] not in {"search", "topics", "login", "signup"}:
            return "PAGE_REPOSITORY"
    if "huggingface.co" in host:
        if len(parts) >= 3 and parts[0] == "datasets":
            return "PAGE_DATASET"
        if len(parts) == 2 and parts[0] not in {"datasets", "models", "spaces", "search", "login", "join"}:
            return "PAGE_DATASET"
    if "zenodo.org" in host and len(parts) >= 2 and parts[0] == "records":
        return "PAGE_DATASET"
    if "arxiv.org" in host and len(parts) >= 2 and parts[0] == "abs":
        return "PAGE_PUBLICATION"
    if "aclanthology.org" in host and parts and parts[0] not in {"search"}:
        return "PAGE_PUBLICATION"
    if "youtube.com" in host and (parsed.path == "/watch" or "/shorts/" in parsed.path):
        return "PAGE_AUDIO_VIDEO"
    if "youtu.be" in host:
        return "PAGE_AUDIO_VIDEO"
    return None
