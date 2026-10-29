"""Regression tests for selection from extracted page content."""

import copy

import pytest

from src.analysis.collection_policy import apply_darija_threshold


def test_threshold_changes_actual_content_selection_at_boundary():
    record = {"Texte_extrait": "wach alpha beta gamma delta", "Langue_principale": "darija_latine"}

    accepted = apply_darija_threshold(record, 0.2)
    reviewed = apply_darija_threshold(record, 0.21)

    assert accepted["Densite_darija"] == reviewed["Densite_darija"] == 0.2
    assert accepted["Eligible_collecte"] is True
    assert accepted["Decision_linguistique"] == "Conserver"
    assert accepted["Motif_selection"] == "densite_darija_suffisante"
    assert reviewed["Eligible_collecte"] is False
    assert reviewed["Decision_linguistique"] == "A_recontroler"
    assert reviewed["Seuil_darija"] == 0.21


def test_seed_url_and_title_cannot_supply_missing_darija_content():
    record = {
        "Texte_extrait": "Les résultats financiers annuels indiquent une croissance stable.",
        "URL_finale": "https://example.ma/darija/wach/daba",
        "Nom_source": "wach daba darija",
        "Titre": "wach daba darija",
        "Description_source": "wach daba darija",
        "Categorie_principale": "Darija",
        "Langue_principale": "darija_latine",
    }

    selected = apply_darija_threshold(record, 0.15)

    assert selected["Densite_darija"] == 0
    assert selected["Eligible_collecte"] is False
    assert selected["Decision_linguistique"] == "A_recontroler"


def test_context_word_does_not_artificially_raise_density():
    record = {"Texte_extrait": "Le Maroc présente des résultats financiers annuels et des indicateurs économiques."}

    selected = apply_darija_threshold(record, 0.15)

    assert selected["Densite_darija"] == 0
    assert selected["Eligible_collecte"] is False


@pytest.mark.parametrize("threshold", [0.15, 1])
def test_standard_arabic_is_an_explicit_exception(threshold):
    record = {"Texte_extrait": "أعلنت الوزارة عن إطلاق البرنامج الوطني الجديد", "Type_contenu": "HTML"}

    selected = apply_darija_threshold(record, threshold)

    assert selected["Eligible_collecte"] is True
    assert selected["Decision_linguistique"] == "Conserver"
    assert selected["Motif_selection"] == "exception_arabe_standard"


def test_confirmed_parallel_content_is_an_explicit_exception():
    record = {"Texte_extrait": "Bonjour signifie salam.", "Contenu_parallele": "Oui"}

    selected = apply_darija_threshold(record, 1)

    assert selected["Eligible_collecte"] is True
    assert selected["Motif_selection"] == "exception_francais_darija_parallele"


@pytest.mark.parametrize("category", ["Traditions", "Patrimoine_materiel", "Gastronomie"])
def test_moroccan_cultural_content_is_preserved(category):
    record = {
        "Texte_extrait": "Les traditions du Maroc et son patrimoine culturel sont présentés dans cette exposition.",
        "Categorie_principale": category,
        "Langue_principale": "autre_langue",
    }

    selected = apply_darija_threshold(record, 1)

    assert selected["Eligible_collecte"] is True
    assert selected["Motif_selection"] == "exception_culture_marocaine"


@pytest.mark.parametrize(
    "text",
    [
        "Cette page présente les résultats financiers annuels de plusieurs entreprises.",
        "Cette page présente le patrimoine et les traditions de la France.",
        "Le Maroc présente des résultats financiers annuels et des indicateurs économiques.",
    ],
)
def test_culture_seed_alone_does_not_make_content_eligible(text):
    record = {"Texte_extrait": text, "Categorie_principale": "Traditions", "Nom_source": "Culture du Maroc"}

    selected = apply_darija_threshold(record, 0.15)

    assert selected["Eligible_collecte"] is False


def test_rejected_foreign_content_remains_explicitly_excluded():
    selected = apply_darija_threshold({
        "Texte_extrait": "The annual financial results show stable growth across different markets.",
        "Decision_linguistique": "Exclure",
    }, 0.15)

    assert selected["Eligible_collecte"] is False
    assert selected["Decision_linguistique"] == "Exclure"


def test_unavailable_html_is_reviewed_without_using_metadata_as_content():
    selected = apply_darija_threshold({
        "Texte_extrait": "", "Titre": "wach daba", "Type_contenu": "HTML", "Contenu_parallele": "Oui",
    }, 0.15)

    assert selected["Densite_darija"] is None
    assert selected["Eligible_collecte"] is False
    assert selected["Decision_linguistique"] == "A_recontroler"
    assert selected["Motif_selection"] == "texte_extrait_absent"


@pytest.mark.parametrize("kind", ["PDF", "JSON", "XML", "Audio", "Video"])
def test_non_html_resources_wait_for_human_validation_and_later_extraction(kind):
    selected = apply_darija_threshold({"Type_contenu": kind}, 0.15)

    assert selected["Eligible_collecte"] is True
    assert selected["Decision_linguistique"] == "A_recontroler"
    assert selected["Densite_darija"] is None
    assert selected["Motif_selection"] == "contenu_non_textuel_a_valider"


def test_zero_disables_only_density_filter_and_never_overrides_access_rules():
    record = {
        "Texte_extrait": "Un rapport financier présente les résultats annuels.",
        "Decision_linguistique": "A_recontroler",
        "Robots_txt": "Non",
        "Autorisation_collecte": "Non",
    }

    selected = apply_darija_threshold(record, 0)

    assert selected["Eligible_collecte"] is True
    assert selected["Decision_linguistique"] == "A_recontroler"
    assert selected["Motif_selection"] == "filtre_densite_desactive"
    assert selected["Robots_txt"] == selected["Autorisation_collecte"] == "Non"


def test_policy_does_not_mutate_input_record():
    record = {"Texte_extrait": "wach daba", "Extra": {"keep": "unchanged"}}
    original = copy.deepcopy(record)

    selected = apply_darija_threshold(record, 0.15)

    assert record == original
    assert selected is not record


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_density_threshold_is_rejected(threshold):
    with pytest.raises(ValueError, match="entre 0 et 1"):
        apply_darija_threshold({}, threshold)
