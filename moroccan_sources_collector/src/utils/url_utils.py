"""Fonctions utilitaires partag?es par plusieurs ?tapes du pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import hashlib

import tldextract

TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "source",
    "session",
    "tracking",
    "sid",
    "phpsessid",
    "ref_src",
}


def normalize_url(url: str, base_url: str | None = None) -> str:
    """Normalise une valeur afin de rendre les comparaisons et d?duplications fiables."""
    if base_url:
        url = urljoin(base_url, url)
    # Parse before decoding: encoded separators are part of paths/query values.
    # parse_qsl below decodes query components once; urlencode re-encodes them.
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lk = key.lower()
        if lk in TRACKING_PARAMS or any(lk.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def canonicalize_for_fingerprint(url: str) -> str:
    """Construit une forme canonique stable pour comparer ou stocker la ressource."""
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    netloc = parsed.netloc.removeprefix("m.")
    path = parsed.path
    for suffix in ("/amp", "/print"):
        if path.endswith(suffix):
            path = path[: -len(suffix)] or "/"
    query = parsed.query
    return urlunparse(("", netloc, path, "", query, ""))


def url_fingerprint(url: str) -> str:
    """D?crit le fonctionnement de `url_fingerprint` et retourne le r?sultat attendu par le module."""
    return hashlib.sha256(canonicalize_for_fingerprint(url).encode("utf-8")).hexdigest()


def text_fingerprint(text: str) -> str:
    """D?crit le fonctionnement de `text_fingerprint` et retourne le r?sultat attendu par le module."""
    compact = " ".join((text or "").lower().split())
    return hashlib.sha256(compact[:5000].encode("utf-8")).hexdigest()


def get_domain(url: str) -> str:
    """D?crit le fonctionnement de `get_domain` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    return parsed.netloc.lower().removeprefix("www.")


def get_registered_domain(url: str) -> str:
    """D?crit le fonctionnement de `get_registered_domain` et retourne le r?sultat attendu par le module."""
    ext = tldextract.extract(url)
    if not ext.domain:
        return get_domain(url)
    return ".".join(part for part in [ext.domain, ext.suffix] if part)


def is_http_url(url: str) -> bool:
    """Retourne un bool?en indiquant si la valeur respecte une condition pr?cise."""
    return urlparse(url).scheme in {"http", "https"}


def deduplicate_urls(urls: list[str]) -> list[str]:
    """D?crit le fonctionnement de `deduplicate_urls` et retourne le r?sultat attendu par le module."""
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        normalized = normalize_url(url)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


@dataclass
class LinkCandidate:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de LinkCandidate."""
    url: str
    source_name: str
    source_url: str
    source_category: str
    source_priority: str
    discovery_method: str
    depth: int = 0
    anchor_text: str = ""
