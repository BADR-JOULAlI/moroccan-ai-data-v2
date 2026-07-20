"""Fonctions d?extraction et de nettoyage des liens concrets YouTube, Facebook et Google dorks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, urlencode, unquote, urlparse, urlunparse

from bs4 import BeautifulSoup

from src.utils.url_utils import is_http_url, normalize_url

SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mp3", ".zip", ".rar")

YOUTUBE_VIDEO_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})", re.I)
YOUTUBE_SHORT_RE = re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})", re.I)
FACEBOOK_POST_RE = re.compile(
    r"facebook\.com/(?:[^/\s?#]+/(?:posts|videos|photos|reel)/[^?\s#]+|permalink\.php\?[^\"'\s<>]+)",
    re.I,
)
FACEBOOK_CONTENT_PATTERNS = (
    re.compile(r"^/[^/?#]+/posts/[^/?#]+/?$", re.I),
    re.compile(r"^/[^/?#]+/videos/[^/?#]+/?$", re.I),
    re.compile(r"^/[^/?#]+/photos/[^/?#]+/?$", re.I),
    re.compile(r"^/reel/[^/?#]+/?$", re.I),
    re.compile(r"^/watch/?$", re.I),
    re.compile(r"^/permalink\.php$", re.I),
)
FACEBOOK_BLOCKED_PATH_PREFIXES = (
    "/login",
    "/recover",
    "/checkpoint",
    "/privacy",
    "/help",
    "/policies",
    "/pages",
    "/groups",
    "/share",
    "/shares",
    "/sharer",
    "/profile.php",
    "/events",
    "/marketplace",
    "/friends",
    "/messages",
)
FACEBOOK_KEEP_QUERY_PARAMS = {"id", "story_fbid", "v"}
# Google markup changes often; selectors are tried from specific to broad.
GOOGLE_RESULT_SELECTORS = ("#search a", "div.g a", "a")


@dataclass(frozen=True)
class DiscoveredLink:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de DiscoveredLink."""
    url: str
    source_origine: str
    discovery_method: str
    anchor_text: str = ""
    platform: str = ""
    status: str = "DISCOVERED"
    date_capture: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict:
        """D?crit le fonctionnement de `as_dict` et retourne le r?sultat attendu par le module."""
        return {
            "url": self.url,
            "source_origine": self.source_origine,
            "discovery_method": self.discovery_method,
            "anchor_text": self.anchor_text,
            "platform": self.platform,
            "status": self.status,
            "date_capture": self.date_capture,
        }


def youtube_search_url(query: str) -> str:
    """D?crit le fonctionnement de `youtube_search_url` et retourne le r?sultat attendu par le module."""
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def google_search_url(query: str) -> str:
    """D?crit le fonctionnement de `google_search_url` et retourne le r?sultat attendu par le module."""
    return f"https://www.google.com/search?q={quote_plus(query)}"


def youtube_channel_tab_url(channel_url: str, tab: str = "videos") -> str:
    """D?crit le fonctionnement de `youtube_channel_tab_url` et retourne le r?sultat attendu par le module."""
    normalized = normalize_url(channel_url)
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    if path.endswith(("/videos", "/shorts")):
        return normalized
    return normalize_url(f"{parsed.scheme}://{parsed.netloc}{path}/{tab}")


def _clean_google_redirect(url: str) -> str:
    # Google result links often look like /url?q=<target>. Keep only the target.
    """D?crit le fonctionnement de `_clean_google_redirect` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    if "google." in parsed.netloc and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q") or parse_qs(parsed.query).get("url")
        if target:
            return target[0]
    return url


def _append_unique(results: list[str], seen: set[str], url: str, limit: int | None = None) -> None:
    """D?crit le fonctionnement de `_append_unique` et retourne le r?sultat attendu par le module."""
    if limit and len(results) >= limit:
        return
    if url and url not in seen:
        seen.add(url)
        results.append(url)


def _clean_production_url(url: str) -> str:
    # Production URLs are stored without volatile tracking parameters.
    """D?crit le fonctionnement de `_clean_production_url` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return _canonical_youtube_url(url)
    if "facebook.com" in host:
        return _canonical_facebook_url(url)
    tracking_keys = {"fbclid", "__tn__", "__cft__", "pp", "t", "si", "feature"}
    clean_query = [
        (key, value)
        for key, values in parse_qs(parsed.query, keep_blank_values=False).items()
        if key not in tracking_keys and not key.startswith("__")
        for value in values
    ]
    return normalize_url(urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(clean_query), "")))


