"""Module d?audit technique des URLs et des fichiers Excel g?n?r?s."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.utils.url_utils import normalize_url

GITHUB_REPO_RE = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")


def extract_concrete_links(url: str, html: str, limit: int = 20) -> list[str]:
    """Extrait les informations utiles depuis le contenu fourni et filtre le bruit."""
    host = urlparse(url).netloc.lower()
    soup = BeautifulSoup(html or "", "lxml")
    results: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        candidate = ""
        if "github.com" in host:
            match = GITHUB_REPO_RE.match(href)
            if match and match.group(1) not in {"features", "topics", "login", "signup"}:
                candidate = f"https://github.com/{match.group(1)}/{match.group(2)}"
        elif "huggingface.co" in host:
            if href.startswith("/datasets/") and len(href.strip("/").split("/")) >= 3:
                candidate = urljoin("https://huggingface.co", href)
        elif "kaggle.com" in host:
            if "/datasets/" in href:
                candidate = urljoin("https://www.kaggle.com", href)
        elif "zenodo.org" in host:
            if "/records/" in href:
                candidate = urljoin("https://zenodo.org", href)
        elif "arxiv.org" in host:
            if "/abs/" in href:
                candidate = urljoin("https://arxiv.org", href)
        elif "aclanthology.org" in host:
            if re.search(r"/\d{4}\.", href):
                candidate = urljoin("https://aclanthology.org", href)
        if candidate:
            normalized = normalize_url(candidate)
            if normalized not in results:
                results.append(normalized)
        if len(results) >= limit:
            break
    return results
