"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

from src.analysis.darija_detector import calculate_darija_score, detect_arabizi_tokens, detect_darija


def test_detect_darija_arabic():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("واش غادي تجي دابا ولا باقي؟")
    assert result["Langue_principale"] == "darija_arabe"
    assert result["Score_darija"] >= 65
    assert result["Decision_linguistique"] == "Conserver"


def test_detect_darija_latin():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("wach nta labas? ana mzyan daba")
    assert result["Langue_principale"] == "darija_latine"
    assert "wach" in result["Mots_darija_detectes"]


def test_detect_arabizi():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("3lach ma jitich? 7na tsennak bzaf")
    assert result["Arabizi_detecte"] == "Oui"
    assert result["Langue_principale"] == "darija_arabizi"
    assert "3lach" in result["Tokens_arabizi_detectes"]
    assert "7na" in result["Tokens_arabizi_detectes"]


def test_year_is_not_arabizi():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("Rapport culturel publié en 2024")
    assert result["Arabizi_detecte"] == "Non"
    assert result["Score_darija"] < 20


def test_technical_tokens_are_not_arabizi():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("Python3 utilise UTF8 et HTTP2")
    assert result["Arabizi_detecte"] == "Non"
    assert result["Score_darija"] <= 5
    assert detect_arabizi_tokens("sha256 utf8 ipv4 html5 page2 dataset2025") == []


def test_arabic_standard_probable_not_darija():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("أعلنت الوزارة عن إطلاق البرنامج الوطني الجديد")
    assert result["Langue_principale"] == "arabe_standard_probable"
    assert result["Langue_principale"] != "darija_arabe"


def test_weak_word_alone_is_not_high_confidence():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("مرحبا")
    assert result["Langue_principale"] != "darija_arabe"
    assert result["Confiance_darija"] != "elevee"


def test_repetition_is_capped():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("wach wach wach wach wach")
    assert result["Score_darija"] < 65


def test_social_repeated_letters_are_normalized_latin():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("waaaach nta bzaaaaf mzyan daba")
    assert result["is_darija"] is True
    assert result["Langue_principale"] == "darija_latine"
    assert result["Densite_darija"] >= 0.5


def test_density_score_contract_for_social_text():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = calculate_darija_score("3laaach bghiti hadchi daba?")
    assert result["is_darija"] is True
    assert result["score"] >= 0.2
    assert result["detected_variant"] == "darija_arabizi"
    assert result["total_tokens"] >= result["matched_tokens"]


def test_phrases_raise_score():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("ما كاينش مشكل، خليها على الله")
    assert result["Expressions_darija_detectees"]
    assert result["Score_darija"] >= 65


def test_french_darija_probable():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("Bonjour veut dire salam, et comment allez-vous se dit kidayr labas")
    assert result["Langue_principale"] in {"darija_latine", "francais_darija_probable"}
    assert result["Score_darija"] >= 40


def test_empty_and_none_do_not_crash():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    for value in ["", None]:
        result = detect_darija(value)
        assert result["Score_darija"] == 0
        assert result["Decision_linguistique"] in {"A_recontroler", "Exclure"}


def test_regression_fields_available():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_darija("wach nta labas")
    for key in [
        "Score_darija",
        "Mots_darija_detectes",
        "Langue_principale",
        "Decision_linguistique",
        "Score_lexical",
        "Score_expressions",
        "Version_lexique",
    ]:
        assert key in result


def test_long_text_reasonable():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    text = ("هذا نص طويل عن الثقافة المغربية. " * 200) + " wach daba dyalna bzaf"
    result = detect_darija(text)
    assert result["Score_darija"] >= 20
