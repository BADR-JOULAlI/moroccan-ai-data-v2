"""Module historique d?expansion du catalogue ? partir de sources existantes."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import httpx
import yaml

from src.discovery.link_extractor import extract_links
from src.expansion.duplicate_detector import DuplicateDetector
from src.expansion.existing_catalog import ExistingCatalog
from src.utils.url_utils import get_domain, get_registered_domain, normalize_url
from src.validation.robots_checker import robots_status

LOGGER = logging.getLogger(__name__)

COMMON_PATHS = [
    "/sitemap.xml", "/sitemap_index.xml", "/sitemap-news.xml", "/post-sitemap.xml",
    "/page-sitemap.xml", "/category-sitemap.xml", "/feed", "/rss", "/archives",
    "/archive", "/category", "/tag", "/search",
]
FAST_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-news.xml", "/post-sitemap.xml", "/page-sitemap.xml", "/feed", "/rss"]

TECHNICAL_DOMAINS = [
    "https://huggingface.co/datasets?search={q}",
    "https://github.com/search?q={q}&type=repositories",
    "https://zenodo.org/search?q={q}",
    "https://dataverse.harvard.edu/dataverse/root?q={q}",
    "https://figshare.com/search?q={q}",
    "https://arxiv.org/search/?query={q}&searchtype=all",
    "https://aclanthology.org/search/?q={q}",
    "https://archive.org/search?query={q}",
    "https://search.openedition.org/results?q={q}",
    "https://commons.wikimedia.org/w/index.php?search={q}",
    "https://www.wikidata.org/w/index.php?search={q}",
    "https://wikisource.org/w/index.php?search={q}",
    "https://www.youtube.com/results?search_query={q}",
    "https://www.youtube.com/hashtag/{q}",
    "https://www.facebook.com/search/posts/?q={q}",
    "https://www.facebook.com/hashtag/{q}",
]

CURATED_BASES = [
    "https://www.maroc.ma/ar", "https://www.maroc.ma/fr", "https://www.minculture.gov.ma/",
    "https://www.habous.gov.ma/", "https://www.mapnews.ma/ar", "https://www.2m.ma/ar",
    "https://snrtnews.com/ar", "https://www.hespress.com/", "https://alyaoum24.com/",
    "https://www.al3omk.com/", "https://www.maghress.com/", "https://www.menara.ma/ar",
    "https://www.yabiladi.ma/", "https://www.libe.ma/", "https://www.maghrebvoices.com/morocco",
    "https://www.visitmorocco.com/ar", "https://ich.unesco.org/en/state/morocco-MA",
    "https://www.imarabe.org/fr/ressources", "https://www.persee.fr/search?q=Maroc+darija",
    "https://hal.science/search/index/q/moroccan+arabic", "https://www.theses.fr/?q=darija",
    "https://www.moroccanarabic.com/", "https://tajinequiparle.com/", "https://talkinarabic.com/moroccan-arabic/",
    "https://www.loecsen.com/en/learn-arabic-moroccan", "https://www.17-minute-languages.com/en/moroccan-arabic/",
    "https://www.youtube.com/@2MMaroc",
    "https://www.youtube.com/@Medi1TVAfrique",
    "https://www.youtube.com/@SNRTnews",
    "https://www.youtube.com/@hespress",
    "https://www.facebook.com/2M.ma",
    "https://www.facebook.com/SNRTNews",
    "https://www.facebook.com/Hespress",
    "https://www.facebook.com/Maroc.ma",
]

@dataclass
class CandidateUrl:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de CandidateUrl."""
    url: str
    source: str
    method: str
    query: str = ""
    depth: int = 0


