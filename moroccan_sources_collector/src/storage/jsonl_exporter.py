"""Module de stockage et d?export des donn?es du pipeline."""

from __future__ import annotations

import json
from pathlib import Path


def export_jsonl(records: list[dict], path: Path) -> None:
    """?crit les donn?es transform?es dans un format de sortie exploitable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict]:
    """Charge des donn?es ou une configuration depuis le disque et retourne une structure exploitable."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
