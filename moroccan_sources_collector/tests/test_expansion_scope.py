"""Expansion discovery must enforce the same website-only network policy."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.expansion import discovery_expander as expansion
from src.expansion.discovery_expander import CandidateUrl, ExpansionDiscoverer
from src.expansion.duplicate_detector import DuplicateDetector
from src.expansion.existing_catalog import ExistingCatalog
from src.utils.url_utils import get_domain
from src.validation.url_checker import UrlCheckResult
from src.validation.url_policy import is_regular_website_url


@pytest.fixture
def discoverer(monkeypatch):
    existing = ExistingCatalog([], set(), set(), set(), set(), set())
    monkeypatch.setattr(expansion, "get_registered_domain", get_domain)
    monkeypatch.setattr(expansion, "time", SimpleNamespace(sleep=lambda _: None))
    return ExpansionDiscoverer(existing, DuplicateDetector(existing), Path("unused"), {
        "max_depth": 2, "max_total_requests": 10, "user_agent": "ScopeTest/1.0",
    })


def checked(url, body="", content_type="text/html", status="Accessible", robots="Oui"):
    return UrlCheckResult(url, 200, status, content_type, False, html=body, robots_txt=robots)


def test_initial_candidates_filter_technical_curated_and_existing_domains(discoverer, monkeypatch):
    monkeypatch.setattr(expansion, "load_keywords", lambda *args: ["darija"])
    monkeypatch.setattr(expansion, "TECHNICAL_DOMAINS", [
        "https://github.com/search?q={q}", "https://huggingface.co/datasets?q={q}",
        "https://zenodo.org/search?q={q}",
    ])
    monkeypatch.setattr(expansion, "CURATED_BASES", [
        "https://www.youtube.com/@Darija", "https://www.facebook.com/darija", "https://example.ma/culture",
    ])
    discoverer.existing.domains.update({"github.com", "m.youtube.com", "example.org"})

    candidates = discoverer._initial_candidates(None)

    assert candidates
    assert all(is_regular_website_url(candidate.url) for candidate in candidates)
    assert {candidate.method for candidate in candidates} == {
        "platform_search", "curated_domain", "curated_common_path", "existing_domain", "domain_common_path",
    }
    assert any(candidate.url.startswith("https://zenodo.org/") for candidate in candidates)
    assert any(candidate.url == "https://example.org" for candidate in candidates)


@pytest.mark.parametrize("url", [
    "https://youtube.com/watch?v=darija", "https://m.facebook.com/darija",
    "https://github.com/owner/corpus", "https://huggingface.co/datasets/owner/darija",
    "https://kaggle.com/darija", "https://youtu.be/darija", "ftp://example.ma/corpus", "",
])
def test_direct_expansion_never_requests_excluded_or_invalid_urls(discoverer, monkeypatch, url):
    def forbidden_request(*args, **kwargs):
        pytest.fail("Excluded URL reached the network checker")

    monkeypatch.setattr(expansion, "check_url", forbidden_request)

    assert discoverer._expand_url(url, CandidateUrl(url, "test", "existing_domain")) == []


def test_discover_filters_initial_and_child_candidates_before_adding_or_requesting(discoverer, monkeypatch):
    allowed = "https://example.ma/culture"
    child = "https://example.ma/darija"
    excluded = "https://github.com/owner/darija"
    monkeypatch.setattr(discoverer, "_initial_candidates", lambda category: [
        CandidateUrl(excluded, "test", "existing_domain"),
        CandidateUrl(allowed, "test", "existing_domain"),
    ])
    requests = []

    def expand(url, parent):
        requests.append(url)
        return [CandidateUrl(excluded, "test", "page_link", depth=1), CandidateUrl(child, "test", "page_link", depth=2)]

    monkeypatch.setattr(discoverer, "_expand_url", expand)

    candidates, rejected = discoverer.discover(target=10, max_links_per_domain=10)

    assert [candidate.url for candidate in candidates] == [allowed, child]
    assert requests == [allowed]
    assert rejected == []


def test_html_expansion_uses_shared_checker_and_filters_platform_children(discoverer, monkeypatch):
    url = "https://example.ma/culture"
    body = """
    <a href="https://youtube.com/watch?v=darija">darija video</a>
    <a href="https://github.com/owner/corpus">moroccan corpus</a>
    <a href="https://example.ma/darija">darija dictionary</a>
    """
    requests = []

    def check(requested_url, **kwargs):
        requests.append((requested_url, kwargs))
        return checked(url, body)

    monkeypatch.setattr(expansion, "check_url", check)

    children = discoverer._expand_url(url, CandidateUrl(url, "test", "existing_domain"))

    assert [candidate.url for candidate in children] == ["https://example.ma/darija"]
    assert requests[0][1]["url_policy"] is is_regular_website_url
    assert requests[0][1]["user_agent"] == "ScopeTest/1.0"


@pytest.mark.parametrize("response", [
    checked("https://example.ma/private", status="Robots_interdit", robots="Non"),
    checked("https://example.ma/private", status="Robots_a_verifier", robots="A_verifier"),
    checked("https://github.com/owner/darija", '<a href="https://example.ma/darija">darija</a>'),
])
def test_blocked_or_redirected_off_scope_response_cannot_expand(discoverer, monkeypatch, response):
    monkeypatch.setattr(expansion, "check_url", lambda *args, **kwargs: response)

    assert discoverer._expand_url("https://example.ma/private", CandidateUrl("", "test", "existing_domain")) == []


def test_xml_sitemap_still_expands_allowed_urls(discoverer, monkeypatch):
    url = "https://example.ma/sitemap.xml"
    body = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://example.ma/darija?utm_source=test</loc></url>
    <url><loc>https://github.com/owner/corpus</loc></url>
    <url><loc>https://m.youtube.com/watch?v=darija</loc></url>
    <url><loc>ftp://example.ma/file</loc></url></urlset>"""
    monkeypatch.setattr(expansion, "check_url", lambda *args, **kwargs: checked(url, body, "application/xml"))

    children = discoverer._expand_url(url, CandidateUrl(url, "test", "existing_domain"))

    assert [candidate.url for candidate in children] == ["https://example.ma/darija"]
    assert children[0].method == "sitemap"


@pytest.mark.parametrize("content_type,body", [
    ("application/rss+xml", "<rss><channel><item><link>https://example.ma/darija</link></item><item><link>https://youtu.be/darija</link></item></channel></rss>"),
    ("application/atom+xml", '<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="/darija"/></entry><entry><link href="https://facebook.com/darija"/></entry></feed>'),
])
def test_rss_and_atom_keep_only_permitted_links(discoverer, monkeypatch, content_type, body):
    url = "https://example.ma/feed"
    monkeypatch.setattr(expansion, "check_url", lambda *args, **kwargs: checked(url, body, content_type))

    children = discoverer._expand_url(url, CandidateUrl(url, "test", "existing_domain"))

    assert [candidate.url for candidate in children] == ["https://example.ma/darija"]


def test_invalid_xml_is_ignored(discoverer):
    assert discoverer._parse_xml_links("<urlset>", "https://example.ma/sitemap.xml", CandidateUrl("", "test", "existing_domain")) == []
