"""Tests automatises pour l'export de validation manuelle."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.storage.jsonl_exporter import load_jsonl
from src.main import REVIEW_COLUMNS, export_crawler_input_from_review, export_manual_review


def test_manual_review_export_adds_empty_decision_column(tmp_path: Path) -> None:
    """Verifie que le CSV de revue laisse la decision a remplir manuellement."""
    path = tmp_path / "liens_a_valider_manuellement.csv"
    records = [
        {
            "Nom_source": "Source test",
            "URL_finale": "https://example.ma/darija",
            "Domaine": "example.ma",
            "Categorie_principale": "Darija",
            "Score_pertinence": 75,
            "Priorite": "P1",
            "Statut_HTTP": 200,
            "Statut_lien": "Accessible",
            "Robots_txt": "Oui",
            "Source_decouverte": "seed",
            "Mots_cles_associes": "darija",
        }
    ]

    export_manual_review(records, path)

    review = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    assert list(review.columns) == REVIEW_COLUMNS
    assert review.loc[0, "Decision_validation"] == ""
    assert review.loc[0, "URL_finale"] == "https://example.ma/darija"
    assert review.loc[0, "Notes_validation"] == ""


def test_crawler_input_export_keeps_only_accepted_rows(tmp_path: Path) -> None:
    """Verifie que seuls les liens acceptes manuellement alimentent le crawler."""
    review_path = tmp_path / "review.csv"
    urls_path = tmp_path / "crawler_urls.txt"
    manifest_path = tmp_path / "crawl_manifest.jsonl"
    review = pd.DataFrame([
        {
            "Decision_validation": "accept",
            "URL_finale": "https://www.example.ma/page?utm_source=test",
            "Domaine": "example.ma",
            "Nom_source": "Accepted",
            "Categorie_principale": "Darija",
            "Score_pertinence": 80,
            "Priorite": "P1",
            "Statut_HTTP": 200,
            "Statut_lien": "Accessible",
            "Robots_txt": "Oui",
            "Source_decouverte": "seed",
            "Mots_cles_associes": "darija",
            "Notes_validation": "bon lien",
        },
        {
            "Decision_validation": "reject",
            "URL_finale": "https://rejected.example.ma/page",
            "Domaine": "rejected.example.ma",
        },
        {
            "Decision_validation": "maybe",
            "URL_finale": "https://maybe.example.ma/page",
            "Domaine": "maybe.example.ma",
        },
    ])
    review.to_csv(review_path, index=False, encoding="utf-8-sig")

    summary = export_crawler_input_from_review(review_path, urls_path, manifest_path)

    assert summary["accepted_links"] == 1
    assert urls_path.read_text(encoding="utf-8").splitlines() == ["https://example.ma/page"]
    manifest = load_jsonl(manifest_path)
    assert manifest[0]["url"] == "https://example.ma/page"
    assert manifest[0]["review_decision"] == "accept"
    assert manifest[0]["review_notes"] == "bon lien"
