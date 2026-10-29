"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

import pytest

from src.utils.url_utils import deduplicate_urls, normalize_url, url_fingerprint


def test_normalize_url_removes_tracking_and_fragment():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    url = "HTTPS://www.Example.com/path/?utm_source=x&b=2&a=1#frag"
    assert normalize_url(url) == "https://example.com/path?a=1&b=2"


def test_deduplicate_urls():
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    urls = ["https://www.example.com?a=1&utm_medium=x", "https://example.com/?a=1"]
    assert deduplicate_urls(urls) == ["https://example.com/?a=1"]


@pytest.mark.parametrize(
    "suffix",
    [
        "/doc/a%23b",
        "/doc/A%2FB",
        "/doc/a%3Fb",
        "/doc/a%3Bb",
        "/search?q=art%26culture",
        "/search?q=C%2B%2B",
        "/search?q=art%2526culture",
    ],
)
def test_normalize_url_preserves_encoded_resource(suffix):
    """Encoded separators belong to the resource, not the URL structure."""
    url = f"https://example.ma{suffix}"

    assert normalize_url(url) == url
    assert normalize_url(normalize_url(url)) == url


def test_normalize_relative_encoded_path_and_query():
    url = normalize_url(
        "../doc/a%23b?q=art%26culture&utm_source=catalogue#heading",
        base_url="https://www.example.ma/catalogue/page",
    )

    assert url == "https://example.ma/doc/a%23b?q=art%26culture"


@pytest.mark.parametrize(
    ("encoded_url", "different_resource"),
    [
        ("https://example.ma/doc/a%23b", "https://example.ma/doc/a#b"),
        ("https://example.ma/doc/A%2FB", "https://example.ma/doc/A/B"),
        ("https://example.ma/search?q=art%26culture", "https://example.ma/search?q=art&culture="),
        ("https://example.ma/search?q=C%2B%2B", "https://example.ma/search?q=C++"),
    ],
)
def test_fingerprint_does_not_merge_distinct_encoded_resources(encoded_url, different_resource):
    assert url_fingerprint(encoded_url) != url_fingerprint(different_resource)
    assert len(deduplicate_urls([encoded_url, different_resource])) == 2
