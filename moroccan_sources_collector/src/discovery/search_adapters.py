"""Adaptateurs de recherche Playwright pour rendre les pages dynamiques et extraire les liens sociaux."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from src.discovery.facebook_crawler import FacebookCrawler, FacebookCrawlerConfig
from src.discovery.link_extractor import (
    DiscoveredLink,
    extract_facebook_post_links,
    extract_platform_links,
    extract_production_links,
    extract_youtube_links,
    google_search_url,
    youtube_channel_tab_url,
    youtube_search_url,
)
from src.validation.robots_checker import robots_status
from src.validation.url_checker import check_url
from src.validation.url_policy import is_regular_website_url

LOGGER = logging.getLogger(__name__)

DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

LOGIN_OR_CAPTCHA_MARKERS = (
    "captcha",
    "sign in to continue",
    "log in to continue",
    "connectez-vous pour continuer",
    "connexion requise",
    "checkpoint",
    "unusual traffic",
)


@dataclass
class BrowserDiscoveryConfig:
    """Objet de configuration regroupant les param?tres utilis?s par BrowserDiscoveryConfig."""
    headless: bool = True
    user_agent: str = DEFAULT_BROWSER_UA
    locale: str = "fr-FR"
    timezone_id: str = "Africa/Casablanca"
    navigation_timeout_ms: int = 30000
    min_delay_seconds: float = 0.8
    max_delay_seconds: float = 2.2
    scroll_pause_seconds: float = 1.2
    max_scrolls: int = 18
    max_results_per_query: int = 50
    max_concurrent_pages: int = 2
    enforce_web_policy: bool = False


async def human_delay(config: BrowserDiscoveryConfig) -> None:
    """D?crit le fonctionnement de `human_delay` et retourne le r?sultat attendu par le module."""
    await asyncio.sleep(random.uniform(config.min_delay_seconds, config.max_delay_seconds))


class OptionalSearchAdapter:
    """Placeholder for API-backed search. It never blocks the seed-source workflow."""

    def available(self) -> bool:
        """D?crit le fonctionnement de `available` et retourne le r?sultat attendu par le module."""
        return bool(os.getenv("BING_SEARCH_API_KEY") or os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY"))

    def search(self, query: str, limit: int = 10) -> list[str]:
        """Lance une recherche cibl?e et retourne les r?sultats exploitables."""
        return []


class PlaywrightDiscoveryAdapter:
    """Async browser adapter for public dynamic pages.

    The adapter renders public pages and extracts visible public links. It does not
    solve CAPTCHA, log in, or bypass access controls. When a platform blocks public
    access, the call returns an empty result and logs the reason.

    Strict website discovery preflights HTTP redirects and guards each browser
    request. Redirect responses appearing only during rendering are refused;
    the HTTP discovery path can still process stable redirect chains.
    """

    def __init__(self, config: BrowserDiscoveryConfig | None = None):
        """D?crit le fonctionnement de `__init__` et retourne le r?sultat attendu par le module."""
        self.config = config or BrowserDiscoveryConfig()
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "PlaywrightDiscoveryAdapter":
        """D?crit le fonctionnement de `__aenter__` et retourne le r?sultat attendu par le module."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is required. Install it with `pip install playwright` and `playwright install`.") from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.config.headless)
        context_options = {
            "user_agent": self.config.user_agent,
            "locale": self.config.locale,
            "timezone_id": self.config.timezone_id,
            "viewport": {"width": 1366, "height": 900},
            "extra_http_headers": {"Accept-Language": "fr-FR,fr;q=0.9,ar-MA;q=0.8,ar;q=0.7,en;q=0.6"},
        }
        if self.config.enforce_web_policy:
            context_options["service_workers"] = "block"
        self._context = await self._browser.new_context(**context_options)
        self._context.set_default_timeout(self.config.navigation_timeout_ms)
        if self.config.enforce_web_policy:
            await self._context.route("**/*", self._guard_web_request)
        return self

    async def _guard_web_request(self, route) -> None:
        """Authorize the exact request and never delegate an unchecked redirect."""
        url = route.request.url
        if not is_regular_website_url(url):
            LOGGER.info("Blocked browser request outside website scope: %s", url)
            await route.abort()
            return
        response = None
        try:
            permission = await asyncio.to_thread(
                robots_status, url, self.config.user_agent,
                timeout=self.config.navigation_timeout_ms / 1000,
            )
            if permission != "Oui":
                LOGGER.info("Blocked browser request without robots permission: %s", url)
                await route.abort()
                return
            response = await route.fetch(max_redirects=0, timeout=self.config.navigation_timeout_ms)
            if 300 <= response.status < 400 and response.headers.get("location"):
                LOGGER.info("Blocked new browser redirect after HTTP preflight: %s", url)
                await route.abort()
                return
            await route.fulfill(response=response)
        except Exception as exc:
            LOGGER.warning("Browser request blocked after validation/fetch failure for %s: %s", url, exc)
            await route.abort()
        finally:
            if response is not None:
                await response.dispose()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """D?crit le fonctionnement de `__aexit__` et retourne le r?sultat attendu par le module."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def youtube_search(self, query: str, limit: int | None = None) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `youtube_search` et retourne le r?sultat attendu par le module."""
        url = youtube_search_url(query)
        LOGGER.info("Playwright YouTube search: %s", query)
        # Search pages are only discovery surfaces; convert rendered HTML to concrete videos/channels.
        return await self._render_and_extract(
            url,
            lambda html: self._production_links_to_discovered(
                extract_production_links(html, "youtube", limit or self.config.max_results_per_query),
                url,
                "youtube_search_result",
                "YouTube",
            ),
            limit,
        )

    async def google_search(self, query: str, limit: int | None = None) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `google_search` et retourne le r?sultat attendu par le module."""
        url = google_search_url(query)
        LOGGER.info("Playwright Google search: %s", query)
        # Google dorks are also discovery surfaces; keep only the target URLs behind results.
        return await self._render_and_extract(
            url,
            lambda html: self._production_links_to_discovered(
                extract_production_links(html, "google", limit or self.config.max_results_per_query),
                url,
                "google_result_target",
                "",
            ),
            limit,
        )

    async def google_facebook_dork(self, query: str, limit: int | None = None) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `google_facebook_dork` et retourne le r?sultat attendu par le module."""
        dork = f'site:facebook.com "{query}"'
        return await self.google_search(dork, limit)

    async def youtube_channel_videos(self, channel_url: str, tab: str = "videos", limit: int | None = None) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `youtube_channel_videos` et retourne le r?sultat attendu par le module."""
        url = youtube_channel_tab_url(channel_url, tab)
        LOGGER.info("Playwright YouTube channel tab: %s", url)
        return await self._render_and_extract(url, lambda html: extract_youtube_links(html, url, limit or self.config.max_results_per_query), limit)

    async def facebook_public_page_posts(self, page_url: str, limit: int | None = None) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `facebook_public_page_posts` et retourne le r?sultat attendu par le module."""
        if self.config.enforce_web_policy:
            LOGGER.info("Social browser discovery is disabled by the website-only policy")
            return []
        LOGGER.info("Playwright Facebook public page: %s", page_url)
        # Facebook has a dedicated crawler because its login walls and cookie banners are specific.
        fb_config = FacebookCrawlerConfig(
            headless=self.config.headless,
            user_agent=self.config.user_agent,
            locale=self.config.locale,
            timezone_id=self.config.timezone_id,
            navigation_timeout_ms=self.config.navigation_timeout_ms,
            min_delay_seconds=self.config.min_delay_seconds,
            max_delay_seconds=self.config.max_delay_seconds,
            scroll_pause_seconds=self.config.scroll_pause_seconds,
        )
        async with FacebookCrawler(fb_config) as crawler:
            records = await crawler.scrawl_facebook_page(page_url, max_scrolls=self.config.max_scrolls)
        return [
            DiscoveredLink(
                url=record["url"],
                source_origine=record.get("source_origine", page_url),
                discovery_method=record.get("discovery_method", "facebook_public_page_playwright"),
                platform="Facebook",
                status=record.get("status", "DISCOVERED"),
                date_capture=record.get("date_capture", datetime.now(timezone.utc).isoformat()),
            )
            for record in records[: limit or self.config.max_results_per_query]
        ]

    async def rendered_page_links(self, page_url: str, limit: int | None = None) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `rendered_page_links` et retourne le r?sultat attendu par le module."""
        LOGGER.info("Playwright rendered page: %s", page_url)
        return await self._render_and_extract(page_url, None, limit)

    @staticmethod
    def _production_links_to_discovered(urls: list[str], source_url: str, method: str, platform: str) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `_production_links_to_discovered` et retourne le r?sultat attendu par le module."""
        return [
            DiscoveredLink(
                url=url,
                source_origine=source_url,
                discovery_method=method,
                platform=platform or ("Facebook" if "facebook.com" in url else "YouTube" if "youtube.com" in url or "youtu.be" in url else ""),
            )
            for url in urls
        ]

    async def _render_and_extract(
        self,
        url: str,
        extractor: Callable[[str], list[DiscoveredLink]] | None,
        limit: int | None,
    ) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `_render_and_extract` et retourne le r?sultat attendu par le module."""
        if not self._context:
            raise RuntimeError("PlaywrightDiscoveryAdapter must be used as an async context manager.")
        if self.config.enforce_web_policy:
            if not is_regular_website_url(url):
                return []
            try:
                preflight = await asyncio.to_thread(
                    check_url, url, timeout=self.config.navigation_timeout_ms / 1000,
                    user_agent=self.config.user_agent,
                )
            except Exception as exc:
                LOGGER.warning("Browser HTTP preflight failed for %s: %s", url, exc)
                return []
            if (
                not is_regular_website_url(preflight.final_url)
                or preflight.robots_txt != "Oui"
                or preflight.status_lien not in {"Accessible", "Accessible_avec_redirection"}
            ):
                LOGGER.info("Browser navigation refused by HTTP preflight: %s", url)
                return []
            url = preflight.final_url
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
            if self.config.enforce_web_policy and not is_regular_website_url(page.url):
                return []

            def extract_current_page(html: str) -> list[DiscoveredLink]:
                links = (
                    extractor(html) if extractor is not None
                    else extract_platform_links(html, page.url, limit or self.config.max_results_per_query)
                )
                if self.config.enforce_web_policy:
                    links = [link for link in links if is_regular_website_url(link.url)]
                return links

            await human_delay(self.config)
            status = await self._blocked_status(page)
            if status:
                # Do not try to bypass CAPTCHA/login; mark the source as blocked for traceability.
                LOGGER.info("Skipping blocked/login page %s: %s", url, status)
                return [
                    DiscoveredLink(
                        url=page.url,
                        source_origine=page.url,
                        discovery_method="playwright_blocked",
                        platform="",
                        status=status,
                        date_capture=datetime.now(timezone.utc).isoformat(),
                    )
                ]
            await self._scroll_until_stable(page, extract_current_page, limit or self.config.max_results_per_query)
            html = await page.content()
            links = extract_current_page(html)
            return links[: limit or self.config.max_results_per_query]
        except Exception as exc:
            LOGGER.error("Playwright discovery failed for %s: %s", url, exc)
            return []
        finally:
            await page.close()

    async def _scroll_until_stable(self, page, extractor: Callable[[str], list[DiscoveredLink]], limit: int) -> None:
        """D?crit le fonctionnement de `_scroll_until_stable` et retourne le r?sultat attendu par le module."""
        previous_height = 0
        stable_rounds = 0
        for _ in range(self.config.max_scrolls):
            html = await page.content()
            # Stop early once enough concrete links are visible.
            if len(extractor(html)) >= limit:
                break
            height = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(self.config.scroll_pause_seconds + random.uniform(0, 0.8))
            if height <= previous_height:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_height = height
            if stable_rounds >= 3:
                break

    async def _blocked_status(self, page) -> str:
        """D?crit le fonctionnement de `_blocked_status` et retourne le r?sultat attendu par le module."""
        text = (await page.locator("body").inner_text(timeout=5000)).lower()
        if any(marker in text for marker in LOGIN_OR_CAPTCHA_MARKERS):
            if "captcha" in text or "unusual traffic" in text:
                return "CAPTCHA_OU_BLOCAGE"
            return "CONNEXION_REQUISE"
        return ""
