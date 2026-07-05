from __future__ import annotations

from dataclasses import dataclass

from src.expansion.existing_catalog import ExistingCatalog
from src.utils.url_utils import normalize_url, text_fingerprint, url_fingerprint


@dataclass
class DuplicateDecision:
    is_duplicate: bool
    duplicate_of: str = ""
    duplicate_type: str = ""
    reason: str = ""
    similarity: float = 0.0


class DuplicateDetector:
    def __init__(self, existing: ExistingCatalog):
        self.normalized = set(existing.normalized_urls)
        self.fingerprints = set(existing.fingerprints)
        self.content_hashes: dict[str, str] = {}

    def check_url(self, url: str) -> DuplicateDecision:
        normalized = normalize_url(url)
        fp = url_fingerprint(normalized)
        if normalized in self.normalized:
            return DuplicateDecision(True, normalized, "url_exacte", "URL deja presente apres normalisation", 1.0)
        if fp in self.fingerprints:
            return DuplicateDecision(True, normalized, "url_fingerprint", "Empreinte URL deja presente", 0.98)
        return DuplicateDecision(False)

    def add_url(self, url: str) -> None:
        normalized = normalize_url(url)
        self.normalized.add(normalized)
        self.fingerprints.add(url_fingerprint(normalized))

    def check_content(self, url: str, text: str) -> DuplicateDecision:
        if not text:
            return DuplicateDecision(False)
        fp = text_fingerprint(text)
        if fp in self.content_hashes:
            return DuplicateDecision(True, self.content_hashes[fp], "contenu_identique", "Hash de contenu deja vu", 1.0)
        self.content_hashes[fp] = url
        return DuplicateDecision(False)
