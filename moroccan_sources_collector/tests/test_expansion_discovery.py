from src.expansion.duplicate_detector import DuplicateDetector
from src.expansion.existing_catalog import ExistingCatalog
from src.utils.url_utils import normalize_url, url_fingerprint


def test_duplicate_detector_rejects_existing_normalized_url():
    existing_url = normalize_url("https://www.example.com/page?utm_source=x")
    catalog = ExistingCatalog([], {existing_url}, set(), {existing_url}, {"example.com"}, {url_fingerprint(existing_url)})
    detector = DuplicateDetector(catalog)
    decision = detector.check_url("http://example.com/page")
    assert decision.is_duplicate


def test_url_fingerprint_normalizes_scheme_www_and_tracking():
    assert url_fingerprint("https://www.example.com/a?utm_campaign=x") == url_fingerprint("http://example.com/a")
