"""Module de validation technique des URLs, contenus ou r?gles d?acc?s."""

from __future__ import annotations

import ssl
from dataclasses import dataclass

import httpx

from src.validation.content_type_checker import normalize_content_type


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


def check_url(url: str, timeout: float = 20, user_agent: str = "MoroccanSourcesCollector/0.1") -> UrlCheckResult:
    """V?rifie l??tat ou la conformit? d?une ressource."""
    headers = {"User-Agent": user_agent}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            response = None
            try:
                response = client.head(url)
                if response.status_code >= 400 or not response.headers.get("content-type"):
                    response = None
            except httpx.HTTPError:
                response = None
            if response is None:
                response = client.get(url)
            elif "html" in normalize_content_type(response.headers.get("content-type")):
                response = client.get(url)
            content_type = normalize_content_type(response.headers.get("content-type"))
            html = response.text[:250000] if "html" in content_type else ""
            return UrlCheckResult(
                final_url=str(response.url),
                status_http=response.status_code,
                status_lien=_status_label(response.status_code, str(response.url) != url),
                content_type=content_type,
                redirection=str(response.url) != url,
                html=html,
            )
    except httpx.TimeoutException as exc:
        return UrlCheckResult(url, None, "Timeout", "unknown", False, error=str(exc))
    except (httpx.ConnectError, ssl.SSLError) as exc:
        message = str(exc)
        status = "Erreur_SSL" if "ssl" in message.lower() or "certificate" in message.lower() else "A_recontroler"
        return UrlCheckResult(url, None, status, "unknown", False, error=message)
    except Exception as exc:
        return UrlCheckResult(url, None, "A_recontroler", "unknown", False, error=str(exc))
