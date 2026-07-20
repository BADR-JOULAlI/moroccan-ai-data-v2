"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

from src.utils.url_utils import deduplicate_urls, normalize_url


def test_normalize_url_removes_tracking_and_fragment():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    url = "HTTPS://www.Example.com/path/?utm_source=x&b=2&a=1#frag"
    assert normalize_url(url) == "https://example.com/path?a=1&b=2"


def test_deduplicate_urls():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    urls = ["https://www.example.com?a=1&utm_medium=x", "https://example.com/?a=1"]
    assert deduplicate_urls(urls) == ["https://example.com/?a=1"]
