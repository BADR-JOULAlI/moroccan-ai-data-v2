"""Module historique d?expansion du catalogue ? partir de sources existantes."""

from __future__ import annotations

from dataclasses import dataclass

from src.expansion.existing_catalog import ExistingCatalog
from src.utils.url_utils import normalize_url, text_fingerprint, url_fingerprint


@dataclass
class DuplicateDecision:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de DuplicateDecision."""
    is_duplicate: bool
    duplicate_of: str = ""
    duplicate_type: str = ""
    reason: str = ""
    similarity: float = 0.0


class DuplicateDetector:
    """Classe responsable de la d?tection et de la d?cision associ?es ? DuplicateDetector."""
    def __init__(self, existing: ExistingCatalog):
        """D?crit le fonctionnement de `__init__` et retourne le r?sultat attendu par le module."""
        self.normalized = set(existing.normalized_urls)
        self.fingerprints = set(existing.fingerprints)
        self.content_hashes: dict[str, str] = {}

    def check_url(self, url: str) -> DuplicateDecision:
        """V?rifie l??tat ou la conformit? d?une ressource."""
        normalized = normalize_url(url)
        fp = url_fingerprint(normalized)
        if normalized in self.normalized:
            return DuplicateDecision(True, normalized, "url_exacte", "URL deja presente apres normalisation", 1.0)
        if fp in self.fingerprints:
            return DuplicateDecision(True, normalized, "url_fingerprint", "Empreinte URL deja presente", 0.98)
        return DuplicateDecision(False)

    def add_url(self, url: str) -> None:
        """D?crit le fonctionnement de `add_url` et retourne le r?sultat attendu par le module."""
        normalized = normalize_url(url)
        self.normalized.add(normalized)
        self.fingerprints.add(url_fingerprint(normalized))

    def check_content(self, url: str, text: str) -> DuplicateDecision:
        """V?rifie l??tat ou la conformit? d?une ressource."""
        if not text:
            return DuplicateDecision(False)
        fp = text_fingerprint(text)
        if fp in self.content_hashes:
            return DuplicateDecision(True, self.content_hashes[fp], "contenu_identique", "Hash de contenu deja vu", 1.0)
        self.content_hashes[fp] = url
        return DuplicateDecision(False)