def _canonical_youtube_url(url: str) -> str:
    # Normalize all YouTube video forms to a stable watch URL.
    """D?crit le fonctionnement de `_canonical_youtube_url` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        video_id = parsed.path.strip("/").split("/")[0]
        return f"https://www.youtube.com/watch?v={video_id}" if video_id else normalize_url(url)
    if "youtube.com" in host:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            return f"https://www.youtube.com/watch?v={video_id}" if video_id else normalize_url(url)
        if parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
            return f"https://www.youtube.com/shorts/{video_id}" if video_id else normalize_url(url)
        if parsed.path.startswith(("/@", "/channel/", "/c/", "/user/")):
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(parts) >= 2 and parts[-1] in {"videos", "shorts"}:
                return normalize_url(f"https://www.youtube.com/{'/'.join(parts)}")
            if parts:
                return normalize_url(f"https://www.youtube.com/{'/'.join(parts[:2] if parts[0] in {'channel', 'c', 'user'} and len(parts) > 1 else parts[:1])}")
    return normalize_url(url)


def _canonical_facebook_url(url: str) -> str:
    # Facebook posts need a few query params; all Meta tracking params are dropped.
    """D?crit le fonctionnement de `_canonical_facebook_url` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    if "facebook.com" not in parsed.netloc.lower():
        return normalize_url(url)
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query, keep_blank_values=False)
    clean_query: dict[str, str] = {}
    for key in sorted(FACEBOOK_KEEP_QUERY_PARAMS):
        if query.get(key):
            clean_query[key] = query[key][0]
    query_string = urlencode(clean_query)
    return normalize_url(urlunparse(("https", "facebook.com", path, "", query_string, "")))


def _is_facebook_content_url(url: str) -> bool:
    # Keep only real content pages. Navigation/login/groups pollute the catalogue.
    """D?crit le fonctionnement de `_is_facebook_content_url` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "facebook.com" not in host:
        return False
    path = parsed.path.lower()
    if any(path.startswith(prefix) for prefix in FACEBOOK_BLOCKED_PATH_PREFIXES):
        return False
    if path.rstrip("/") == "/watch":
        return bool(parse_qs(parsed.query).get("v"))
    if path == "/permalink.php":
        query = parse_qs(parsed.query)
        return bool(query.get("story_fbid") or query.get("id"))
    return any(pattern.match(parsed.path.rstrip("/") or "/") for pattern in FACEBOOK_CONTENT_PATTERNS)


def _is_youtube_production_url(url: str) -> bool:
    # A YouTube production URL is either a concrete video or a creator/channel page.
    """D?crit le fonctionnement de `_is_youtube_production_url` et retourne le r?sultat attendu par le module."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    if "youtu.be" in host:
        return bool(path.strip("/"))
    if "youtube.com" not in host:
        return False
    if path == "/watch":
        return bool(parse_qs(parsed.query).get("v"))
    return path.startswith("/@")


def extract_google_result_targets(html_content: str, limit: int | None = None) -> list[str]:
    """Extract final targets from rendered Google results, never Google search URLs."""
    soup = BeautifulSoup(html_content or "", "lxml")
    seen: set[str] = set()
    results: list[str] = []
    anchors = []
    for selector in GOOGLE_RESULT_SELECTORS:
        anchors.extend(soup.select(selector))
    for anchor in anchors:
        href = anchor.get("href", "")
        if not href:
            continue
        google_or_target = normalize_url(unquote(href), base_url="https://www.google.com")
        target = normalize_url(_clean_google_redirect(google_or_target))
        host = urlparse(target).netloc.lower()
        # Never keep Google itself; only the concrete target behind the result.
        if "google." in host:
            continue
        if "facebook.com" in host:
            if _is_facebook_content_url(target):
                _append_unique(results, seen, _clean_production_url(target), limit)
        elif "youtube.com" in host or "youtu.be" in host:
            if _is_youtube_production_url(target):
                _append_unique(results, seen, _clean_production_url(target), limit)
        if limit and len(results) >= limit:
            break
    return results


def extract_production_links(html_content: str, platform: str, limit: int | None = None) -> list[str]:
    """Return unique concrete URLs ready for catalogue insertion.

    Search-result pages themselves are intentionally never returned. The function
    keeps only YouTube videos/channels and concrete Facebook content discovered in
    rendered Google/Facebook HTML.
    """
    normalized_platform = (platform or "").strip().lower()
    soup = BeautifulSoup(html_content or "", "lxml")
    seen: set[str] = set()
    results: list[str] = []

    if normalized_platform in {"youtube", "yt"}:
        for anchor in soup.find_all("a", href=True):
            raw = unquote(anchor.get("href", ""))
            target = normalize_url(raw, base_url="https://www.youtube.com")
            # This explicitly rejects /results?search_query=... and feed/navigation links.
            if _is_youtube_production_url(target):
                _append_unique(results, seen, _clean_production_url(target), limit)
            if limit and len(results) >= limit:
                break
        return results

    if normalized_platform in {"google", "google_facebook", "google_dork", "facebook_dork"}:
        # Google dorks are discovery pages; only their Facebook/YouTube targets matter.
        return extract_google_result_targets(html_content, limit)

    if normalized_platform == "facebook":
        return extract_facebook_links(html_content, limit=limit)

    for anchor in soup.find_all("a", href=True):
        target = normalize_url(unquote(anchor.get("href", "")))
        if _is_youtube_production_url(target) or _is_facebook_content_url(target):
            _append_unique(results, seen, _clean_production_url(target), limit)
        if limit and len(results) >= limit:
            break
    return results


