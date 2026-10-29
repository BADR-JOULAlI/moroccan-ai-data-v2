"""Strict browser discovery guards requests without launching Chromium."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.discovery import search_adapters
from src.discovery.search_adapters import BrowserDiscoveryConfig, PlaywrightDiscoveryAdapter
from src.validation.url_checker import UrlCheckResult


def strict_adapter():
    return PlaywrightDiscoveryAdapter(BrowserDiscoveryConfig(
        enforce_web_policy=True, min_delay_seconds=0, max_delay_seconds=0, max_scrolls=0,
    ))


def fake_route(url="https://example.ma/page", status=200, headers=None):
    response = SimpleNamespace(status=status, headers=headers or {}, dispose=AsyncMock())
    route = SimpleNamespace(
        request=SimpleNamespace(url=url),
        fetch=AsyncMock(return_value=response),
        fulfill=AsyncMock(),
        abort=AsyncMock(),
    )
    return route, response


@pytest.mark.asyncio
async def test_excluded_browser_request_is_aborted_before_robots_and_fetch(monkeypatch):
    robots = Mock(side_effect=AssertionError("Do not contact an excluded host"))
    monkeypatch.setattr(search_adapters, "robots_status", robots)
    route, _ = fake_route("https://m.youtube.com:443/watch?v=1")

    await strict_adapter()._guard_web_request(route)

    route.abort.assert_awaited_once()
    route.fetch.assert_not_awaited()
    robots.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", ["Non", "A_verifier", "Inconnue"])
async def test_browser_request_needs_known_robots_permission(monkeypatch, permission):
    monkeypatch.setattr(search_adapters, "robots_status", lambda *args, **kwargs: permission)
    route, _ = fake_route()

    await strict_adapter()._guard_web_request(route)

    route.abort.assert_awaited_once()
    route.fetch.assert_not_awaited()
    route.fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowed_request_fetches_without_automatic_redirects(monkeypatch):
    monkeypatch.setattr(search_adapters, "robots_status", lambda *args, **kwargs: "Oui")
    route, response = fake_route()
    adapter = strict_adapter()

    await adapter._guard_web_request(route)

    route.fetch.assert_awaited_once_with(max_redirects=0, timeout=adapter.config.navigation_timeout_ms)
    route.fulfill.assert_awaited_once_with(response=response)
    route.abort.assert_not_awaited()
    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["https://youtube.com/watch?v=1", "https://example.ma/new-location"])
async def test_render_time_redirect_is_not_fulfilled_or_followed(monkeypatch, location):
    checked = []

    def permission(url, *args, **kwargs):
        checked.append(url)
        return "Oui"

    monkeypatch.setattr(search_adapters, "robots_status", permission)
    route, response = fake_route(status=302, headers={"location": location})

    await strict_adapter()._guard_web_request(route)

    route.fetch.assert_awaited_once()
    assert route.fetch.await_args.kwargs["max_redirects"] == 0
    assert checked == ["https://example.ma/page"]
    route.abort.assert_awaited_once()
    route.fulfill.assert_not_awaited()
    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_failure_does_not_fall_back_to_unchecked_navigation(monkeypatch):
    monkeypatch.setattr(search_adapters, "robots_status", lambda *args, **kwargs: "Oui")
    route, _ = fake_route()
    route.fetch.side_effect = RuntimeError("local fixture failure")

    await strict_adapter()._guard_web_request(route)

    route.abort.assert_awaited_once()
    route.fulfill.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [True, False])
async def test_strict_context_disables_service_workers_and_installs_guard(monkeypatch, strict):
    context = SimpleNamespace(set_default_timeout=Mock(), route=AsyncMock(), close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = SimpleNamespace(
        chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)), stop=AsyncMock(),
    )
    manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: manager)
    adapter = PlaywrightDiscoveryAdapter(BrowserDiscoveryConfig(enforce_web_policy=strict))

    async with adapter:
        options = browser.new_context.await_args.kwargs
        if strict:
            assert options["service_workers"] == "block"
            context.route.assert_awaited_once_with("**/*", adapter._guard_web_request)
        else:
            assert "service_workers" not in options
            context.route.assert_not_awaited()

    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()


def attach_page(adapter, html="", *, page_url=None):
    page = SimpleNamespace(url="about:blank", content=AsyncMock(return_value=html), close=AsyncMock())

    async def goto(url, **kwargs):
        page.url = page_url or url

    page.goto = AsyncMock(side_effect=goto)
    page.locator = lambda *args: SimpleNamespace(inner_text=AsyncMock(return_value="local page text"))
    adapter._context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    return page


def preflight_result(url="https://example.ma/", *, robots="Oui", status="Accessible"):
    return UrlCheckResult(url, 200, status, "text/html", True, robots_txt=robots)


@pytest.mark.asyncio
async def test_browser_preflight_refuses_excluded_seed_without_opening_page(monkeypatch):
    adapter = strict_adapter()
    attach_page(adapter)
    preflight = Mock(side_effect=AssertionError("Excluded seeds must not be requested"))
    monkeypatch.setattr(search_adapters, "check_url", preflight)

    assert await adapter.rendered_page_links("https://github.com/owner/repo") == []

    preflight.assert_not_called()
    adapter._context.new_page.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        preflight_result("https://youtube.com/watch?v=1"),
        preflight_result(robots="Non"),
        preflight_result(robots="A_verifier"),
        preflight_result(status="Timeout"),
    ],
)
async def test_failed_or_refused_preflight_never_navigates(monkeypatch, result):
    adapter = strict_adapter()
    attach_page(adapter)
    monkeypatch.setattr(search_adapters, "check_url", lambda *args, **kwargs: result)

    assert await adapter.rendered_page_links("https://example.ma/") == []
    adapter._context.new_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_relative_browser_links_use_preflight_destination_and_scope(monkeypatch):
    adapter = strict_adapter()
    destination = "https://new.ma/directory/"
    page = attach_page(adapter, '<a href="article">Article</a><a href="https://youtube.com/watch?v=1">Darija</a>')
    monkeypatch.setattr(search_adapters, "check_url", lambda *args, **kwargs: preflight_result(destination))

    links = await adapter.rendered_page_links("https://example.ma/old")

    assert page.goto.await_args.args == (destination,)
    assert [link.url for link in links] == ["https://new.ma/directory/article"]
    assert links[0].source_origine == destination
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_unexpected_excluded_page_url_is_never_extracted(monkeypatch):
    adapter = strict_adapter()
    page = attach_page(adapter, page_url="https://github.com/owner/repo")
    monkeypatch.setattr(search_adapters, "check_url", lambda *args, **kwargs: preflight_result())

    assert await adapter.rendered_page_links("https://example.ma/") == []
    page.content.assert_not_awaited()
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_strict_facebook_method_does_not_start_separate_legacy_browser(monkeypatch):
    monkeypatch.setattr(search_adapters, "FacebookCrawler", Mock(side_effect=AssertionError("No social browser")))

    assert await strict_adapter().facebook_public_page_posts("https://facebook.com/page") == []
