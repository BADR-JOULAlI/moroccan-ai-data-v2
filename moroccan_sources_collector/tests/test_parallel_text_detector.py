"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

from src.analysis.parallel_text_detector import detect_parallel_text


def test_detect_parallel_french_darija_table():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    html = """
    <table><tr><td>Bonjour</td><td>Salam</td></tr>
    <tr><td>Merci beaucoup</td><td>Chokran bezzaf</td></tr></table>
    """
    result = detect_parallel_text(html, "Bonjour | Salam\nMerci beaucoup | Chokran bezzaf")
    assert result["Contenu_parallele"] == "Oui"
    assert result["Nombre_paires_detectees"] >= 2
    assert result["Type_alignement"] == "francais_darija_latine"
