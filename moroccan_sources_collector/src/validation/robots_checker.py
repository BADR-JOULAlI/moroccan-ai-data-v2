"""Read robots rules with bounded requests and an expiring policy cache."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx

from src.validation.url_policy import is_regular_website_url, is_valid_web_url


_CACHE_TTL_SECONDS = 3600
_MAX_CACHE_SIZE = 512


@dataclass
class _RobotsPolicy:
    expires_at: float
    urls: tuple[str, ...]
    status: str | None = None
    parser: urllib.robotparser.RobotFileParser | None = None


_CACHE: OrderedDict[tuple[str, str], _RobotsPolicy] = OrderedDict()
_CACHE_LOCK = Lock()


def clear_robots_cache() -> None:
    """Discard cached policies, for example after a configuration change."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _url_allowed(url: str, url_policy: Callable[[str], bool] | None) -> bool:
    return is_valid_web_url(url) and (url_policy is None or url_policy(url))


def _read_policy(
    robots_url: str, user_agent: str, timeout: float,
    url_policy: Callable[[str], bool] | None,
) -> _RobotsPolicy | None:
    requested_urls = []
    current_url = robots_url
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=False, headers={"User-Agent": user_agent}
        ) as client:
            for redirects in range(11):
                if not _url_allowed(current_url, url_policy):
                    return None
                requested_urls.append(current_url)
                response = client.get(current_url)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                if redirects == 10 or not response.headers.get("location"):
                    return None
                current_url = urljoin(current_url, response.headers["location"])
    except (httpx.HTTPError, ValueError):
        return None

    expires_at = monotonic() + _CACHE_TTL_SECONDS
    urls = tuple(requested_urls)
    if response.status_code in {404, 410}:
        return _RobotsPolicy(expires_at, urls, status="Oui")
    if response.status_code in {401, 403}:
        return _RobotsPolicy(expires_at, urls, status="Non")
    if not 200 <= response.status_code < 300:
        return None

    parser = urllib.robotparser.RobotFileParser(robots_url)
    parser.parse(response.text.splitlines())
    return _RobotsPolicy(expires_at, urls, parser=parser)


def robots_status(
    url: str, user_agent: str = "*", timeout: float = 20, *,
    url_policy: Callable[[str], bool] | None = is_regular_website_url,
) -> str:
    """Return Oui/Non for a known policy, A_verifier for a transient failure.

    Only successfully retrieved rules and definite HTTP allow/deny responses are
    cached. A temporary network/server error can be retried immediately.
    """
    if not _url_allowed(url, url_policy):
        return "A_verifier"
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    key = (robots_url, user_agent)
    with _CACHE_LOCK:
        policy = _CACHE.get(key)
        if policy and policy.expires_at <= monotonic():
            del _CACHE[key]
            policy = None
        if policy:
            _CACHE.move_to_end(key)

    if policy is None:
        policy = _read_policy(robots_url, user_agent, timeout, url_policy)
        if policy is None:
            return "A_verifier"
        with _CACHE_LOCK:
            _CACHE[key] = policy
            _CACHE.move_to_end(key)
            while len(_CACHE) > _MAX_CACHE_SIZE:
                _CACHE.popitem(last=False)

    # An audit with a wider policy must never populate a cache that lets a
    # website-only caller bypass validation of robots redirect destinations.
    if not all(_url_allowed(target, url_policy) for target in policy.urls):
        return "A_verifier"

    if policy.status:
        return policy.status
    return "Oui" if policy.parser.can_fetch(user_agent, url) else "Non"
