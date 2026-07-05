from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from pathlib import Path

from src.discovery.link_extractor import extract_links
from src.utils.url_utils import LinkCandidate, get_registered_domain, normalize_url
from src.validation.robots_checker import robots_status
from src.validation.url_checker import check_url

LOGGER = logging.getLogger(__name__)


class CatalogCrawler:
    def __init__(self, settings: dict, log_dir: Path):
        self.settings = settings
        self.log_dir = log_dir

    def crawl(self, seeds: list[dict], max_links: int | None = None) -> list[LinkCandidate]:
        max_links = max_links or self.settings.get("max_total_links", 500)
        max_depth = self.settings.get("max_depth", 2)
        max_pages_per_domain = self.settings.get("max_pages_per_domain", 20)
        delay = float(self.settings.get("delay_between_requests_seconds", 1.5))
        timeout = float(self.settings.get("request_timeout_seconds", 20))
        user_agent = self.settings.get("user_agent", "MoroccanSourcesCollector/0.1")

        queue: deque[LinkCandidate] = deque()
        for seed in seeds:
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
            url = normalize_url(candidate.url)
            domain = get_registered_domain(url)
            if url in seen or pages_by_domain[domain] >= max_pages_per_domain:
                continue
            seen.add(url)
            pages_by_domain[domain] += 1
            results.append(candidate)

            if candidate.depth >= max_depth or robots_status(url, user_agent) == "Non":
                continue
            check = check_url(url, timeout=timeout, user_agent=user_agent)
            if check.status_lien not in {"Accessible", "Accessible_avec_redirection"} or "html" not in check.content_type:
                continue
            for child_url, anchor_text in extract_links(check.html, check.final_url):
                if len(results) + len(queue) >= max_links * 2:
                    break
                child_domain = get_registered_domain(child_url)
                relevant = child_domain == domain or any(token in (anchor_text + " " + child_url).lower() for token in [
                    "darija", "moroccan", "maroc", "المغرب", "دارجة", "arabic", "dataset", "corpus", "culture"
                ])
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
