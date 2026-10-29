"""Shared URL syntax and website-only collection policy."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit


EXCLUDED_WEB_PLATFORMS = {
    "facebook.com",
    "fb.com",
    "fb.watch",
    "github.com",
    "huggingface.co",
    "kaggle.com",
    "youtu.be",
    "youtube.com",
}

EXCLUDED_DISCOVERY_METHODS = {
    "facebook_dork",
    "facebook_page",
    "facebook_public_page",
    "google_facebook_dork",
    "youtube_channel",
    "youtube_keyword",
    "youtube_search",
    "youtube_shorts",
    "youtube_videos",
}

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)


def _validated_host(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    value = url.strip()
    if not value or "\\" in value or any(
        character.isspace() or ord(character) < 32 or 127 <= ord(character) < 160
        for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            return None
        # Accessing port validates its syntax and range, including bracketed IPv6.
        parsed.port
        if parsed.netloc.rsplit("@", 1)[-1].endswith(":"):
            return None
        host = parsed.hostname
        try:
            return str(ipaddress.ip_address(host)).lower()
        except ValueError:
            host = host.encode("idna").decode("ascii").lower().removesuffix(".")
            if len(host) > 253 or not all(_HOST_LABEL.fullmatch(label) for label in host.split(".")):
                return None
            return host
    except (ValueError, UnicodeError):
        return None


def is_valid_web_url(url: str) -> bool:
    """Accept absolute HTTP(S) URLs with a syntactically valid host and port."""
    return _validated_host(url) is not None


def is_regular_website_url(url: str) -> bool:
    """Apply the website-only policy to the destination host, including subdomains."""
    host = _validated_host(url)
    return host is not None and not any(
        host == excluded or host.endswith(f".{excluded}") for excluded in EXCLUDED_WEB_PLATFORMS
    )
