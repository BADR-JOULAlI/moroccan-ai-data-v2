"""Website discovery does not admit or fetch excluded candidates."""

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from src.discovery import catalog_crawler
from src.discovery.catalog_crawler import CatalogCrawler
from src.discovery.link_extractor import DiscoveredLink


@pytest.fixture
def crawler(monkeypatch):
    # Avoid PSL updates while exercising local discovery behavior.
    monkeypatch.setattr(catalog_crawler, "get_registered_domain", lambda url: urlsplit(url).hostname)
    return CatalogCrawler({"max_depth": 2, "delay_between_requests_seconds": 0}, Path("unused"))


def seed(url="https://example.ma/", **kwargs):
    return {"name": "Moroccan catalogue", "url": url, "discovery_method": "catalog", **kwargs}


def check(final_url, html="", robots="Oui"):
    return SimpleNamespace(
        final_url=final_url,
        status_lien="Accessible",
        content_type="text/html",
        html=html,
        robots_txt=robots,
    )


@pytest.mark.parametrize(
    "url", ["https://m.youtube.com:443/watch?v=1", "https://github.com./repo", "", "ftp://example.ma/file"]
)
def test_http_seed_outside_scope_never_reaches_robots_or_http(crawler, monkeypatch, url):
    def unexpected_request(*args, **kwargs):
        pytest.fail("An excluded seed must not make any network request")

    monkeypatch.setattr(catalog_crawler, "robots_status", unexpected_request)
    monkeypatch.setattr(catalog_crawler, "check_url", unexpected_request)

    assert crawler.crawl([seed(url)], max_links=10) == []
    assert crawler._crawl_http([seed(url)], max_links=10) == []


def test_excluded_http_children_are_neither_returned_nor_downloaded(crawler, monkeypatch):
    fetched = []
    permissions = []

    def fake_robots(url, user_agent):
        permissions.append(url)
        return "Oui"

    def fake_check(url, **kwargs):
        fetched.append(url)
        html = """
            <a href="https://youtube.com/watch?v=1">Darija video</a>
            <a href="https://github.com/owner/corpus">Moroccan corpus</a>
            <a href="/article">Culture</a>
        """ if url == "https://example.ma/" else ""
        return check(url, html)

    monkeypatch.setattr(catalog_crawler, "robots_status", fake_robots)
    monkeypatch.setattr(catalog_crawler, "check_url", fake_check)

    results = crawler._crawl_http([seed()], max_links=10)

    assert [result.url for result in results] == ["https://example.ma/", "https://example.ma/article"]
    assert fetched == permissions == ["https://example.ma/", "https://example.ma/article"]


@pytest.mark.parametrize("permission", ["Non", "A_verifier", "Inconnue"])
@pytest.mark.parametrize("max_depth", [0, 2])
def test_robots_refused_or_unknown_seed_is_not_returned_or_downloaded(crawler, monkeypatch, permission, max_depth):
    crawler.settings["max_depth"] = max_depth
    monkeypatch.setattr(catalog_crawler, "robots_status", lambda *args: permission)

    def unexpected_request(*args, **kwargs):
        pytest.fail("No content request is allowed without robots permission")

    monkeypatch.setattr(catalog_crawler, "check_url", unexpected_request)

    assert crawler._crawl_http([seed()], max_links=10) == []


@pytest.mark.parametrize("target", ["https://youtube.com/watch?v=1", "https://github.com:443/owner/corpus"])
def test_excluded_redirect_is_not_returned_or_explored(crawler, monkeypatch, target):
    fetched = []
    monkeypatch.setattr(catalog_crawler, "robots_status", lambda *args: "Oui")

    def fake_check(url, **kwargs):
        fetched.append(url)
        return check(target, '<a href="https://other.ma/corpus">Moroccan corpus</a>')

    monkeypatch.setattr(catalog_crawler, "check_url", fake_check)

    assert crawler._crawl_http([seed()], max_links=10) == []
    assert fetched == ["https://example.ma/"]


@pytest.mark.parametrize("permission", ["Non", "A_verifier"])
def test_redirect_robots_result_is_reused_and_candidate_is_not_returned(crawler, monkeypatch, permission):
    permissions = []

    def initial_permission(url, user_agent):
        permissions.append(url)
        return "Oui"

    monkeypatch.setattr(catalog_crawler, "robots_status", initial_permission)
    monkeypatch.setattr(catalog_crawler, "check_url", lambda *args, **kwargs: check("https://new.ma/", robots=permission))

    assert crawler._crawl_http([seed()], max_links=10) == []
    assert permissions == ["https://example.ma/"]


def test_internal_link_scope_uses_final_redirect_domain(crawler, monkeypatch):
    crawler.settings["max_depth"] = 1
    monkeypatch.setattr(catalog_crawler, "robots_status", lambda *args: "Oui")
    monkeypatch.setattr(
        catalog_crawler,
        "check_url",
        lambda *args, **kwargs: check("https://new.ma/", '<a href="/about">About</a>'),
    )

    results = crawler._crawl_http([seed()], max_links=10)

    assert [result.url for result in results] == ["https://example.ma/", "https://new.ma/about"]


@pytest.mark.asyncio
async def test_browser_seeds_and_returned_links_share_website_policy(crawler, monkeypatch):
    visited = []

    class LocalAdapter:
        def __init__(self, config):
            assert config.enforce_web_policy

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def rendered_page_links(self, url, limit):
            visited.append(url)
            return [
                DiscoveredLink("https://youtube.com/watch?v=1", url, "rendered_page"),
                DiscoveredLink("https://github.com/owner/corpus", url, "rendered_page"),
                DiscoveredLink("https://example.ma/article", url, "rendered_page"),
            ]

    monkeypatch.setattr(catalog_crawler, "PlaywrightDiscoveryAdapter", LocalAdapter)
    seeds = [
        seed(use_playwright=True),
        seed("https://github.com/owner/repo", use_playwright=True),
        seed("https://example.ma/social", discovery_method="youtube_search", use_playwright=True),
    ]

    records = await crawler.discover_structured_async(seeds, max_links=10)

    assert visited == ["https://example.ma/"]
    assert [record["url"] for record in records] == ["https://example.ma/article"]


@pytest.mark.asyncio
async def test_excluded_browser_seeds_do_not_open_a_browser(crawler, monkeypatch):
    def unexpected_browser(*args, **kwargs):
        pytest.fail("An excluded seed must not start the browser")

    monkeypatch.setattr(catalog_crawler, "PlaywrightDiscoveryAdapter", unexpected_browser)

    assert await crawler.discover_structured_async([seed("https://fb.watch/1", use_playwright=True)]) == []
