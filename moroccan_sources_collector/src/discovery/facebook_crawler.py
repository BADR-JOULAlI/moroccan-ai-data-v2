"""Crawler Playwright sp?cialis? dans les pages Facebook publiques."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from src.discovery.link_extractor import extract_facebook_links

logger = logging.getLogger(__name__)

DEFAULT_FACEBOOK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

LOGIN_REQUIRED_MARKERS = (
    "log in to facebook",
    "sign in to facebook",
    "connectez-vous à facebook",
    "connectez-vous pour continuer",
    "vous devez vous connecter",
    "login",
    "checkpoint",
)
BLOCKED_MARKERS = (
    "captcha",
    "unusual traffic",
    "temporarily blocked",
    "access denied",
    "content isn't available",
    "ce contenu n'est pas disponible",
)
COOKIE_BUTTON_TEXTS = (
    "Allow all cookies",
    "Allow essential and optional cookies",
    "Autoriser tous les cookies",
    "Autoriser les cookies essentiels et optionnels",
    "Accepter tous les cookies",
    "Accepter",
)


@dataclass
class FacebookCrawlerConfig:
    """Classe responsable du crawl ou de la d?couverte de sources pour FacebookCrawlerConfig."""
    headless: bool = True
    user_agent: str = DEFAULT_FACEBOOK_UA
    locale: str = "fr-FR"
    timezone_id: str = "Africa/Casablanca"
    navigation_timeout_ms: int = 45000
    min_delay_seconds: float = 0.5
    max_delay_seconds: float = 2.0
    scroll_pause_seconds: float = 1.4
    viewport_width: int = 1366
    viewport_height: int = 900


class FacebookCrawler:
    """Playwright-based crawler for public Facebook pages and groups.

    The crawler only reads public rendered content. It does not log in, solve
    CAPTCHA, or bypass Meta protections. If Facebook requires authentication or
    blocks the page, the crawler logs a warning and returns an empty list.
    """

    def __init__(self, config: FacebookCrawlerConfig | None = None):
        """D?crit le fonctionnement de `__init__` et retourne le r?sultat attendu par le module."""
        self.config = config or FacebookCrawlerConfig()
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "FacebookCrawler":
        """D?crit le fonctionnement de `__aenter__` et retourne le r?sultat attendu par le module."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is required. Install it with `pip install playwright` and `playwright install`.") from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.config.headless)
        self._context = await self._browser.new_context(
            user_agent=self.config.user_agent,
            locale=self.config.locale,
            timezone_id=self.config.timezone_id,
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,ar-MA;q=0.8,ar;q=0.7,en;q=0.6"},
        )
        self._context.set_default_timeout(self.config.navigation_timeout_ms)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """D?crit le fonctionnement de `__aexit__` et retourne le r?sultat attendu par le module."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def scrawl_facebook_page(self, page_url: str, max_scrolls: int = 20) -> list[dict]:
        """Open a public Facebook page/group and extract concrete post URLs.

        The method name intentionally follows the requested public API. Use
        ``crawl_facebook_page`` as an alias if you prefer the standard spelling.
        """
        if not self._context:
            raise RuntimeError("FacebookCrawler must be used as an async context manager.")

        page = await self._context.new_page()
        try:
            logger.info("Opening Facebook source with Playwright: %s", page_url)
            await page.goto(page_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
            await self._human_delay()
            await self._accept_cookie_banner(page)

            blocked_status = await self._blocked_status(page)
            if blocked_status:
                logger.warning("Page Facebook nécessite une connexion obligatoire, saut de la source")
                logger.info("Facebook source skipped: %s (%s)", page_url, blocked_status)
                return []

            seen: set[str] = set()
            extracted: list[str] = []
            stable_rounds = 0
            previous_height = 0

            for _ in range(max_scrolls):
                # Extract before each scroll because Facebook loads posts incrementally.
                html = await page.content()
                for url in extract_facebook_links(html, page_url):
                    if url not in seen:
                        seen.add(url)
                        extracted.append(url)

                # Scroll to trigger older public posts; stop when height stops growing.
                current_height = await page.evaluate("document.body.scrollHeight")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self._human_delay(extra=self.config.scroll_pause_seconds)

                # Facebook can show a login wall after a few scrolls; do not bypass it.
                blocked_status = await self._blocked_status(page)
                if blocked_status:
                    logger.warning("Page Facebook nécessite une connexion obligatoire, saut de la source")
                    break

                if current_height <= previous_height:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                previous_height = current_height
                if stable_rounds >= 3:
                    break

            date_capture = datetime.now(timezone.utc).date().isoformat()
            return [
                {
                    "url": url,
                    "source_origine": page_url,
                    "date_capture": date_capture,
                    "platform": "Facebook",
                    "discovery_method": "facebook_public_page_playwright",
                    "status": "DISCOVERED",
                }
                for url in extracted
            ]
        except Exception as exc:
            logger.warning("Page Facebook nécessite une connexion obligatoire, saut de la source")
            logger.error("Facebook crawler failed for %s: %s", page_url, exc)
            return []
        finally:
            await page.close()

    async def crawl_facebook_page(self, page_url: str, max_scrolls: int = 20) -> list[dict]:
        """Parcourt des sources distantes pour d?couvrir de nouvelles URLs candidates."""
        return await self.scrawl_facebook_page(page_url, max_scrolls=max_scrolls)

    async def _human_delay(self, extra: float = 0.0) -> None:
        # Small random pauses make the browser flow less bursty and reduce accidental rate limits.
        """D?crit le fonctionnement de `_human_delay` et retourne le r?sultat attendu par le module."""
        await asyncio.sleep(extra + random.uniform(self.config.min_delay_seconds, self.config.max_delay_seconds))

    async def _accept_cookie_banner(self, page) -> None:
        # Cookie banners vary by locale, so multiple likely labels are attempted.
        """D?crit le fonctionnement de `_accept_cookie_banner` et retourne le r?sultat attendu par le module."""
        for text in COOKIE_BUTTON_TEXTS:
            try:
                button = page.get_by_role("button", name=text)
                if await button.count():
                    await button.first.click(timeout=2500)
                    logger.info("Accepted Facebook cookie banner")
                    await self._human_delay()
                    return
            except Exception:
                continue

    async def _blocked_status(self, page) -> str:
        """D?crit le fonctionnement de `_blocked_status` et retourne le r?sultat attendu par le module."""
        try:
            body_text = (await page.locator("body").inner_text(timeout=5000)).lower()
        except Exception:
            return ""
        # The crawler is intentionally conservative: blocked/private pages are skipped.
        if any(marker in body_text for marker in BLOCKED_MARKERS):
            return "BLOQUEE"
        if any(marker in body_text for marker in LOGIN_REQUIRED_MARKERS):
            return "CONNEXION_REQUISE"
        return ""
