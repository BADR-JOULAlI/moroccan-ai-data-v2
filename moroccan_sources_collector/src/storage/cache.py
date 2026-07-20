"""Module de stockage et d?export des donn?es du pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class JsonCache:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de JsonCache."""
    def __init__(self, path: Path, ttl_hours: int = 168):
        """D?crit le fonctionnement de `__init__` et retourne le r?sultat attendu par le module."""
        self.path = path
        self.ttl = timedelta(hours=ttl_hours)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.data = {}

    def get(self, key: str, force: bool = False) -> Any | None:
        """D?crit le fonctionnement de `get` et retourne le r?sultat attendu par le module."""
        if force or key not in self.data:
            return None
        item = self.data[key]
        timestamp = datetime.fromisoformat(item.get("timestamp"))
        if datetime.now(timezone.utc) - timestamp > self.ttl:
            return None
        return item.get("value")

    def set(self, key: str, value: Any) -> None:
        """D?crit le fonctionnement de `set` et retourne le r?sultat attendu par le module."""
        self.data[key] = {"timestamp": datetime.now(timezone.utc).isoformat(), "value": value}

    def save(self) -> None:
        """D?crit le fonctionnement de `save` et retourne le r?sultat attendu par le module."""
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.path)
