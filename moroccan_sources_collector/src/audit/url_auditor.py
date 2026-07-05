from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.audit.github_validator import validate_github
from src.audit.huggingface_validator import validate_huggingface
from src.audit.kaggle_validator import validate_kaggle
from src.audit.relevance_validator import is_relevant_resource, relevance_scores
from src.audit.search_page_detector import concrete_type_for_url, is_search_page, platform_for_url, query_for_url
from src.audit.soft_404_detector import detect_content_problem
from src.audit.zenodo_validator import validate_zenodo
from src.storage.cache import JsonCache
from src.utils.text_utils import clean_text
from src.utils.url_utils import get_domain, normalize_url, text_fingerprint, url_fingerprint
from src.validation.content_type_checker import content_kind
from src.validation.robots_checker import robots_status
from src.validation.url_checker import check_url


@dataclass
class AuditConfig:
    timeout: float = 20.0
    user_agent: str = "MoroccanSourcesCollector/0.1 audit"
    max_results_per_search: int = 20
    max_attempts: int = 3
    request_delay_seconds: float = 0.5
    force: bool = False


class UrlAuditor:
    def __init__(self, cache_path: Path, config: AuditConfig):
        self.cache = JsonCache(cache_path, ttl_hours=168)
        self.config = config

    def close(self) -> None:
        self.cache.save()

    def audit(self, row: dict) -> dict:
        original = row.get("_input_url") or row.get("URL_finale") or row.get("URL_originale") or ""
        normalized = normalize_url(str(original))
        cached = self.cache.get(normalized, force=self.config.force)
        if cached is None:
            cached = self._check_with_retries(normalized)
            self.cache.set(normalized, cached)
        html = cached.get("html") or ""
        final_url = cached.get("final_url") or normalized
        soup = BeautifulSoup(html, "lxml") if html else BeautifulSoup("", "lxml")
        title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        meta = soup.find("meta", attrs={"name": "description"})
        description = clean_text(meta.get("content", "")) if meta else ""
        canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
        canonical = normalize_url(canonical_tag.get("href"), final_url) if canonical_tag and canonical_tag.get("href") else final_url
        visible = clean_text(soup.get_text(" ", strip=True))[:5000] if html else ""
        problem = detect_content_problem(title, visible, html)
        platform = platform_for_url(final_url)
        type_url = self._type_url(final_url, cached.get("content_type", ""), problem["problem"])
        platform_hint = self._platform_hint(final_url, title, visible, html)
        type_url = platform_hint.get("Type_URL") or type_url
        scores = relevance_scores(title, description, visible, final_url)
        status_http = cached.get("status_http") or ""
        decision, reason = self._decision(type_url, cached, problem, platform_hint, scores)
        return {
            "ID": row.get("ID") or row.get("_row_number"),
            "Nom_source": row.get("Nom_source") or row.get("Source") or platform,
            "URL_originale": original,
            "URL_normalisee": normalized,
            "URL_finale": final_url,
            "URL_canonique": canonical,
            "Domaine": get_domain(final_url),
            "Plateforme": platform,
            "Type_URL": type_url,
            "Statut_HTTP": status_http,
            "Type_MIME": cached.get("content_type") or "",
            "Titre_page": title,
            "Meta_description": description,
            "Message_erreur_detecte": problem["message"],
            "Nombre_resultats": platform_hint.get("Nombre_resultats", 0),
            "Est_page_recherche": "Oui" if is_search_page(final_url) or type_url == "PAGE_RECHERCHE" else "Non",
            "Est_soft_404": "Oui" if problem["problem"] == "SOFT_404" else "Non",
            "Est_page_connexion": "Oui" if problem["problem"] == "PAGE_CONNEXION" or type_url == "PAGE_CONNEXION" else "Non",
            "JavaScript_requis": "Oui" if self._javascript_required(html, cached.get("content_type", "")) else "Non",
            "Robots_txt": robots_status(final_url, self.config.user_agent),
            "Categorie_principale": row.get("Categorie_principale") or row.get("Catégorie") or "",
            **scores,
            "Decision_finale": decision,
            "Raison_decision": reason,
            "URL_remplacement": platform_hint.get("URL_remplacement", ""),
            "Date_verification": datetime.now(timezone.utc).date().isoformat(),
            "Notes": cached.get("error", ""),
            "Hash_URL": url_fingerprint(canonical),
            "Hash_extrait": text_fingerprint(visible[:1000]),
            "URL_recherche_origine": row.get("URL_recherche_origine", ""),
            "Requete_origine": query_for_url(final_url),
            "Plateforme_origine": platform if is_search_page(final_url) else "",
            "Rang_resultat": "",
            "Remplace_URL_ID": "",
        }

    def replacement_record(self, parent: dict, replacement_url: str, rank: int) -> dict:
        row = {"_input_url": replacement_url, "Nom_source": f"Remplacement {parent.get('Plateforme')}"}
        result = self.audit(row)
        result["URL_recherche_origine"] = parent["URL_originale"]
        result["Requete_origine"] = parent.get("Requete_origine") or query_for_url(parent["URL_originale"])
        result["Plateforme_origine"] = parent.get("Plateforme")
        result["Rang_resultat"] = rank
        result["Remplace_URL_ID"] = parent.get("ID")
        return result

    def _check_with_retries(self, url: str) -> dict:
        last_result = None
        for attempt in range(1, max(self.config.max_attempts, 1) + 1):
            result = check_url(url, timeout=self.config.timeout, user_agent=self.config.user_agent)
            last_result = result.__dict__
            status = last_result.get("status_http")
            transient = last_result.get("status_lien") in {"Timeout", "A_recontroler"} or status in {429, 500, 502, 503, 504}
            if not transient or attempt >= self.config.max_attempts:
                break
            time.sleep(self.config.request_delay_seconds)
        time.sleep(self.config.request_delay_seconds)
        return last_result or {
            "final_url": url,
            "status_http": None,
            "status_lien": "A_recontroler",
            "content_type": "unknown",
            "redirection": False,
            "html": "",
            "error": "No result after retries",
        }

    def _type_url(self, url: str, content_type: str, problem: str) -> str:
        if problem == "ZERO_RESULTAT":
            return "PAGE_RECHERCHE"
        if problem == "SOFT_404":
            return "SOFT_404"
        if problem == "PAGE_CONNEXION":
            return "PAGE_CONNEXION"
        if problem == "BLOQUEE":
            return "BLOQUEE"
        concrete = concrete_type_for_url(url)
        if concrete:
            return concrete
        if is_search_page(url):
            return "PAGE_RECHERCHE"
        kind = content_kind(content_type, url)
        if kind == "PDF":
            return "PAGE_DOCUMENT"
        if kind in {"Audio", "Video"}:
            return "PAGE_AUDIO_VIDEO"
        path = urlparse(url).path.strip("/")
        if not path:
            return "PAGE_ACCUEIL"
        if any(seg in path.lower() for seg in ["category", "tag", "topics"]):
            return "PAGE_CATEGORIE"
        if kind == "HTML":
            return "PAGE_CONTENU"
        return "INDETERMINEE"

    def _platform_hint(self, url: str, title: str, text: str, html: str) -> dict:
        for fn in (validate_github, validate_huggingface, validate_kaggle, validate_zenodo):
            hint = fn(url, title, text, html, self.config.max_results_per_search)
            if hint:
                return hint
        return {}

    def _decision(self, type_url: str, check: dict, problem: dict, hint: dict, scores: dict) -> tuple[str, str]:
        if hint.get("Decision_hint"):
            return hint["Decision_hint"], hint.get("Raison_hint", "")
        status = check.get("status_http")
        if check.get("status_lien") in {"Timeout", "Erreur_SSL"}:
            return "A_RECONTROLER", check.get("status_lien")
        if status in {401, 403, 429} or type_url == "BLOQUEE":
            return "A_RECONTROLER", "BLOQUE_OU_LIMITE"
        if status == 404 or type_url == "SOFT_404":
            return "REJETER", "PAGE_ERREUR_OU_SOFT_404"
        if type_url == "PAGE_CONNEXION":
            return "A_RECONTROLER", "PAGE_CONNEXION"
        if type_url == "PAGE_RECHERCHE":
            return "REJETER", problem["problem"] or "PAGE_RECHERCHE_NON_FINALE"
        if not is_relevant_resource(scores, type_url):
            return "REJETER", "HORS_PERIMETRE_OU_PERTINENCE_FAIBLE"
        return "CONSERVER", "RESSOURCE_CONCRETE_PERTINENTE"

    @staticmethod
    def _javascript_required(html: str, content_type: str) -> bool:
        if "html" not in (content_type or ""):
            return False
        text_len = len(BeautifulSoup(html or "", "lxml").get_text(" ", strip=True))
        script_count = (html or "").lower().count("<script")
        return text_len < 200 and script_count >= 5
