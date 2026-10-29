"""Enforce scope and robots before HTTP requests and redirects."""

import httpx
import pytest

from src.validation import robots_checker, url_checker


REAL_CLIENT = httpx.Client


@pytest.fixture(autouse=True)
def clean_robots_cache():
    robots_checker.clear_robots_cache()
    yield
    robots_checker.clear_robots_cache()


def install_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: REAL_CLIENT(transport=transport, **kwargs))


def test_robots_checked_before_head_and_get(monkeypatch):
    events = []

    def policy(url, user_agent, timeout, **kwargs):
        events.append(("ROBOTS", url))
        assert timeout == 0.7
        return "Oui"

    def handler(request):
        events.append((request.method, str(request.url)))
        return httpx.Response(200, headers={"content-type": "text/html"}, text="page")

    monkeypatch.setattr(url_checker, "robots_status", policy)
    install_transport(monkeypatch, handler)
    url = "https://example.test/page"
    result = url_checker.check_url(url, timeout=0.7)
    assert result.status_lien == "Accessible"
    assert result.html == "page"
    assert result.robots_txt == "Oui"
    assert events == [("ROBOTS", url), ("HEAD", url), ("ROBOTS", url), ("GET", url)]


@pytest.mark.parametrize("robots,status", [("Non", "Robots_interdit"), ("A_verifier", "Robots_a_verifier")])
def test_disallowed_or_unknown_robots_never_fetch_content(monkeypatch, robots, status):
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: robots)

    def handler(request):
        pytest.fail(f"Unexpected content request: {request.url}")

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/private")
    assert result.status_lien == status
    assert result.status_http is None
    assert result.robots_txt == robots
    assert not result.html


def test_robots_rechecked_before_get_fallback(monkeypatch):
    replies = iter(["Oui", "Non"])
    calls = []
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: next(replies))

    def handler(request):
        calls.append(request.method)
        return httpx.Response(405)

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/page")
    assert calls == ["HEAD"]
    assert result.status_lien == "Robots_interdit"


def test_get_fallback_after_head_error(monkeypatch):
    calls = []
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: "Oui")

    def handler(request):
        calls.append(request.method)
        if request.method == "HEAD":
            raise httpx.ReadTimeout("HEAD unsupported", request=request)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="ok")

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/page")
    assert calls == ["HEAD", "GET"]
    assert result.html == "ok"


def test_redirect_target_is_checked_before_content(monkeypatch):
    events = []

    def policy(url, *args, **kwargs):
        events.append(("ROBOTS", url))
        return "Non" if url.endswith("/private") else "Oui"

    def handler(request):
        events.append((request.method, str(request.url)))
        return httpx.Response(302, headers={"location": "/private"})

    install_transport(monkeypatch, handler)
    monkeypatch.setattr(url_checker, "robots_status", policy)
    result = url_checker.check_url("https://example.test/start")
    assert result.status_lien == "Robots_interdit"
    assert result.final_url == "https://example.test/private"
    assert result.redirection
    assert events == [
        ("ROBOTS", "https://example.test/start"),
        ("HEAD", "https://example.test/start"),
        ("ROBOTS", "https://example.test/private"),
    ]


def test_redirect_to_excluded_domain_is_not_requested(monkeypatch):
    requested = []
    checked = []

    def policy(url, *args, **kwargs):
        checked.append(url)
        return "Oui"

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://youtube.com/watch?v=123"})

    install_transport(monkeypatch, handler)
    monkeypatch.setattr(url_checker, "robots_status", policy)
    result = url_checker.check_url("https://example.test/start")
    assert result.status_lien == "Hors_perimetre"
    assert requested == ["https://example.test/start"]
    assert checked == requested


def test_get_redirect_is_also_checked(monkeypatch):
    requested = []
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: "Oui")

    def handler(request):
        requested.append((request.method, str(request.url)))
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-type": "text/html"})
        return httpx.Response(302, headers={"location": "https://github.com/example/corpus"})

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/start")
    assert result.status_lien == "Hors_perimetre"
    assert requested == [("HEAD", "https://example.test/start"), ("GET", "https://example.test/start")]


