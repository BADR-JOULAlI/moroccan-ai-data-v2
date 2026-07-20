"""Fonctions utilitaires partag?es par plusieurs ?tapes du pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


def setup_logging(log_dir: Path) -> None:
    """D?crit le fonctionnement de `setup_logging` et retourne le r?sultat attendu par le module."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "collector.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


def log_error(log_dir: Path, url: str, stage: str, error: str) -> None:
    """D?crit le fonctionnement de `log_error` et retourne le r?sultat attendu par le module."""
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "stage": stage,
        "error": error,
    }
    with (log_dir / "errors.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
