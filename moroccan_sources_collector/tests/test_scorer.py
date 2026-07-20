"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

from src.scoring.scorer import score_record


def test_score_record_p0():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    record = {
        "URL_finale": "https://example.com/darija-dataset-morocco",
        "Description_source": "Darija parallel corpus",
        "Categorie_principale": "Dataset_IA",
        "Score_darija": 40,
        "Contenu_parallele": "Oui",
        "Licence": "Probablement",
        "Statut_lien": "Accessible",
        "Robots_txt": "Oui",
        "Priorite": "P1",
        "Statut_HTTP": 200,
    }
    scored = score_record(record)
    assert scored["Score_pertinence"] >= 70
    assert scored["Priorite"] == "P0"