def test_allowed_relative_redirect_preserves_result(monkeypatch):
    requested = []
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: "Oui")

    def handler(request):
        requested.append((request.method, str(request.url)))
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/finish"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="final page")

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/start")
    assert result.status_lien == "Accessible_avec_redirection"
    assert result.final_url == "https://example.test/finish"
    assert result.html == "final page"
    assert requested == [
        ("HEAD", "https://example.test/start"),
        ("HEAD", "https://example.test/finish"),
        ("GET", "https://example.test/finish"),
    ]


def test_redirect_limit_stops_loop(monkeypatch):
    calls = []
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: "Oui")

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "/again"})

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/start")
    assert result.status_lien == "A_recontroler"
    assert "redirects" in result.error
    assert len(calls) == 11


def test_legacy_audit_can_explicitly_allow_platforms(monkeypatch):
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: "Oui")
    install_transport(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}))
    assert url_checker.check_url("https://github.com/example/corpus").status_lien == "Hors_perimetre"
    assert url_checker.check_url("https://github.com/example/corpus", url_policy=None).status_lien == "Accessible"


def test_real_robots_timeout_blocks_content_and_later_recovers(monkeypatch):
    robots_checker.clear_robots_cache()
    requested = []

    def handler(request):
        requested.append((request.method, request.url.path))
        if request.url.path == "/robots.txt":
            if len(requested) == 1:
                raise httpx.ReadTimeout("robots temporarily unavailable", request=request)
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="ok")

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/page")
    assert result.status_lien == "Robots_a_verifier"
    assert requested == [("GET", "/robots.txt")]
    recovered = url_checker.check_url("https://example.test/page")
    assert recovered.status_lien == "Accessible"
    assert requested == [("GET", "/robots.txt"), ("GET", "/robots.txt"), ("HEAD", "/page"), ("GET", "/page")]
    robots_checker.clear_robots_cache()


@pytest.mark.parametrize("url", ["https://example.test:bad/path", "https://bad_host.test/page", "https:///page", "ftp://example.test/file"])
def test_legacy_policy_opt_out_still_rejects_invalid_urls(monkeypatch, url):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid URL must not trigger robots or content requests")

    monkeypatch.setattr(url_checker, "robots_status", unexpected)
    install_transport(monkeypatch, unexpected)
    assert url_checker.check_url(url, url_policy=None).status_lien == "Hors_perimetre"


@pytest.mark.parametrize("content_type", ["application/xml", "text/xml", "application/rss+xml", "application/atom+xml"])
def test_xml_feeds_are_fetched_and_retained_for_discovery(monkeypatch, content_type):
    calls = []
    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: "Oui")
    xml = "<urlset><url><loc>https://example.test/darija</loc></url></urlset>"

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, headers={"content-type": content_type}, text=xml)

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/sitemap.xml")
    assert result.status_lien == "Accessible"
    assert result.html == xml
    assert result.content_type == content_type
    assert calls == ["HEAD", "GET"]


def test_large_sitemap_survives_http_check_and_expansion(monkeypatch, tmp_path):
    from src.expansion.discovery_expander import CandidateUrl, ExpansionDiscoverer
    from src.expansion.duplicate_detector import DuplicateDetector
    from src.expansion.existing_catalog import ExistingCatalog

    monkeypatch.setattr(url_checker, "robots_status", lambda *args, **kwargs: "Oui")
    xml = (
        "<urlset><!--" + "x" * 260000 + "-->"
        "<url><loc>https://example.test/darija</loc></url></urlset>"
    )
    install_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "application/xml"}, text=xml,
    ))
    existing = ExistingCatalog([], set(), set(), set(), set(), set())
    discoverer = ExpansionDiscoverer(existing, DuplicateDetector(existing), tmp_path, {})
    url = "https://example.test/sitemap.xml"

    links = discoverer._expand_url(url, CandidateUrl(url, "test", "existing_domain"))

    assert [link.url for link in links] == ["https://example.test/darija"]


def test_robots_redirect_outside_scope_prevents_any_content_request(monkeypatch):
    requested = []

    def handler(request):
        requested.append((request.method, str(request.url)))
        return httpx.Response(302, headers={"location": "https://github.com/example/rules"})

    install_transport(monkeypatch, handler)
    result = url_checker.check_url("https://example.test/page")
    assert result.status_lien == "Robots_a_verifier"
    assert result.robots_txt == "A_verifier"
    assert requested == [("GET", "https://example.test/robots.txt")]
