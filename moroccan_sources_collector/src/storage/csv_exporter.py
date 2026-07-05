from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_csv(records: list[dict], path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).reindex(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
