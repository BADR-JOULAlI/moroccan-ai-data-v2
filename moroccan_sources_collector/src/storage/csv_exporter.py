"""Module de stockage et d?export des donn?es du pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_csv(records: list[dict], path: Path, columns: list[str]) -> None:
    """?crit les donn?es transform?es dans un format de sortie exploitable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).reindex(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
