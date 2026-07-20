"""Tests du filtrage des seeds en mode sites web uniquement."""

from __future__ import annotations

from src.main import _regular_website_seeds


def test_regular_website_seeds_excludes_social_and_code_platforms() -> None:
    seeds = [
        {"name": "Culture", "url": "https://www.minculture.gov.ma/", "discovery_method": "catalog"},
        {"name": "YouTube", "query": "darija", "discovery_method": "youtube_search"},
        {"name": "Facebook", "query": "darija", "discovery_method": "google_facebook_dork"},
        {"name": "Kaggle", "url": "https://www.kaggle.com/search?q=darija", "discovery_method": "catalog"},
        {"name": "HuggingFace", "url": "https://huggingface.co/datasets?search=darija", "discovery_method": "catalog"},
        {"name": "GitHub", "url": "https://github.com/search?q=darija", "discovery_method": "catalog"},
    ]

    kept = _regular_website_seeds(seeds)

    assert kept == [{"name": "Culture", "url": "https://www.minculture.gov.ma/", "discovery_method": "catalog"}]
