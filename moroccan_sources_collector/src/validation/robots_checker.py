from __future__ import annotations

import urllib.robotparser
from functools import lru_cache
from urllib.parse import urlparse


@lru_cache(maxsize=512)
def _parser(robots_url: str) -> urllib.robotparser.RobotFileParser:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        pass
    return parser


def robots_status(url: str, user_agent: str = "*") -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        return "Inconnue"
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        allowed = _parser(robots_url).can_fetch(user_agent, url)
    except Exception:
        return "A_verifier"
    return "Oui" if allowed else "Non"
