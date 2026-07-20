"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

from src.analysis.category_classifier import classify_category


def test_classify_dataset():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = classify_category("A Moroccan Arabic corpus dataset for Darija", "https://huggingface.co/datasets/x")
    assert result["Categorie_principale"] == "Dataset_IA"


def test_classify_dictionary():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = classify_category("French Darija dictionary and vocabulary", "https://example.com")
    assert result["Categorie_principale"] == "Dictionnaire_francais_darija"
