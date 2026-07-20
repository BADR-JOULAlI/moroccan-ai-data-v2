"""Tests automatis?s qui documentent et prot?gent le comportement attendu du projet."""

from __future__ import annotations

from pathlib import Path

from src.discovery.catalog_crawler import CatalogCrawler
from src.discovery.link_extractor import (
    extract_facebook_links,
    extract_facebook_post_links,
    extract_production_links,
    extract_youtube_links,
    google_search_url,
    youtube_channel_tab_url,
    youtube_search_url,
)


def test_youtube_search_url_encodes_query() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    assert youtube_search_url("darija podcast") == "https://www.youtube.com/results?search_query=darija+podcast"


def test_google_search_url_encodes_dork() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    assert google_search_url('site:facebook.com "darija"') == "https://www.google.com/search?q=site%3Afacebook.com+%22darija%22"


def test_youtube_channel_tab_url_appends_videos() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    assert youtube_channel_tab_url("https://www.youtube.com/@SomeMoroccanChannel") == "https://youtube.com/@SomeMoroccanChannel/videos"


def test_extract_youtube_videos_shorts_and_channels() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    html = """
    <a href="/watch?v=ABCdef12345">Darija podcast</a>
    <a href="https://youtu.be/XYZ98765432?si=x">Moroccan documentary</a>
    <a href="/shorts/SHORT123456">Short</a>
    <a href="/@CultureMaroc">Channel</a>
    <a href="/watch?v=ABCdef12345&utm_source=x">Duplicate</a>
    """

    links = extract_youtube_links(html, "https://www.youtube.com/results?search_query=darija", limit=10)
    urls = [link.url for link in links]

    assert "https://www.youtube.com/watch?v=ABCdef12345" in urls
    assert "https://www.youtube.com/watch?v=XYZ98765432" in urls
    assert "https://www.youtube.com/shorts/SHORT123456" in urls
    assert "https://youtube.com/@CultureMaroc" in urls
    assert len(urls) == len(set(urls))


def test_extract_production_links_youtube_never_returns_search_page() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    html = """
    <a href="/results?search_query=darija">Search page</a>
    <a href="/watch?v=ABCdef12345&pp=tracking&t=90">Video</a>
    <a href="https://www.youtube.com/@CultureMaroc?si=abc">Creator</a>
    <a href="/feed/history">Navigation</a>
    """

    urls = extract_production_links(html, "youtube")

    assert urls == [
        "https://www.youtube.com/watch?v=ABCdef12345",
        "https://youtube.com/@CultureMaroc",
    ]
    assert all("/results" not in url for url in urls)


def test_extract_facebook_posts_and_permalinks() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    html = """
    <a href="/CultureMarocaine/posts/123456789?utm_source=x">Post</a>
    <a href="https://www.facebook.com/permalink.php?story_fbid=111&id=222">Permalink</a>
    <a href="/CultureMarocaine/about">Ignore</a>
    """

    links = extract_facebook_post_links(html, "https://www.facebook.com/CultureMarocaine", limit=10)
    urls = [link.url for link in links]

    assert "https://facebook.com/CultureMarocaine/posts/123456789" in urls
    assert "https://facebook.com/permalink.php?id=222&story_fbid=111" in urls
    assert all(link.platform == "Facebook" for link in links)


def test_extract_facebook_links_keeps_only_concrete_content_and_cleans_tracking() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    html = """
    <a href="/CultureMarocaine/posts/123456789?__cft__[0]=abc&__tn__=%2CO&fbclid=zzz">Post</a>
    <a href="https://www.facebook.com/watch/?v=998877&__tn__=x">Watch</a>
    <a href="https://www.facebook.com/reel/445566?fbclid=x">Reel</a>
    <a href="https://www.facebook.com/permalink.php?story_fbid=111&id=222&__cft__[0]=abc">Permalink</a>
    <a href="https://www.facebook.com/login/">Login</a>
    <a href="https://www.facebook.com/groups/123456">Group navigation</a>
    <a href="https://www.facebook.com/pages/category/Community">Pages navigation</a>
    <a href="https://www.facebook.com/shares/view?id=1">Shares navigation</a>
    """

    urls = extract_facebook_links(html, "https://www.facebook.com/CultureMarocaine")

    assert urls == [
        "https://facebook.com/CultureMarocaine/posts/123456789",
        "https://facebook.com/watch?v=998877",
        "https://facebook.com/reel/445566",
        "https://facebook.com/permalink.php?id=222&story_fbid=111",
    ]


def test_extract_production_links_google_dork_returns_only_clean_targets() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    html = """
    <div id="search">
      <div class="g"><a href="/search?q=site:facebook.com+darija">Google search</a></div>
      <div class="g"><a href="/url?q=https%3A%2F%2Fwww.facebook.com%2FCultureMarocaine%2Fposts%2F123%3Ffbclid%3Dabc%26__tn__%3Dx&sa=U">FB post</a></div>
      <div class="g"><a href="https://www.facebook.com/login/">Login</a></div>
      <div class="g"><a href="https://www.facebook.com/permalink.php?story_fbid=456&id=789&__cft__[0]=x">Permalink</a></div>
      <div class="g"><a href="https://www.google.com/policies/terms/">Google terms</a></div>
    </div>
    """

    urls = extract_production_links(html, "google")

    assert urls == [
        "https://facebook.com/CultureMarocaine/posts/123",
        "https://facebook.com/permalink.php?id=789&story_fbid=456",
    ]
    assert all("google.com" not in url for url in urls)


def test_catalog_crawler_dedupes_structured_records() -> None:
    """V?rifie le comportement attendu d?une fonctionnalit? du projet."""
    records = [
        {"url": "https://www.youtube.com/watch?v=ABC&utm_source=x"},
        {"url": "https://youtube.com/watch?v=ABC"},
        {"url": "https://facebook.com/page/posts/1"},
    ]

    unique = CatalogCrawler({}, Path("."))._dedupe_records(records)

    assert [record["url"] for record in unique] == [
        "https://youtube.com/watch?v=ABC",
        "https://facebook.com/page/posts/1",
    ]
