"""Module de d?couverte de sources et d?extraction de liens candidats."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

from src.discovery.link_extractor import DiscoveredLink, extract_links
from src.discovery.search_adapters import BrowserDiscoveryConfig, PlaywrightDiscoveryAdapter
from src.utils.url_utils import LinkCandidate, get_registered_domain, normalize_url
from src.validation.robots_checker import robots_status
from src.validation.url_checker import check_url
from src.validation.url_policy import EXCLUDED_DISCOVERY_METHODS, is_regular_website_url

LOGGER = logging.getLogger(__name__)


class CatalogCrawler:
    """Discovery orchestrator.

    HTTP and Playwright discovery share the website-only destination policy.
    Historical social extractors remain available separately from this workflow.
    """

    def __init__(self, settings: dict, log_dir: Path):
        """D?crit le fonctionnement de `__init__` et retourne le r?sultat attendu par le module."""
        self.settings = settings
        self.log_dir = log_dir

    def crawl(self, seeds: list[dict], max_links: int | None = None) -> list[LinkCandidate]:
        """Parcourt des sources distantes pour d?couvrir de nouvelles URLs candidates."""
        max_links = max_links or self.settings.get("max_total_links", 500)
        seeds = [seed for seed in seeds if self._is_regular_seed(seed)]
        http_seeds = [seed for seed in seeds if not self._is_playwright_seed(seed)]
        browser_seeds = [seed for seed in seeds if self._is_playwright_seed(seed)]
        results: list[LinkCandidate] = []

        dynamic_first = bool(self.settings.get("playwright_discovery_first", True))
        dynamic_budget = max_links if not http_seeds else int(max_links * float(self.settings.get("playwright_discovery_budget_ratio", 0.7)))
        dynamic_budget = max(0, min(max_links, dynamic_budget))

        if browser_seeds and dynamic_first and dynamic_budget > 0:
            try:
                results.extend(asyncio.run(self.crawl_playwright_async(browser_seeds, dynamic_budget)))
            except RuntimeError as exc:
                LOGGER.error("Playwright discovery skipped: %s", exc)

        remaining = max(max_links - len(results), 0)
        if http_seeds and remaining > 0:
            results.extend(self._crawl_http(http_seeds, max_links=remaining))

        remaining = max(max_links - len(results), 0)
        if browser_seeds and not dynamic_first and remaining > 0:
            try:
                results.extend(asyncio.run(self.crawl_playwright_async(browser_seeds, remaining)))
            except RuntimeError as exc:
                LOGGER.error("Playwright discovery skipped: %s", exc)
        return self._dedupe_candidates(results)[:max_links]

    async def crawl_playwright_async(self, seeds: list[dict], max_links: int | None = None) -> list[LinkCandidate]:
        """Parcourt des sources distantes pour d?couvrir de nouvelles URLs candidates."""
        records = await self.discover_structured_async(seeds, max_links=max_links)
        return [self._record_to_candidate(record) for record in records if is_regular_website_url(record.get("url", ""))]

    async def discover_structured_async(self, seeds: list[dict], max_links: int | None = None) -> list[dict]:
        """D?crit le fonctionnement de `discover_structured_async` et retourne le r?sultat attendu par le module."""
        max_links = max_links or self.settings.get("max_total_links", 500)
        seeds = [seed for seed in seeds if self._is_regular_seed(seed)]
        if not seeds:
            return []
        config = self._browser_config()
        raw_links: list[DiscoveredLink] = []
        domain_counts: Counter[str] = Counter()
        max_links_per_domain = int(self.settings.get("max_links_per_domain", self.settings.get("max_pages_per_domain", 40)))

        async with PlaywrightDiscoveryAdapter(config) as adapter:
            semaphore = asyncio.Semaphore(config.max_concurrent_pages)

            async def run_seed(seed: dict) -> list[DiscoveredLink]:
                """Ex?cute une ?tape compl?te du pipeline et retourne un r?sum? ou des r?sultats."""
                async with semaphore:
                    return await self._run_browser_seed(adapter, seed)

            for batch_start in range(0, len(seeds), config.max_concurrent_pages):
                batch = seeds[batch_start : batch_start + config.max_concurrent_pages]
                for result in await asyncio.gather(*(run_seed(seed) for seed in batch)):
                    for link in result:
                        if not is_regular_website_url(link.url):
                            continue
                        domain = get_registered_domain(link.url)
                        if domain_counts[domain] >= max_links_per_domain:
                            continue
                        domain_counts[domain] += 1
                        raw_links.append(link)
                        if len(raw_links) >= max_links:
                            break
                    if len(raw_links) >= max_links:
                        break
                if len(raw_links) >= max_links:
                    break
        return self._dedupe_records([link.as_dict() for link in raw_links])[:max_links]

    def _crawl_http(self, seeds: list[dict], max_links: int) -> list[LinkCandidate]:
        """D?crit le fonctionnement de `_crawl_http` et retourne le r?sultat attendu par le module."""
        max_depth = self.settings.get("max_depth", 2)
        max_pages_per_domain = self.settings.get("max_pages_per_domain", 20)
        delay = float(self.settings.get("delay_between_requests_seconds", 1.5))
        timeout = float(self.settings.get("request_timeout_seconds", 20))
        user_agent = self.settings.get("user_agent", "MoroccanSourcesCollector/0.1")

        queue: deque[LinkCandidate] = deque()
        for seed in seeds:
            if not self._is_regular_seed(seed):
                continue
            queue.append(
                LinkCandidate(
                    url=normalize_url(seed["url"]),
                    source_name=seed["name"],
                    source_url=seed["url"],
                    source_category=seed.get("category", "Autre"),
                    source_priority=seed.get("priority", "P2"),
                    discovery_method=seed.get("discovery_method", "seed"),
                    depth=0,
                )
            )

        seen: set[str] = set()
        results: list[LinkCandidate] = []
        pages_by_domain: dict[str, int] = defaultdict(int)

        while queue and len(results) < max_links:
            candidate = queue.popleft()
            if not is_regular_website_url(candidate.url):
                continue
            url = normalize_url(candidate.url)
            domain = get_registered_domain(url)
            if url in seen or pages_by_domain[domain] >= max_pages_per_domain:
                continue
            seen.add(url)
            pages_by_domain[domain] += 1

            if robots_status(url, user_agent) != "Oui":
                LOGGER.info("Skipped URL without robots permission: %s", url)
                continue
            if candidate.depth >= max_depth:
                results.append(candidate)
                continue
            check = check_url(url, timeout=timeout, user_agent=user_agent)
            if not is_regular_website_url(check.final_url) or getattr(check, "robots_txt", "A_verifier") != "Oui":
                continue
            results.append(candidate)
            if check.status_lien not in {"Accessible", "Accessible_avec_redirection"} or "html" not in check.content_type:
                continue
            final_domain = get_registered_domain(check.final_url)
            for child_url, anchor_text in extract_links(check.html, check.final_url):
                if len(results) + len(queue) >= max_links * 2:
                    break
                if not is_regular_website_url(child_url):
                    continue
                child_domain = get_registered_domain(child_url)
                relevant = child_domain == final_domain or any(
                    token in (anchor_text + " " + child_url).lower()
                    for token in ["darija", "moroccan", "maroc", "المغرب", "دارجة", "arabic", "dataset", "corpus", "culture"]
                )
                if relevant and child_url not in seen:
                    queue.append(
                        LinkCandidate(
                            url=child_url,
                            source_name=candidate.source_name,
                            source_url=candidate.source_url,
                            source_category=candidate.source_category,
                            source_priority=candidate.source_priority,
                            discovery_method="catalog_link",
                            depth=candidate.depth + 1,
                            anchor_text=anchor_text,
                        )
                    )
            LOGGER.info("Crawled %s (%s links)", url, len(results))
            if delay:
                time.sleep(min(delay, 0.25))
        return results[:max_links]

    async def _run_browser_seed(self, adapter: PlaywrightDiscoveryAdapter, seed: dict) -> list[DiscoveredLink]:
        """D?crit le fonctionnement de `_run_browser_seed` et retourne le r?sultat attendu par le module."""
        method = str(seed.get("discovery_method") or "").lower()
        limit = int(seed.get("max_results") or seed.get("max_pages") or self.settings.get("max_results_per_query", 50))
        query = seed.get("query") or seed.get("name") or ""
        url = seed.get("url") or ""

        if not self._is_regular_seed(seed):
            return []

        if method in {"youtube_search", "youtube_keyword"}:
            return await adapter.youtube_search(query, limit)
        if method in {"youtube_channel", "youtube_videos"}:
            return await adapter.youtube_channel_videos(url, "videos", limit)
        if method == "youtube_shorts":
            return await adapter.youtube_channel_videos(url, "shorts", limit)
        if method in {"facebook_page", "facebook_public_page"}:
            return await adapter.facebook_public_page_posts(url, limit)
        if method in {"google_facebook_dork", "facebook_dork"}:
            return await adapter.google_facebook_dork(query, limit)
        if method in {"google_search", "web_search"}:
            return await adapter.google_search(query, limit)
        if seed.get("use_playwright"):
            return await adapter.rendered_page_links(url, limit)
        return []

    def _browser_config(self) -> BrowserDiscoveryConfig:
        """D?crit le fonctionnement de `_browser_config` et retourne le r?sultat attendu par le module."""
        return BrowserDiscoveryConfig(
            headless=bool(self.settings.get("playwright_headless", True)),
            user_agent=self.settings.get("browser_user_agent", self.settings.get("user_agent", "")) or BrowserDiscoveryConfig().user_agent,
            locale=self.settings.get("browser_locale", "fr-FR"),
            timezone_id=self.settings.get("browser_timezone", "Africa/Casablanca"),
            navigation_timeout_ms=int(self.settings.get("playwright_timeout_ms", 30000)),
            min_delay_seconds=float(self.settings.get("playwright_min_delay_seconds", 0.8)),
            max_delay_seconds=float(self.settings.get("playwright_max_delay_seconds", 2.2)),
            scroll_pause_seconds=float(self.settings.get("playwright_scroll_pause_seconds", 1.2)),
            max_scrolls=int(self.settings.get("playwright_max_scrolls", 18)),
            max_results_per_query=int(self.settings.get("max_results_per_query", 50)),
            max_concurrent_pages=int(self.settings.get("playwright_max_concurrent_pages", 2)),
            enforce_web_policy=True,
        )

    @staticmethod
    def _is_regular_seed(seed: dict) -> bool:
        method = str(seed.get("discovery_method") or "").strip().lower()
        return method not in EXCLUDED_DISCOVERY_METHODS and is_regular_website_url(seed.get("url", ""))

    @staticmethod
    def _is_playwright_seed(seed: dict) -> bool:
        """D?crit le fonctionnement de `_is_playwright_seed` et retourne le r?sultat attendu par le module."""
        method = str(seed.get("discovery_method") or "").lower()
        return bool(seed.get("use_playwright")) or method in {
            "youtube_search",
            "youtube_keyword",
            "youtube_channel",
            "youtube_videos",
            "youtube_shorts",
            "facebook_page",
            "facebook_public_page",
            "google_facebook_dork",
            "facebook_dork",
            "google_search",
            "web_search",
        }

    @staticmethod
    def _record_to_candidate(record: dict) -> LinkCandidate:
        """D?crit le fonctionnement de `_record_to_candidate` et retourne le r?sultat attendu par le module."""
        return LinkCandidate(
            url=normalize_url(record["url"]),
            source_name=record.get("source_origine") or record.get("platform") or "Playwright discovery",
            source_url=record.get("source_origine", ""),
            source_category=record.get("category", "Autre"),
            source_priority=record.get("priority", "P2"),
            discovery_method=record.get("discovery_method", "playwright"),
            depth=0,
            anchor_text=record.get("anchor_text", ""),
        )

    @staticmethod
    def _dedupe_records(records: list[dict]) -> list[dict]:
        """D?crit le fonctionnement de `_dedupe_records` et retourne le r?sultat attendu par le module."""
        seen: set[str] = set()
        unique: list[dict] = []
        for record in records:
            url = normalize_url(record.get("url", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            record["url"] = url
            unique.append(record)
        return unique

    @staticmethod
    def _dedupe_candidates(candidates: list[LinkCandidate]) -> list[LinkCandidate]:
        """D?crit le fonctionnement de `_dedupe_candidates` et retourne le r?sultat attendu par le module."""
        seen: set[str] = set()
        unique: list[LinkCandidate] = []
        for candidate in candidates:
            if not is_regular_website_url(candidate.url):
                continue
            url = normalize_url(candidate.url)
            if url in seen:
                continue
            seen.add(url)
            unique.append(candidate)
        return unique