def extract_facebook_links(html_content: str, source_url: str = "https://www.facebook.com", limit: int | None = None) -> list[str]:
    """Extract concrete public Facebook content URLs from rendered HTML.

    The extractor keeps only posts, videos, reels, photos and permalinks. Generic
    navigation URLs such as login, groups, shares and pages are systematically
    ignored. Tracking parameters such as ``__cft__``, ``__tn__`` and ``fbclid``
    are dropped during canonicalization.
    """
    soup = BeautifulSoup(html_content or "", "lxml")
    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = unquote(anchor.get("href", ""))
        candidates.append(normalize_url(href, base_url=source_url))
    # Some rendered Facebook HTML includes raw URLs outside href attributes.
    candidates.extend(f"https://www.{match.group(0)}" for match in FACEBOOK_POST_RE.finditer(html_content or ""))

    seen: set[str] = set()
    results: list[str] = []
    for candidate in candidates:
        if not _is_facebook_content_url(candidate):
            continue
        canonical = _canonical_facebook_url(candidate)
        if canonical in seen:
            continue
        seen.add(canonical)
        results.append(canonical)
        if limit and len(results) >= limit:
            break
    return results


def extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extrait les informations utiles depuis le contenu fourni et filtre le bruit."""
    soup = BeautifulSoup(html or "", "lxml")
    links: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = _clean_google_redirect(anchor.get("href", ""))
        url = normalize_url(href, base_url=base_url)
        if not is_http_url(url) or url.lower().endswith(SKIP_EXTENSIONS):
            continue
        text = anchor.get_text(" ", strip=True)[:200]
        links.append((url, text))
    return links


def extract_youtube_links(html: str, source_url: str, limit: int = 50) -> list[DiscoveredLink]:
    """Extrait les informations utiles depuis le contenu fourni et filtre le bruit."""
    soup = BeautifulSoup(html or "", "lxml")
    seen: set[str] = set()
    results: list[DiscoveredLink] = []
    for anchor in soup.find_all("a", href=True):
        href = unquote(anchor.get("href", ""))
        url = normalize_url(href, base_url="https://www.youtube.com")
        if "youtube.com" not in url and "youtu.be" not in url:
            continue
        parsed = urlparse(url)
        is_video = (parsed.path == "/watch" and bool(parse_qs(parsed.query).get("v"))) or "youtu.be" in parsed.netloc.lower()
        is_short = parsed.path.startswith("/shorts/")
        is_channel = parsed.path.startswith(("/@", "/channel/", "/c/", "/user/"))
        if not (is_video or is_short or is_channel):
            continue
        canonical = _canonical_youtube_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        method = "youtube_video" if is_video else "youtube_short" if is_short else "youtube_channel"
        results.append(
            DiscoveredLink(
                url=canonical,
                source_origine=source_url,
                discovery_method=method,
                anchor_text=anchor.get_text(" ", strip=True)[:200],
                platform="YouTube",
            )
        )
        if len(results) >= limit:
            break
    return results


def extract_facebook_post_links(html: str, source_url: str, limit: int = 50) -> list[DiscoveredLink]:
    """Extrait les informations utiles depuis le contenu fourni et filtre le bruit."""
    results: list[DiscoveredLink] = []
    for canonical in extract_facebook_links(html, source_url, limit):
        results.append(
            DiscoveredLink(
                url=canonical,
                source_origine=source_url,
                discovery_method="facebook_public_post",
                platform="Facebook",
            )
        )
        if len(results) >= limit:
            break
    return results


def extract_platform_links(html: str, source_url: str, limit: int = 50) -> list[DiscoveredLink]:
    """Extrait les informations utiles depuis le contenu fourni et filtre le bruit."""
    host = urlparse(source_url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return extract_youtube_links(html, source_url, limit)
    if "facebook.com" in host:
        return extract_facebook_post_links(html, source_url, limit)
    return [
        DiscoveredLink(url=url, source_origine=source_url, discovery_method="rendered_link", anchor_text=text)
        for url, text in extract_links(html, source_url)[:limit]
    ]
