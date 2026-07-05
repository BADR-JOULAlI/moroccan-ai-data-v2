from __future__ import annotations

from pathlib import Path

import yaml


def load_seed_sources(path: Path, category: str | None = None) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    if not category:
        return sources
    mapping = {
        "darija": {"Darija", "Dictionnaire_francais_darija", "Lexique_francais_darija"},
        "culture": {"Traditions", "Patrimoine_materiel", "Patrimoine_immateriel", "Gastronomie", "Artisanat"},
        "parallel": {"Dictionnaire_francais_darija", "Lexique_francais_darija", "Phrases_paralleles"},
    }
    allowed = mapping.get(category.lower(), {category})
    return [source for source in sources if source.get("category") in allowed]