def load_keywords(config_dir: Path, category: str | None = None) -> list[str]:
    """Charge des donn?es ou une configuration depuis le disque et retourne une structure exploitable."""
    data = yaml.safe_load((config_dir / "keywords.yaml").read_text(encoding="utf-8")) or {}
    keywords = list(data.get("arabic", [])) + list(data.get("darija_latin_arabizi", []))
    extra = [
        "darija marocaine", "darija dictionary", "darija dialogue", "darija subtitles",
        "darija speech corpus", "darija parallel corpus", "moroccan arabic NLP",
        "dictionnaire francais darija", "lexique francais darija", "apprendre la darija",
        "phrases utiles en darija", "proverbes marocains traduction", "moroccan proverbs",
        "moroccan folklore", "moroccan culture arabic", "الدارجة المغربية", "قاموس الدارجة",
        "حوار بالدارجة", "الأمثال الشعبية المغربية", "التراث المغربي", "المطبخ المغربي",
        "darija youtube", "darija podcast", "darija interview", "moroccan arabic subtitles",
        "moroccan arabic conversation youtube", "moroccan darija facebook", "darija facebook",
        "حوار مغربي يوتيوب", "بودكاست مغربي بالدارجة", "فيديو بالدارجة المغربية",
        "تعلم الدارجة يوتيوب", "أمثال مغربية بالدارجة",
    ]
    keywords.extend(extra)
    if category == "parallel":
        keywords = [k for k in keywords if any(t in k.lower() for t in ["darija", "franc", "translation", "dictionary", "lexique", "phrases"])]
    elif category == "culture":
        keywords = [k for k in keywords if any(t in k.lower() for t in ["culture", "maroc", "moroccan", "تراث", "ثقافة", "مغربي"])]
    elif category == "darija":
        keywords = [k for k in keywords if "darija" in k.lower() or "دارجة" in k]
    return list(dict.fromkeys(keywords))[:80]


