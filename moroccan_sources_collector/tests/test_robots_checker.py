"""Robots decisions, retries and cache expiration without network access."""

import httpx
import pytest

from src.validation import robots_checker


REAL_CLIENT = httpx.Client


@pytest.fixture(autouse=True)
def clean_cache():
    robots_checker.clear_robots_cache()
    yield
    robots_checker.clear_robots_cache()


def install_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: REAL_CLIENT(transport=transport, **kwargs))


@pytest.mark.parametrize("code,expected", [(404, "Oui"), (410, "Oui"), (401, "Non"), (403, "Non"), (429, "A_verifier"), (500, "A_verifier")])
def test_robots_http_statuses(monkeypatch, code, expected):
    install_transport(monkeypatch, lambda request: httpx.Response(code))
    assert robots_checker.robots_status("https://example.test/private") == expected


def test_rules_apply_per_path_and_user_agent(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

    install_transport(monkeypatch, handler)
    assert robots_checker.robots_status("https://example.test/private") == "Non"
    assert robots_checker.robots_status("https://example.test/public") == "Oui"
    assert calls == ["https://example.test/robots.txt"]


def test_timeout_is_explicit_and_temporary_error_is_not_cached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] == 0.5
        if len(calls) == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")

    install_transport(monkeypatch, handler)
    url = "https://example.test/page"
    assert robots_checker.robots_status(url, timeout=0.5) == "A_verifier"
    assert robots_checker.robots_status(url, timeout=0.5) == "Oui"
    assert len(calls) == 2


def test_server_error_is_retried_immediately(monkeypatch):
    replies = iter([503, 404])
    install_transport(monkeypatch, lambda request: httpx.Response(next(replies)))
    assert robots_checker.robots_status("https://example.test/page") == "A_verifier"
    assert robots_checker.robots_status("https://example.test/page") == "Oui"


def test_cached_policy_expires(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(robots_checker, "monotonic", lambda: clock[0])
    monkeypatch.setattr(robots_checker, "_CACHE_TTL_SECONDS", 10)

    def handler(request):
        calls.append(request)
        return httpx.Response(403 if len(calls) == 1 else 404)

    install_transport(monkeypatch, handler)
    url = "https://example.test/page"
    assert robots_checker.robots_status(url) == "Non"
    clock[0] = 9
    assert robots_checker.robots_status(url) == "Non"
    clock[0] = 10
    assert robots_checker.robots_status(url) == "Oui"
    assert len(calls) == 2


def test_cache_size_is_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr(robots_checker, "_MAX_CACHE_SIZE", 2)

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    install_transport(monkeypatch, handler)
    for host in ["one.test", "two.test", "three.test", "one.test"]:
        assert robots_checker.robots_status(f"https://{host}/page") == "Oui"
    assert len(robots_checker._CACHE) == 2
    assert len(calls) == 4


def test_invalid_url_does_not_request_robots(monkeypatch):
    def unexpected_request(request):
        pytest.fail(f"Unexpected request: {request.url}")

    install_transport(monkeypatch, unexpected_request)
    assert robots_checker.robots_status("https:///") == "A_verifier"


@pytest.mark.parametrize("target", ["https://github.com/example/rules", "https://example.test:bad/rules", "ftp://example.test/rules"])
def test_robots_redirect_destination_is_validated_before_fetch(monkeypatch, target):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": target})

    install_transport(monkeypatch, handler)
    assert robots_checker.robots_status("https://example.test/page") == "A_verifier"
    assert calls == ["https://example.test/robots.txt"]


def test_robots_redirect_chain_accepts_allowed_destinations(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(302, headers={"location": "/rules"})
        if request.url.path == "/rules":
            return httpx.Response(307, headers={"location": "https://rules.example.test/policy.txt"})
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

    install_transport(monkeypatch, handler)
    assert robots_checker.robots_status("https://example.test/private") == "Non"
    assert robots_checker.robots_status("https://example.test/public") == "Oui"
    assert calls == ["https://example.test/robots.txt", "https://example.test/rules", "https://rules.example.test/policy.txt"]


def test_robots_redirect_limit_stops_loop(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "/again"})

    install_transport(monkeypatch, handler)
    assert robots_checker.robots_status("https://example.test/page") == "A_verifier"
    assert len(calls) == 11


def test_permissive_audit_cache_cannot_bypass_stricter_redirect_policy(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "example.test":
            return httpx.Response(302, headers={"location": "https://github.com/example/rules"})
        return httpx.Response(404)

    install_transport(monkeypatch, handler)
    url = "https://example.test/page"
    assert robots_checker.robots_status(url, url_policy=None) == "Oui"
    assert robots_checker.robots_status(url) == "A_verifier"
    assert calls == ["https://example.test/robots.txt", "https://github.com/example/rules"]


def test_legacy_platform_requires_explicit_robots_policy_opt_out(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    install_transport(monkeypatch, handler)
    url = "https://github.com/example/corpus"
    assert robots_checker.robots_status(url) == "A_verifier"
    assert calls == []
    assert robots_checker.robots_status(url, url_policy=None) == "Oui"
    assert calls == ["https://github.com/robots.txt"]
