from __future__ import annotations

import os


class OptionalSearchAdapter:
    """Placeholder for API-backed search. It never blocks the seed-source workflow."""

    def available(self) -> bool:
        return bool(os.getenv("BING_SEARCH_API_KEY") or os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY"))

    def search(self, query: str, limit: int = 10) -> list[str]:
        return []