class ExpansionDiscoverer:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de ExpansionDiscoverer."""
    def __init__(self, existing: ExistingCatalog, duplicate_detector: DuplicateDetector, config_dir: Path, settings: dict):
        """D?crit le fonctionnement de `__init__` et retourne le r?sultat attendu par le module."""
        self.existing = existing
        self.duplicates = duplicate_detector
        self.config_dir = config_dir
        self.settings = settings
        self.timeout = min(float(settings.get("request_timeout_seconds", 20)), 8.0)
        self.user_agent = settings.get("user_agent", "MoroccanSourcesCollector/0.1")

    def discover(self, target: int, max_links_per_domain: int, category: str | None = None) -> tuple[list[CandidateUrl], list[dict]]:
        """D?crit le fonctionnement de `discover` et retourne le r?sultat attendu par le module."""
        candidates: list[CandidateUrl] = []
        rejected: list[dict] = []
        per_domain: Counter[str] = Counter()
        queue: deque[CandidateUrl] = deque(self._initial_candidates(category))
        seen: set[str] = set()
        max_requests = int(self.settings.get("max_total_requests", 10000))
        requests = 0

        while queue and len(candidates) < target and requests < max_requests:
            item = queue.popleft()
            url = normalize_url(item.url)
            if url in seen:
                continue
            seen.add(url)
            decision = self.duplicates.check_url(url)
            if decision.is_duplicate:
                rejected.append(self._rejected(url, decision, item))
                continue
            domain = get_registered_domain(url)
            if per_domain[domain] >= max_links_per_domain:
                continue
            candidates.append(CandidateUrl(url, item.source, item.method, item.query, item.depth))
            per_domain[domain] += 1
            if item.depth >= int(self.settings.get("max_depth", 3)) or item.method in {"platform_search", "domain_common_path", "curated_common_path"}:
                continue
            requests += 1
            for child in self._expand_url(url, item):
                child_url = normalize_url(child.url)
                if child_url not in seen and len(candidates) + len(queue) < target * 4:
                    queue.append(child)
            if requests % 25 == 0:
                LOGGER.info("Expansion discovery: %s candidates, %s duplicates", len(candidates), len(rejected))
            time.sleep(0.03)
        return candidates[:target], rejected

    def _initial_candidates(self, category: str | None) -> list[CandidateUrl]:
        """D?crit le fonctionnement de `_initial_candidates` et retourne le r?sultat attendu par le module."""
        items: list[CandidateUrl] = []
        for query in load_keywords(self.config_dir, category):
            encoded = quote_plus(query)
            for pattern in TECHNICAL_DOMAINS:
                url = pattern.format(q=encoded)
                items.append(CandidateUrl(url, get_domain(url), "platform_search", query))
        for base in CURATED_BASES:
            items.append(CandidateUrl(base, get_domain(base), "curated_domain"))
            parsed = urlparse(base)
            root = f"{parsed.scheme}://{parsed.netloc}"
            for path in FAST_PATHS:
                items.append(CandidateUrl(root + path, get_domain(base), "curated_common_path"))
        for domain in sorted(self.existing.domains):
            if not domain:
                continue
            base = f"https://{domain}"
            items.append(CandidateUrl(base, domain, "existing_domain"))
            for path in FAST_PATHS:
                items.append(CandidateUrl(base + path, domain, "domain_common_path"))
        return items

    def _expand_url(self, url: str, parent: CandidateUrl) -> list[CandidateUrl]:
        """D?crit le fonctionnement de `_expand_url` et retourne le r?sultat attendu par le module."""
        try:
            with httpx.Client(follow_redirects=True, timeout=self.timeout, headers={"User-Agent": self.user_agent}) as client:
                response = client.get(url)
        except Exception:
            return []
        content_type = response.headers.get("content-type", "").lower()
        body = response.text[:500000]
        final_url = str(response.url)
        if "xml" in content_type or body.lstrip().startswith("<?xml") or "<urlset" in body or "<sitemapindex" in body:
            return self._parse_xml_links(body, final_url, parent)
        if "rss" in content_type or "atom" in content_type or "<rss" in body[:200].lower() or "<feed" in body[:200].lower():
            return self._parse_xml_links(body, final_url, parent)
        if "html" in content_type:
            children = []
            for link, anchor in extract_links(body, final_url):
                if self._is_relevant(link, anchor):
                    children.append(CandidateUrl(link, parent.source, "page_link", parent.query, parent.depth + 1))
            return children[:100]
        return []

    def _parse_xml_links(self, body: str, final_url: str, parent: CandidateUrl) -> list[CandidateUrl]:
        """D?crit le fonctionnement de `_parse_xml_links` et retourne le r?sultat attendu par le module."""
        try:
            root = ET.fromstring(body.encode("utf-8"))
        except ET.ParseError:
            return []
        links = []
        for elem in root.iter():
            if elem.tag.lower().endswith("loc") and elem.text:
                method = "sitemap" if "sitemap" in final_url else "rss"
                links.append(CandidateUrl(elem.text.strip(), parent.source, method, parent.query, parent.depth + 1))
            elif elem.tag.lower().endswith("link") and elem.text and elem.text.strip().startswith("http"):
                links.append(CandidateUrl(elem.text.strip(), parent.source, "rss", parent.query, parent.depth + 1))
        return links[:200]

    def _is_relevant(self, url: str, anchor: str) -> bool:
        """D?crit le fonctionnement de `_is_relevant` et retourne le r?sultat attendu par le module."""
        haystack = f"{url} {anchor}".lower()
        skip = [
            "login", "signin", "cart", "checkout", "privacy", "terms", "facebook.com/sharer",
            "mailto:", "amazon.", "amzn.to", "doubleclick", "ads", "utm_", "share="
        ]
        if any(token in haystack for token in skip):
            return False
        keep = [
            "darija", "moroccan", "maroc", "morocco", "arabic", "dataset", "corpus", "culture",
            "patrimoine", "archive", "dictionary", "lexique", "proverb", "tradition", "المغرب",
            "مغربي", "دارجة", "تراث", "ثقافة", "حكايات", "أمثال",
        ]
        return any(token in haystack for token in keep)

    def _rejected(self, url: str, decision, item: CandidateUrl) -> dict:
        """D?crit le fonctionnement de `_rejected` et retourne le r?sultat attendu par le module."""
        return {
            "URL_candidate": url,
            "URL_existante_correspondante": decision.duplicate_of,
            "type_doublon": decision.duplicate_type,
            "raison": decision.reason,
            "score_similarite": decision.similarity,
            "source": item.source,
            "methode": item.method,
        }
