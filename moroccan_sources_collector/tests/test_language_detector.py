"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

from src.analysis.language_detector import detect_language
from src.utils.text_utils import arabic_ratio


def test_arabic_script_detection():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    assert arabic_ratio("السلام عليكم test") > 50


def test_language_detector_arabic_standard():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    result = detect_language("هذا نص عربي عن الثقافة المغربية والتراث المغربي")
    assert result["Langue_principale"] == "arabe_standard_probable"
