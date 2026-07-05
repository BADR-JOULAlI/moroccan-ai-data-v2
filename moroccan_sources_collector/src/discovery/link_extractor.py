from __future__ import annotations

from bs4 import BeautifulSoup

from src.utils.url_utils import is_http_url, normalize_url

SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mp3", ".zip", ".rar")


def extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html or "", "lxml")
    links: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        url = normalize_url(href, base_url=base_url)
        if not is_http_url(url) or url.lower().endswith(SKIP_EXTENSIONS):
            continue
        text = anchor.get_text(" ", strip=True)[:200]
        links.append((url, text))
    return links
