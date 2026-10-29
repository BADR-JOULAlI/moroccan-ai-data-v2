"""Module de validation technique des URLs, contenus ou r?gles d?acc?s."""

from __future__ import annotations

from collections.abc import Callable
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from src.validation.content_type_checker import normalize_content_type
from src.validation.robots_checker import robots_status
from src.validation.url_policy import is_regular_website_url, is_valid_web_url


def _has_text_body(content_type: str) -> bool:
    """Retain HTML and XML feeds for page and sitemap discovery."""
    return "html" in content_type or "xml" in content_type


@dataclass
class UrlCheckResult:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de UrlCheckResult."""
    final_url: str
    status_http: int | None
    status_lien: str
    content_type: str
    redirection: bool
    html: str = ""
    error: str = ""
    robots_txt: str = "A_verifier"


def _status_label(status: int | None, redirected: bool) -> str:
    """D?crit le fonctionnement de `_status_label` et retourne le r?sultat attendu par le module."""
    if status is None:
        return "A_recontroler"
    if 200 <= status < 300:
        return "Accessible_avec_redirection" if redirected else "Accessible"
    if status in {401, 403, 429}:
        return "Bloque"
    if status == 404:
        return "Introuvable"
    if status >= 500:
        return "Serveur_en_erreur"
    return "A_recontroler"


def check_url(
    url: str,
    timeout: float = 20,
    user_agent: str = "MoroccanSourcesCollector/0.1",
    *,
    url_policy: Callable[[str], bool] | None = is_regular_website_url,
) -> UrlCheckResult:
    """Check robots before each request, including every redirect destination.

    An explicit ``url_policy=None`` permits legacy platform auditing while
    retaining HTTP(S) validation and robots enforcement.
    """
    current_url = url
    redirected = False
    current_robots = "A_verifier"

    def blocked_result(status: str, message: str) -> UrlCheckResult:
        return UrlCheckResult(
            current_url, None, status, "unknown", redirected,
            error=message, robots_txt=current_robots,
        )

    def request_checked(client: httpx.Client, method: str) -> httpx.Response | UrlCheckResult:
        nonlocal current_url, redirected, current_robots
        for redirects in range(11):
            current_robots = "A_verifier"
            if (
                not is_valid_web_url(current_url)
                or (url_policy is not None and not url_policy(current_url))
            ):
                return blocked_result("Hors_perimetre", "URL excluded by the crawl policy")
            current_robots = robots_status(current_url, user_agent, timeout=timeout, url_policy=url_policy)
            if current_robots != "Oui":
                status = "Robots_interdit" if current_robots == "Non" else "Robots_a_verifier"
                return blocked_result(status, "Robots rules do not currently permit this request")

            response = client.request(method, current_url)
            if response.status_code not in {301, 302, 303, 307, 308} or not response.headers.get("location"):
                return response
            target = urljoin(current_url, response.headers["location"])
            current_url = target
            redirected = True
            if redirects == 10:
                return blocked_result("A_recontroler", "Too many redirects (maximum: 10)")
        raise AssertionError("unreachable redirect loop")

    try:
        with httpx.Client(follow_redirects=False, timeout=timeout, headers={"User-Agent": user_agent}) as client:
            response = None
            try:
                response = request_checked(client, "HEAD")
                if isinstance(response, UrlCheckResult):
                    return response
                if response.status_code >= 400 or not response.headers.get("content-type"):
                    response = None
            except httpx.HTTPError:
                response = None
            if response is None or _has_text_body(normalize_content_type(response.headers.get("content-type"))):
                response = request_checked(client, "GET")
                if isinstance(response, UrlCheckResult):
                    return response
            content_type = normalize_content_type(response.headers.get("content-type"))
            # XML must remain well formed for sitemap/feed parsing. The HTTP
            # response is already loaded; slicing it can silently lose all links.
            if "html" in content_type:
                html = response.text[:250000]
            elif _has_text_body(content_type):
                html = response.text
            else:
                html = ""
            return UrlCheckResult(
                final_url=str(response.url),
                status_http=response.status_code,
                status_lien=_status_label(response.status_code, redirected),
                content_type=content_type,
                redirection=redirected,
                html=html,
                robots_txt=current_robots,
            )
    except httpx.TimeoutException as exc:
        return blocked_result("Timeout", str(exc))
    except (httpx.ConnectError, ssl.SSLError) as exc:
        message = str(exc)
        status = "Erreur_SSL" if "ssl" in message.lower() or "certificate" in message.lower() else "A_recontroler"
        return blocked_result(status, message)
    except Exception as exc:
        return blocked_result("A_recontroler", str(exc))
