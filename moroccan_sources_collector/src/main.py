"""Point d'entree CLI qui orchestre le pipeline ETL, les commandes historiques et les exports."""

from __future__ import annotations

"""Command-line entrypoint for the Moroccan Sources Collector.

The recommended MVP path is intentionally linear and easy to present:

1. Extraction: Playwright discovers concrete YouTube/Facebook URLs from YAML seeds.
2. Transformation: Darija density filtering keeps only relevant social sources.
3. Load: Excel, CSV and JSONL artefacts are written under ``data/output``.

For the jury/demo, the project can be launched with:

``uv run python -m src.main``

Legacy commands are kept for advanced runs and audit experiments, but the default
entrypoint executes the social ETL MVP.
"""

import argparse
import asyncio
import csv
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx
import yaml

from src.audit.audit_exporter import export_audit_excel
from src.audit.excel_loader import load_url_rows, resolve_excel_path
from src.audit.url_auditor import AuditConfig, UrlAuditor
from src.analysis.darija_detector import calculate_darija_score
from src.analysis.page_analyzer import analyze_page
from src.discovery.catalog_crawler import CatalogCrawler
from src.discovery.seed_loader import load_seed_sources
from src.discovery.search_adapters import BrowserDiscoveryConfig, PlaywrightDiscoveryAdapter
from src.expansion.discovery_expander import ExpansionDiscoverer
from src.expansion.duplicate_detector import DuplicateDetector
from src.expansion.existing_catalog import load_existing_catalog, resolve_input_path
from src.scoring.scorer import score_record
from src.storage.cache import JsonCache
from src.storage.csv_exporter import export_csv
from src.storage.expansion_excel_exporter import EXPANDED_COLUMNS, export_expanded_excel
from src.storage.excel_exporter import CATALOG_COLUMNS, export_excel
from src.storage.exporter import DataExporter
from src.storage.jsonl_exporter import export_jsonl, load_jsonl
from src.utils.logging_utils import log_error, setup_logging
from src.utils.url_utils import LinkCandidate, get_domain, normalize_url, text_fingerprint, url_fingerprint
from src.validation.content_type_checker import content_kind
from src.validation.robots_checker import robots_status
from src.validation.url_checker import check_url

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
LOGS = ROOT / "logs"
OUTPUT = DATA / "output"
INTERMEDIATE = DATA / "intermediate"
CANDIDATES_PATH = INTERMEDIATE / "candidates.jsonl"
VERIFIED_PATH = INTERMEDIATE / "verified.jsonl"
JSONL_PATH = OUTPUT / "catalogue_sources_marocaines_ai.jsonl"
CSV_PATH = OUTPUT / "catalogue_sources_marocaines_ai.csv"
XLSX_PATH = OUTPUT / "catalogue_sources_marocaines_ai.xlsx"
EXPANDED_XLSX_PATH = OUTPUT / "catalogue_sources_marocaines_ai_enrichi.xlsx"
NEW_JSONL_PATH = OUTPUT / "nouveaux_liens.jsonl"
NEW_CSV_PATH = OUTPUT / "nouveaux_liens.csv"
DUP_JSONL_PATH = OUTPUT / "doublons_rejetes.jsonl"
DOMAINS_CSV_PATH = OUTPUT / "domaines_decouverts.csv"
AUDITED_XLSX_PATH = OUTPUT / "catalogue_sources_marocaines_ai_audite.xlsx"
REVIEW_CSV_PATH = OUTPUT / "liens_a_valider_manuellement.csv"
CRAWLER_URLS_PATH = OUTPUT / "crawler_urls.txt"
CRAWLER_MANIFEST_PATH = OUTPUT / "crawl_manifest.jsonl"
ACCEPTED_REVIEW_DECISIONS = {"accept", "accepted", "conserver", "oui", "yes", "ok", "valide", "valid"}

REVIEW_COLUMNS = [
    "Decision_validation",
    "URL_finale",
    "Domaine",
    "Nom_source",
    "Categorie_principale",
    "Score_pertinence",
    "Priorite",
    "Statut_HTTP",
    "Statut_lien",
    "Robots_txt",
    "Source_decouverte",
    "Mots_cles_associes",
    "Notes_validation",
]

LOGGER = logging.getLogger(__name__)

MVP_UV_USAGE = """
MVP execution with uv:
  uv init
  uv add playwright httpx beautifulsoup4 openpyxl pyyaml pytest
  uv run playwright install chromium
  uv run python -m src.main

Default command:
  uv run python -m src.main

Explicit command:
  uv run python -m src.main mvp --max-links 800 --min-darija-density 0.15
"""

SOCIAL_DISCOVERY_METHODS = {
    "youtube_search",
    "youtube_keyword",
    "youtube_channel",
    "youtube_videos",
    "youtube_shorts",
    "facebook_page",
    "facebook_public_page",
    "google_facebook_dork",
    "facebook_dork",
}

STATIC_BACKGROUND_PLATFORMS = {"Kaggle", "GitHub"}


def _review_record(record: dict) -> dict:
    """Prepare one row for human validation before crawler export."""
    return {
        "Decision_validation": "",
        "URL_finale": record.get("URL_finale") or record.get("URL_originale") or record.get("url", ""),
        "Domaine": record.get("Domaine") or get_domain(record.get("URL_finale") or record.get("URL_originale") or record.get("url", "")),
        "Nom_source": record.get("Nom_source") or record.get("source_name", ""),
        "Categorie_principale": record.get("Categorie_principale") or record.get("source_category", ""),
        "Score_pertinence": record.get("Score_pertinence", ""),
        "Priorite": record.get("Priorite") or record.get("source_priority", ""),
        "Statut_HTTP": record.get("Statut_HTTP", ""),
        "Statut_lien": record.get("Statut_lien", ""),
        "Robots_txt": record.get("Robots_txt", ""),
        "Source_decouverte": record.get("Source_decouverte") or record.get("source_url", ""),
        "Mots_cles_associes": record.get("Mots_cles_associes") or record.get("anchor_text", ""),
        "Notes_validation": "",
    }


def export_manual_review(records: list[dict], path: Path = REVIEW_CSV_PATH) -> None:
    """Export a CSV file that lets a human accept, reject, or postpone links."""
    export_csv([_review_record(record) for record in records], path, REVIEW_COLUMNS)


def _resolve_output_path(path_value: str | Path, default_parent: Path = OUTPUT) -> Path:
    """Resolve CLI paths relative to data/output by default."""
    path = Path(path_value)
    return path if path.is_absolute() else default_parent / path


def _crawler_manifest_record(row: dict) -> dict:
    """Prepare one accepted human-reviewed row for the crawler manifest."""
    url = normalize_url(row.get("URL_finale", ""))
    return {
        "url": url,
        "domain": row.get("Domaine") or get_domain(url),
        "source_name": row.get("Nom_source", ""),
        "source_category": row.get("Categorie_principale", ""),
        "priority": row.get("Priorite", ""),
        "score": row.get("Score_pertinence", ""),
        "review_decision": row.get("Decision_validation", ""),
        "review_notes": row.get("Notes_validation", ""),
        "discovery_source": row.get("Source_decouverte", ""),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def export_crawler_input_from_review(review_path: Path, urls_path: Path, manifest_path: Path) -> dict:
    """Export crawler inputs from manually accepted review rows only."""
    if not review_path.exists():
        raise FileNotFoundError(f"Fichier de revue introuvable: {review_path}")

    accepted_rows: list[dict] = []
    seen_urls: set[str] = set()
    with review_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            decision = str(row.get("Decision_validation", "")).strip().lower()
            if decision not in ACCEPTED_REVIEW_DECISIONS:
                continue
            url = normalize_url(row.get("URL_finale", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            row["URL_finale"] = url
            accepted_rows.append(row)

    urls_path.parent.mkdir(parents=True, exist_ok=True)
    urls_path.write_text("\n".join(row["URL_finale"] for row in accepted_rows) + ("\n" if accepted_rows else ""), encoding="utf-8")
    export_jsonl([_crawler_manifest_record(row) for row in accepted_rows], manifest_path)
    return {
        "review_csv": str(review_path),
        "accepted_links": len(accepted_rows),
        "urls_txt": str(urls_path),
        "crawl_manifest_jsonl": str(manifest_path),
    }


def load_yaml(path: Path) -> dict:
    """Charge un fichier YAML et retourne un dictionnaire vide si le fichier est sans contenu."""
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _social_seeds(seeds: list[dict]) -> list[dict]:
    # MVP scope: keep only dynamic social sources that can feed the demo quickly.
    """Filtre les seeds pour garder uniquement les methodes de decouverte sociales."""
    return [seed for seed in seeds if str(seed.get("discovery_method", "")).lower() in SOCIAL_DISCOVERY_METHODS]


def _seed_platform(seed: dict) -> str:
    """Detecte la plateforme cible d'un seed a partir de son URL, nom ou mode de collecte."""
    signal = " ".join(
        str(seed.get(key, ""))
        for key in ["platform", "name", "url", "query", "discovery_method"]
    ).lower()
    if "youtube" in signal or "youtu.be" in signal:
        return "YouTube"
    if "facebook" in signal:
        return "Facebook"
    if "kaggle" in signal:
        return "Kaggle"
    if "github" in signal:
        return "GitHub"
    return "Autres"


def _static_background_seeds(seeds: list[dict]) -> list[dict]:
    """Garde les seeds statiques rapides qui peuvent etre collectes sans Playwright."""
    return [seed for seed in seeds if _seed_platform(seed) in STATIC_BACKGROUND_PLATFORMS]


def _canonical_candidate_url(url: str) -> str:
    """Nettoie une URL avant deduplication en preservant l'identifiant metier.

    Pour YouTube, tous les parametres de tracking sont supprimes et seul
    ``watch?v=VIDEO_ID`` est conserve. Pour les autres plateformes, la
    normalisation generale du projet reste appliquee.
    """
    normalized = normalize_url(url)
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        return f"https://www.youtube.com/watch?v={video_id}" if video_id else normalized
    if host.endswith("youtube.com"):
        query = parse_qs(parsed.query)
        video_id = (query.get("v") or [""])[0]
        if video_id:
            return urlunparse(("https", "www.youtube.com", "/watch", "", urlencode({"v": video_id}), ""))
        if parsed.path.startswith("/@") or parsed.path.startswith("/channel/") or parsed.path.startswith("/c/"):
            return urlunparse(("https", "www.youtube.com", parsed.path.rstrip("/"), "", "", ""))
    return normalized


def _browser_config_from_settings(settings: dict) -> BrowserDiscoveryConfig:
    # Centralize Playwright settings so the YAML file remains the only tuning point.
    """Construit la configuration Playwright a partir des parametres YAML du projet."""
    return BrowserDiscoveryConfig(
        headless=bool(settings.get("playwright_headless", True)),
        user_agent=settings.get("browser_user_agent", BrowserDiscoveryConfig().user_agent),
        locale=settings.get("browser_locale", "fr-FR"),
        timezone_id=settings.get("browser_timezone", "Africa/Casablanca"),
        navigation_timeout_ms=int(settings.get("playwright_timeout_ms", 30000)),
        min_delay_seconds=float(settings.get("playwright_min_delay_seconds", 0.8)),
        max_delay_seconds=float(settings.get("playwright_max_delay_seconds", 2.2)),
        scroll_pause_seconds=float(settings.get("playwright_scroll_pause_seconds", 1.2)),
        max_scrolls=max(
            int(settings.get("playwright_max_scrolls", 18)),
            int(settings.get("social_playwright_max_scrolls", 30)),
        ),
        max_results_per_query=max(
            int(settings.get("max_results_per_query", 50)),
            int(settings.get("social_max_results_per_query", 120)),
        ),
        max_concurrent_pages=int(settings.get("playwright_max_concurrent_pages", 2)),
    )


async def _collect_static_platform_links(seeds: list[dict], settings: dict) -> list[dict]:
    """Collecte rapidement les liens Kaggle/GitHub publics sans navigateur Playwright.

    Inputs:
        seeds: liste de seeds catalogues pointant vers Kaggle ou GitHub.
        settings: configuration HTTP, notamment timeout et User-Agent.

    Output:
        liste de dictionnaires candidats compatible avec candidates.jsonl.
    """
    if not seeds:
        return []
    timeout = float(settings.get("request_timeout_seconds", 20))
    headers = {"User-Agent": settings.get("user_agent", "MoroccanSourcesCollector/0.1")}
    records: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for seed in seeds:
            seed_url = seed.get("url")
            if not seed_url:
                continue
            platform = _seed_platform(seed)
            per_seed_limit = int(seed.get("max_results") or seed.get("max_pages") or 20)
            try:
                response = await client.get(seed_url)
                response.raise_for_status()
            except Exception as exc:
                LOGGER.info("[ETL - Extraction] Seed statique ignore %s: %s", seed_url, exc)
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            candidates = [seed_url]
            for anchor in soup.select("a[href]"):
                href = anchor.get("href", "")
                absolute = normalize_url(urljoin(seed_url, href))
                if platform == "Kaggle" and "kaggle.com" not in absolute:
                    continue
                if platform == "GitHub" and "github.com" not in absolute:
                    continue
                candidates.append(absolute)
                if len(candidates) >= per_seed_limit:
                    break
            for url in candidates:
                if not url or url in seen:
                    continue
                seen.add(url)
                records.append({
                    "url": url,
                    "source_name": seed.get("name", platform),
                    "source_url": seed_url,
                    "source_category": seed.get("category", "Dataset_IA"),
                    "source_priority": seed.get("priority", "P1"),
                    "discovery_method": "httpx_static_background",
                    "platform": platform,
                    "anchor_text": seed.get("query") or seed.get("name", ""),
                    "query": seed.get("query", ""),
                    "date_capture": datetime.now(timezone.utc).date().isoformat(),
                    "status": "DISCOVERED",
                })
    LOGGER.info("[ETL - Extraction] %s liens statiques Kaggle/GitHub collectes", len(records))
    return records


async def mvp_extract_async(seeds: list[dict], settings: dict, max_links: int) -> list[dict]:
    """Extract concrete social URLs with Playwright.

    Inputs:
        seeds: YouTube/Facebook discovery seeds loaded from config/seed_sources.yaml.
        settings: runtime configuration, especially Playwright delays and scroll limits.
        max_links: global cap for raw candidate URLs.

    Output:
        A list of dictionaries ready to be written to data/intermediate/candidates.jsonl.
        Only concrete YouTube/Facebook URLs are returned; search pages are not kept.
    """
    config = _browser_config_from_settings(settings)
    social_seeds = _social_seeds(seeds)
    static_task = asyncio.create_task(_collect_static_platform_links(_static_background_seeds(seeds), settings))
    social_quota = min(int(settings.get("max_social_links_per_platform", 400)), max_links)
    per_seed_social_limit = int(settings.get("social_max_results_per_query", config.max_results_per_query))
    extracted: list[dict] = []
    seen: set[str] = set()
    platform_counts: defaultdict[str, int] = defaultdict(int)
    async with PlaywrightDiscoveryAdapter(config) as adapter:
        for seed in social_seeds:
            if len(extracted) >= max_links:
                break
            method = str(seed.get("discovery_method", "")).lower()
            platform = _seed_platform(seed)
            remaining_platform = social_quota - platform_counts[platform]
            if remaining_platform <= 0:
                LOGGER.info("[ETL - Extraction] Quota %s atteint (%s liens)", platform, social_quota)
                continue
            limit = min(
                max(int(seed.get("max_results") or 0), per_seed_social_limit),
                remaining_platform,
                max_links - len(extracted),
            )
            # Dispatch by seed type. Each adapter returns concrete links, never search pages.
            if method in {"youtube_search", "youtube_keyword"}:
                links = await adapter.youtube_search(seed.get("query") or seed.get("name", ""), limit)
            elif method in {"youtube_channel", "youtube_videos"}:
                links = await adapter.youtube_channel_videos(seed.get("url", ""), "videos", limit)
            elif method == "youtube_shorts":
                links = await adapter.youtube_channel_videos(seed.get("url", ""), "shorts", limit)
            elif method in {"facebook_page", "facebook_public_page"}:
                links = await adapter.facebook_public_page_posts(seed.get("url", ""), limit)
            elif method in {"google_facebook_dork", "facebook_dork"}:
                links = await adapter.google_facebook_dork(seed.get("query") or seed.get("name", ""), limit)
            else:
                links = []

            added = 0
            for link in links:
                url = _canonical_candidate_url(link.url)
                # Deduplicate immediately so the next ETL step receives a clean JSONL stream.
                if not url:
                    LOGGER.warning("[REJET] URL vide ou invalide apres nettoyage: %s", link.url)
                    continue
                if url in seen:
                    LOGGER.warning("[REJET] URL dedupliquee: %s", url)
                    continue
                seen.add(url)
                extracted.append({
                    "url": url,
                    "source_name": seed.get("name", link.platform or "Social discovery"),
                    "source_url": link.source_origine,
                    "source_category": seed.get("category", "Audio_video"),
                    "source_priority": seed.get("priority", "P1"),
                    "discovery_method": link.discovery_method,
                    "platform": link.platform,
                    "anchor_text": link.anchor_text,
                    "query": seed.get("query", ""),
                    "date_capture": datetime.now(timezone.utc).date().isoformat(),
                    "status": link.status,
                })
                added += 1
                platform_counts[link.platform or platform] += 1
                if len(extracted) >= max_links:
                    break
            LOGGER.info("[ETL - Extraction] %s liens trouves depuis %s", added, seed.get("name", method))
    for candidate in await static_task:
        if len(extracted) >= max_links:
            break
        url = _canonical_candidate_url(candidate.get("url", ""))
        if not url:
            LOGGER.warning("[REJET] URL statique vide ou invalide apres nettoyage: %s", candidate.get("url", ""))
            continue
        if url in seen:
            LOGGER.warning("[REJET] URL statique dedupliquee: %s", url)
            continue
        seen.add(url)
        candidate["url"] = url
        extracted.append(candidate)
    return extracted


def mvp_extract(args: argparse.Namespace) -> list[dict]:
    """Run the Extraction step and persist raw candidates line by line.

    Inputs:
        args.max_links controls the global extraction target.

    Output:
        Raw candidate dictionaries saved to data/intermediate/candidates.jsonl.
    """
    settings = load_yaml(CONFIG / "settings.yaml")
    seeds = load_seed_sources(CONFIG / "seed_sources.yaml")
    social_count = len(_social_seeds(seeds))
    static_count = len(_static_background_seeds(seeds))
    LOGGER.info(
        "[ETL - Extraction] Demarrage MVP avec %s seeds sociaux et %s seeds statiques",
        social_count,
        static_count,
    )
    records = asyncio.run(mvp_extract_async(seeds, settings, int(args.max_links)))
    export_jsonl(records, CANDIDATES_PATH)
    LOGGER.info("[ETL - Extraction] %s liens bruts sauvegardes dans %s", len(records), CANDIDATES_PATH)
    return records


def mvp_transform(args: argparse.Namespace) -> list[dict]:
    """Transform raw candidates into validated Darija/culture catalogue records.

    Inputs:
        data/intermediate/candidates.jsonl generated by mvp_extract.
        args.min_darija_density is the minimum density score required to keep a URL.

    Output:
        Catalogue-shaped records saved to data/intermediate/verified.jsonl.
    """
    candidates = load_jsonl(CANDIDATES_PATH)
    threshold = float(args.min_darija_density)
    verified: list[dict] = []
    for idx, candidate in enumerate(candidates, start=1):
        # Social platforms do not always expose descriptions without API access.
        # We therefore combine the available public signals before Darija scoring.
        text = " ".join(str(candidate.get(key, "")) for key in ["anchor_text", "query", "source_name", "url"])
        density = calculate_darija_score(text)
        url = _canonical_candidate_url(candidate["url"])
        if not url:
            LOGGER.warning("[REJET] URL invalide pendant transformation: %s", candidate.get("url", ""))
            continue
        platform = candidate.get("platform") or ("YouTube" if "youtube.com" in url or "youtu.be" in url else "Facebook")
        probable_keep = bool(density.get("probable_keep")) or density.get("decision") == "CONSERVER_PROBABLE"
        # MVP rule: a candidate must have enough Darija/Moroccan lexical density.
        if density["density"] < threshold and not probable_keep and platform not in STATIC_BACKGROUND_PLATFORMS:
            LOGGER.warning(
                "[REJET] Densite Darija insuffisante: score=%.4f seuil=%.4f url=%s tokens=%s/%s",
                density["density"],
                threshold,
                url,
                density.get("matched_tokens", 0),
                density.get("total_tokens", 0),
            )
            continue
        record = {column: "" for column in CATALOG_COLUMNS}
        is_static_platform = platform in STATIC_BACKGROUND_PLATFORMS
        decision = (
            "A_recontroler"
            if is_static_platform and density["density"] < threshold
            else "CONSERVER_PROBABLE"
            if probable_keep and density["density"] < threshold
            else "Conserver"
        )
        content_type = {
            "YouTube": "Video",
            "Facebook": "Post_public",
            "Kaggle": "Dataset",
            "GitHub": "Repository",
        }.get(platform, "Source_web")
        # Build records directly in the Excel schema expected by storage/excel_exporter.py.
        record.update({
            "ID": len(verified) + 1,
            "Nom_source": candidate.get("source_name") or platform,
            "URL_originale": url,
            "URL_finale": url,
            "Domaine": get_domain(url),
            "Categorie_principale": candidate.get("source_category", "Audio_video"),
            "Sous_categories": platform,
            "Description_source": candidate.get("anchor_text") or candidate.get("query") or candidate.get("source_name", ""),
            "Type_source": "plateforme_statique" if is_static_platform else "reseau_social_public",
            "Type_contenu": content_type,
            "Langue_principale": density["detected_variant"],
            "Pourcentage_script_arabe": "",
            "Pourcentage_script_latin": "",
            "Score_darija": int(round(density["density"] * 100)),
            "Mots_darija_detectes": ", ".join(density.get("arabizi_tokens", [])),
            "Arabizi_detecte": "Oui" if density.get("arabizi_tokens") else "Non",
            "Decision_linguistique": decision,
            "Contenu_parallele": "Non",
            "Usage_IA": "source_dataset_code" if is_static_platform else "corpus_social_darija",
            "Methode_acces": "HTTPX" if is_static_platform else "Playwright",
            "Statut_HTTP": "",
            "Statut_lien": "A_verifier",
            "Redirection": "Non",
            "Robots_txt": "A_verifier",
            "Licence": "Inconnue",
            "Autorisation_entrainement_IA": "A_verifier",
            "Priorite": candidate.get("source_priority", "P1"),
            "Score_pertinence": int(round(density["density"] * 100)),
            "Score_fiabilite": 60,
            "Date_verification": datetime.now(timezone.utc).date().isoformat(),
            "Source_decouverte": candidate.get("source_url", ""),
            "Mots_cles_associes": candidate.get("query", ""),
            "Notes": (
                f"MVP uv ETL; densite_darija={density['density']}; "
                f"decision={density.get('decision', decision)}; "
                f"tokens={density['matched_tokens']}/{density['total_tokens']}; "
                f"signaux_forts={', '.join(density.get('high_signal_tokens', []))}"
            ),
            "platform": platform,
        })
        verified.append(record)
    export_jsonl(verified, VERIFIED_PATH)
    LOGGER.info("[ETL - Transformation] %s/%s liens gardes avec densite >= %.2f", len(verified), len(candidates), threshold)
    return verified


def mvp_load(args: argparse.Namespace) -> list[dict]:
    """Load validated records into final MVP outputs.

    Inputs:
        data/intermediate/verified.jsonl generated by mvp_transform.

    Output:
        data/output/catalogue_sources_marocaines_ai.xlsx and .jsonl for AI training.
    """
    records = load_jsonl(VERIFIED_PATH)
    export_jsonl(records, JSONL_PATH)
    export_csv(records, CSV_PATH, CATALOG_COLUMNS)
    DataExporter(records).export_excel_by_platform(XLSX_PATH)
    export_manual_review(records)
    LOGGER.info("[ETL - Load] Export Excel: %s", XLSX_PATH)
    LOGGER.info("[ETL - Load] Export JSONL IA: %s", JSONL_PATH)
    LOGGER.info("[ETL - Load] Export revue manuelle: %s", REVIEW_CSV_PATH)
    return records


def run_mvp_etl(args: argparse.Namespace) -> dict:
    """Execute the MVP ETL linearly: Extraction -> Transformation -> Load.

    Inputs:
        CLI args from `uv run python -m src.main`.

    Output:
        A summary dictionary printed in the terminal for the jury/demo.
    """
    LOGGER.info("[MVP] Pipeline lance via uv-compatible entrypoint")
    candidates = mvp_extract(args)
    validated = mvp_transform(args)
    records = mvp_load(args)
    return {
        "mode": "mvp_social_etl",
        "raw_candidates": len(candidates),
        "validated_records": len(validated),
        "exported_records": len(records),
        "candidates_jsonl": str(CANDIDATES_PATH),
        "catalogue_xlsx": str(XLSX_PATH),
        "manual_review_csv": str(REVIEW_CSV_PATH),
        "training_jsonl": str(JSONL_PATH),
        "uv_command": "uv run python -m src.main",
    }


def candidate_to_dict(candidate: LinkCandidate) -> dict:
    """Convertit un LinkCandidate en dictionnaire serialisable JSONL."""
    return {
        "url": candidate.url,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "source_category": candidate.source_category,
        "source_priority": candidate.source_priority,
        "discovery_method": candidate.discovery_method,
        "depth": candidate.depth,
        "anchor_text": candidate.anchor_text,
    }


def candidate_from_dict(data: dict) -> LinkCandidate:
    """Reconstruit un LinkCandidate depuis une ligne JSONL chargee en dictionnaire."""
    return LinkCandidate(
        url=data["url"],
        source_name=data.get("source_name", ""),
        source_url=data.get("source_url", ""),
        source_category=data.get("source_category", "Autre"),
        source_priority=data.get("source_priority", "P2"),
        discovery_method=data.get("discovery_method", "unknown"),
        depth=int(data.get("depth", 0)),
        anchor_text=data.get("anchor_text", ""),
    )


def collect(args: argparse.Namespace) -> list[dict]:
    """Execute le crawler historique et sauvegarde les candidats bruts dans candidates.jsonl."""
    settings = load_yaml(CONFIG / "settings.yaml")
    seeds = load_seed_sources(CONFIG / "seed_sources.yaml", getattr(args, "category", None))
    crawler = CatalogCrawler(settings, LOGS)
    candidates = crawler.crawl(seeds, max_links=getattr(args, "max_links", None))
    records = [candidate_to_dict(candidate) for candidate in candidates]
    export_jsonl(records, CANDIDATES_PATH)
    LOGGER.info("Collected %s candidates", len(records))
    return records


def _base_record(candidate: LinkCandidate, idx: int, check: dict, settings: dict, regions_config: dict) -> dict:
    """Construit une ligne catalogue analysee, verifiee, enrichie et scoree."""
    now = datetime.now(timezone.utc).date().isoformat()
    final_url = check.get("final_url") or candidate.url
    html = check.get("html") or ""
    kind = content_kind(check.get("content_type", ""), final_url)
    if kind == "HTML" and html:
        analysis = analyze_page(html, final_url, candidate.source_category, regions_config)
    else:
        analysis = {
            "Description_source": candidate.anchor_text or candidate.source_name,
            "Type_contenu": kind,
            "Langue_principale": "indeterminee",
            "Pourcentage_script_arabe": 0,
            "Pourcentage_script_latin": 0,
            "Score_darija": 0,
            "Mots_darija_detectes": "",
            "Arabizi_detecte": "Non",
            "Decision_linguistique": "A_recontroler",
            "Contenu_parallele": "Non",
            "Langue_source": "",
            "Langue_cible": "",
            "Type_alignement": "non_aligne",
            "Nombre_paires_detectees": 0,
            "Exemples_paires": "",
            "Score_alignement": 0,
            "Region_marocaine": "",
            "Categorie_principale": candidate.source_category,
            "Sous_categories": "",
            "Usage_IA": "non_determine",
            "Licence": "Inconnue",
            "URL_licence": "",
            "Autorisation_entrainement_IA": "Inconnue",
        }
    robots = robots_status(final_url, settings.get("user_agent", "*"))
    record = {
        "ID": idx,
        "Nom_source": candidate.source_name,
        "URL_originale": candidate.url,
        "URL_finale": final_url,
        "Domaine": get_domain(final_url),
        "Type_source": "catalogue",
        "Methode_acces": "HTTP",
        "Statut_HTTP": check.get("status_http") or "",
        "Statut_lien": check.get("status_lien") or "A_recontroler",
        "Redirection": "Oui" if check.get("redirection") else "Non",
        "Robots_txt": robots,
        "Priorite": candidate.source_priority,
        "Date_verification": now,
        "Source_decouverte": candidate.source_url,
        "Mots_cles_associes": candidate.anchor_text,
        "Notes": check.get("error", ""),
        **analysis,
    }
    if robots == "Non":
        record["Autorisation_collecte"] = "Non"
    return score_record(record)


def _canonical_from_html(html: str, fallback_url: str) -> str:
    """Extrait l'URL canonique d'une page HTML ou retourne l'URL de secours."""
    if not html:
        return fallback_url
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    return normalize_url(tag.get("href"), fallback_url) if tag and tag.get("href") else fallback_url


def _to_expanded_record(record: dict, idx: int, batch_id: str = "") -> dict:
    """Adapte une ligne catalogue au schema enrichi utilise par l'export d'expansion."""
    url_finale = record.get("URL_finale") or record.get("URL_originale") or ""
    expanded = {column: record.get(column, "") for column in EXPANDED_COLUMNS}
    expanded.update({
        "ID": idx,
        "URL_originale": record.get("URL_originale") or url_finale,
        "URL_finale": url_finale,
        "URL_canonique": record.get("URL_canonique") or url_finale,
        "Domaine": record.get("Domaine") or (get_domain(url_finale) if url_finale else ""),
        "Date_decouverte": record.get("Date_decouverte") or record.get("Date_verification") or "",
        "Methode_decouverte": record.get("Methode_decouverte") or record.get("Methode_acces") or "",
        "Requete_decouverte": record.get("Requete_decouverte") or record.get("Mots_cles_associes") or "",
        "Profondeur_crawl": record.get("Profondeur_crawl") or "",
        "Est_nouveau": record.get("Est_nouveau") or "Non",
        "Batch_id": record.get("Batch_id") or batch_id,
        "Hash_URL": record.get("Hash_URL") or (url_fingerprint(url_finale) if url_finale else ""),
        "Hash_contenu": record.get("Hash_contenu") or "",
        "Doublon_de": record.get("Doublon_de") or "",
    })
    return expanded


def _expanded_new_record(candidate, idx: int, check: dict, settings: dict, regions_config: dict, batch_id: str) -> dict:
    """Transforme un nouveau candidat d'expansion en ligne enrichie avec hashes et metadata."""
    link_candidate = LinkCandidate(
        url=candidate.url,
        source_name=candidate.source,
        source_url=candidate.source,
        source_category="Autre",
        source_priority="P2",
        discovery_method=candidate.method,
        depth=candidate.depth,
        anchor_text=candidate.query,
    )
    base = _base_record(link_candidate, idx, check, settings, regions_config)
    html = check.get("html") or ""
    text = base.get("Texte_extrait") or base.get("Description_source") or ""
    canonical = _canonical_from_html(html, base.get("URL_finale") or candidate.url)
    base.update({
        "URL_canonique": canonical,
        "Date_decouverte": datetime.now(timezone.utc).date().isoformat(),
        "Methode_decouverte": candidate.method,
        "Requete_decouverte": candidate.query,
        "Profondeur_crawl": candidate.depth,
        "Est_nouveau": "Oui",
        "Batch_id": batch_id,
        "Hash_URL": url_fingerprint(canonical),
        "Hash_contenu": text_fingerprint(text),
        "Doublon_de": "",
    })
    if base.get("Langue_principale") == "autre_langue" and base.get("Categorie_principale") in {"Dataset_IA", "Publication_scientifique"}:
        base["Langue_principale"] = "anglais_dataset_darija"
    elif base.get("Langue_principale") == "autre_langue" and any(t in str(base.get("Description_source", "")).lower() for t in ["maroc", "morocco", "moroccan", "culture"]):
        base["Langue_principale"] = "francais_culture_marocaine"
    return _to_expanded_record(base, idx, batch_id)


def _write_domains_csv(records: list[dict], path: Path) -> None:
    """Ecrit un resume CSV par domaine pour les nouveaux liens decouverts."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("Domaine"):
            grouped[record["Domaine"]].append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["domaine", "nombre_de_nouveaux_liens", "categorie_dominante", "langue_dominante", "score_moyen", "statut_robots_txt"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for domain, items in sorted(grouped.items()):
            writer.writerow({
                "domaine": domain,
                "nombre_de_nouveaux_liens": len(items),
                "categorie_dominante": Counter(i.get("Categorie_principale") for i in items).most_common(1)[0][0],
                "langue_dominante": Counter(i.get("Langue_principale") for i in items).most_common(1)[0][0],
                "score_moyen": round(sum(int(i.get("Score_pertinence") or 0) for i in items) / len(items), 2),
                "statut_robots_txt": Counter(i.get("Robots_txt") for i in items).most_common(1)[0][0],
            })


def expand(args: argparse.Namespace) -> dict:
    """Elargit un catalogue existant avec de nouveaux liens dedupliques et exporte les resultats."""
    settings = load_yaml(CONFIG / "settings.yaml")
    settings.update({
        "max_depth": 3,
        "max_total_requests": 10000,
        "request_timeout_seconds": min(int(settings.get("request_timeout_seconds", 20)), 3),
    })
    expansion_handler = logging.FileHandler(LOGS / "expansion.log", encoding="utf-8")
    expansion_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(expansion_handler)
    input_path = resolve_input_path(args.input, ROOT)
    existing = load_existing_catalog(input_path)
    detector = DuplicateDetector(existing)
    discoverer = ExpansionDiscoverer(existing, detector, CONFIG, settings)
    batch_id = datetime.now().strftime("EXPANSION_%Y%m%d_%H%M%S")
    discovery_target = min(args.target_new_links, 700)
    candidates, duplicates = discoverer.discover(discovery_target, args.max_links_per_domain, getattr(args, "category", None))
    candidates = candidates[:700]

    regions_config = load_yaml(CONFIG / "regions.yaml")
    cache = JsonCache(DATA / "cache" / "expansion_url_checks.json", ttl_hours=settings.get("cache_ttl_hours", 168))
    new_records: list[dict] = []
    for candidate in candidates:
        cached = cache.get(candidate.url, force=getattr(args, "force", False))
        if cached is None:
            result = check_url(candidate.url, timeout=float(settings["request_timeout_seconds"]), user_agent=settings.get("user_agent", "*"))
            cached = result.__dict__
            cache.set(candidate.url, cached)
        if cached.get("error"):
            log_error(LOGS, candidate.url, "expansion_verify", cached["error"])
        final_decision = detector.check_url(cached.get("final_url") or candidate.url)
        if final_decision.is_duplicate:
            duplicates.append({
                "URL_candidate": candidate.url,
                "URL_existante_correspondante": final_decision.duplicate_of,
                "type_doublon": "redirection_vers_existant",
                "raison": final_decision.reason,
                "score_similarite": final_decision.similarity,
                "source": candidate.source,
                "methode": candidate.method,
            })
            continue
        idx = len(existing.records) + len(new_records) + 1
        record = _expanded_new_record(candidate, idx, cached, settings, regions_config, batch_id)
        if candidate.method not in {"platform_search", "domain_common_path", "curated_common_path"}:
            content_dup = detector.check_content(record["URL_finale"], record.get("Description_source", "") + " " + record.get("Exemples_paires", ""))
            if content_dup.is_duplicate:
                duplicates.append({
                    "URL_candidate": candidate.url,
                    "URL_existante_correspondante": content_dup.duplicate_of,
                    "type_doublon": content_dup.duplicate_type,
                    "raison": content_dup.reason,
                    "score_similarite": content_dup.similarity,
                    "source": candidate.source,
                    "methode": candidate.method,
                })
                continue
        detector.add_url(record["URL_finale"])
        new_records.append(record)
        if len(new_records) % 50 == 0:
            export_jsonl(new_records, INTERMEDIATE / "expansion_checkpoint_records.jsonl")
            export_jsonl(duplicates, INTERMEDIATE / "expansion_checkpoint_duplicates.jsonl")
            cache.save()
    cache.save()

    existing_expanded = [_to_expanded_record(record, idx + 1) for idx, record in enumerate(existing.records)]
    all_records = existing_expanded + new_records
    for idx, record in enumerate(all_records, start=1):
        record["ID"] = idx

    export_jsonl(new_records, NEW_JSONL_PATH)
    export_csv(new_records, NEW_CSV_PATH, EXPANDED_COLUMNS)
    export_jsonl(duplicates, DUP_JSONL_PATH)
    _write_domains_csv(new_records, DOMAINS_CSV_PATH)
    export_expanded_excel(all_records, new_records, duplicates, EXPANDED_XLSX_PATH, len(existing.records))
    return {
        "existing_rows": len(existing.records),
        "existing_domains": len(existing.domains),
        "candidates": len(candidates),
        "duplicates": len(duplicates),
        "new_records": len(new_records),
        "new_domains": len({r.get("Domaine") for r in new_records if r.get("Domaine")}),
        "new_darija": sum((r.get("Score_darija") or 0) >= 20 or str(r.get("Langue_principale", "")).startswith("darija") for r in new_records),
        "new_fr_darija": sum(r.get("Contenu_parallele") == "Oui" or r.get("Langue_principale") == "francais_darija" for r in new_records),
        "new_culture": sum(r.get("Categorie_principale") in {"Traditions", "Patrimoine_materiel", "Patrimoine_immateriel", "Gastronomie", "Artisanat", "Histoire", "Litterature"} for r in new_records),
        "new_p0": sum(r.get("Priorite") == "P0" for r in new_records),
        "recheck": sum(r.get("Statut_lien") not in {"Accessible", "Accessible_avec_redirection"} or r.get("Licence") == "Inconnue" for r in new_records),
        "total_final": len(all_records),
        "xlsx": str(EXPANDED_XLSX_PATH),
        "jsonl": str(NEW_JSONL_PATH),
        "csv": str(NEW_CSV_PATH),
    }


def verify(args: argparse.Namespace) -> list[dict]:
    """Verifie les URLs candidates, analyse leur contenu et sauvegarde les lignes validees."""
    settings = load_yaml(CONFIG / "settings.yaml")
    regions_config = load_yaml(CONFIG / "regions.yaml")
    candidates_data = load_jsonl(CANDIDATES_PATH)
    if not candidates_data:
        candidates_data = collect(args)
    max_links = getattr(args, "max_links", None)
    if max_links:
        candidates_data = candidates_data[:max_links]
    cache = JsonCache(DATA / "cache" / "url_checks.json", ttl_hours=settings.get("cache_ttl_hours", 168))
    records = []
    for idx, data in enumerate(candidates_data, start=1):
        candidate = candidate_from_dict(data)
        url = normalize_url(candidate.url)
        cached = cache.get(url, force=getattr(args, "force", False))
        if cached is None:
            result = check_url(
                url,
                timeout=float(settings.get("request_timeout_seconds", 20)),
                user_agent=settings.get("user_agent", "MoroccanSourcesCollector/0.1"),
            )
            cached = result.__dict__
            cache.set(url, cached)
        if cached.get("error"):
            log_error(LOGS, url, "verify", cached["error"])
        try:
            records.append(_base_record(candidate, idx, cached, settings, regions_config))
        except Exception as exc:
            log_error(LOGS, url, "analysis", str(exc))
    cache.save()
    export_jsonl(records, VERIFIED_PATH)
    LOGGER.info("Verified %s records", len(records))
    return records


def export_outputs(args: argparse.Namespace) -> list[dict]:
    """Ecrit les donnees transformees en JSONL, CSV, Excel et fichier de revue manuelle."""
    records = load_jsonl(VERIFIED_PATH)
    if not records:
        records = verify(args)
    export_jsonl(records, JSONL_PATH)
    export_csv(records, CSV_PATH, CATALOG_COLUMNS)
    DataExporter(records).export_excel_by_platform(XLSX_PATH)
    export_manual_review(records)
    LOGGER.info("Exported JSONL, CSV and Excel")
    return records


def run_all(args: argparse.Namespace) -> list[dict]:
    """Execute la chaine historique collect -> verify -> export."""
    collect(args)
    verify(args)
    return export_outputs(args)


def audit_links(args: argparse.Namespace) -> dict:
    """Audite les liens d'un fichier Excel et produit un classeur annote avec les decisions."""
    settings = load_yaml(CONFIG / "settings.yaml")
    input_path = resolve_excel_path(args.input, ROOT)
    rows, sheet_name, url_column = load_url_rows(input_path)
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = OUTPUT / output_path
    auditor = UrlAuditor(
        DATA / "cache" / "audit_url_checks.json",
        AuditConfig(
            timeout=float(settings.get("request_timeout_seconds", 20)),
            user_agent=settings.get("user_agent", "MoroccanSourcesCollector/0.1 audit"),
            max_results_per_search=args.max_results_per_search,
            force=args.force,
        ),
    )
    audited: list[dict] = []
    duplicates: list[dict] = []
    seen_hashes: dict[str, str] = {}
    domain_counts: Counter[str] = Counter()
    try:
        for row_index, row in enumerate(rows, start=1):
            record = auditor.audit(row)
            if record.get("Domaine"):
                domain_counts[record["Domaine"]] += 1
            hash_key = record.get("Hash_URL") or url_fingerprint(record["URL_finale"])
            if hash_key in seen_hashes:
                record["Decision_finale"] = "REJETER"
                record["Raison_decision"] = "DOUBLON"
                duplicates.append({
                    "URL_candidate": record["URL_finale"],
                    "URL_existante": seen_hashes[hash_key],
                    "type_doublon": "HASH_URL",
                    "raison": "URL normalisee/canonique deja vue",
                    "score_similarite": 1.0,
                })
            else:
                seen_hashes[hash_key] = record["URL_finale"]
            audited.append(record)
            if record["Decision_finale"] == "REMPLACER" and record.get("URL_remplacement"):
                for rank, replacement_url in enumerate(str(record["URL_remplacement"]).splitlines(), start=1):
                    if rank > args.max_results_per_search:
                        break
                    child = auditor.replacement_record(record, replacement_url, rank)
                    child_domain = child.get("Domaine", "")
                    if child_domain and domain_counts[child_domain] >= args.max_links_per_domain:
                        child["Decision_finale"] = "A_RECONTROLER"
                        child["Raison_decision"] = "LIMITE_DOMAINE_ATTEINTE"
                    child_hash = child.get("Hash_URL") or url_fingerprint(child["URL_finale"])
                    if child_hash in seen_hashes:
                        child["Decision_finale"] = "REJETER"
                        child["Raison_decision"] = "DOUBLON"
                        duplicates.append({
                            "URL_candidate": child["URL_finale"],
                            "URL_existante": seen_hashes[child_hash],
                            "type_doublon": "HASH_URL",
                            "raison": "Remplacement deja present",
                            "score_similarite": 1.0,
                        })
                    else:
                        seen_hashes[child_hash] = child["URL_finale"]
                    if child_domain:
                        domain_counts[child_domain] += 1
                    audited.append(child)
            if row_index % 25 == 0:
                auditor.cache.save()
    finally:
        auditor.close()
    export_audit_excel(audited, duplicates, output_path, len(rows))
    summary = {
        "input_sheet": sheet_name,
        "url_column": url_column,
        "total_urls_loaded": len(rows),
        "search_pages": sum(r["Type_URL"] == "PAGE_RECHERCHE" for r in audited),
        "zero_result_searches": sum(r["Raison_decision"] == "ZERO_RESULTAT" for r in audited),
        "soft_404": sum(r["Type_URL"] == "SOFT_404" for r in audited),
        "login_pages": sum(r["Type_URL"] == "PAGE_CONNEXION" for r in audited),
        "dead_links": sum(r.get("Statut_HTTP") == 404 for r in audited),
        "accessible_but_useless": sum(str(r.get("Statut_HTTP")).startswith("2") and r["Decision_finale"] == "REJETER" for r in audited),
        "replaced_links": sum(r["Decision_finale"] == "REMPLACER" for r in audited),
        "concrete_extracted": sum(1 for r in audited if r.get("URL_recherche_origine")),
        "duplicates_rejected": len(duplicates),
        "kept_sources": sum(r["Decision_finale"] == "CONSERVER" for r in audited),
        "to_recheck": sum(r["Decision_finale"] == "A_RECONTROLER" for r in audited),
        "output": str(output_path),
    }
    return summary


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI et declare toutes les commandes disponibles."""
    parser = argparse.ArgumentParser(
        description="Moroccan AI sources collector MVP",
        epilog=MVP_UV_USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--max-links", type=int, default=800, help="MVP target for raw YouTube/Facebook candidates.")
    parser.add_argument("--min-darija-density", type=float, default=0.15, help="Minimum Darija density required after transformation.")
    sub = parser.add_subparsers(dest="command", required=False)
    mvp_cmd = sub.add_parser("mvp", help="Run the uv-compatible MVP ETL: Extraction -> Transformation -> Load.")
    mvp_cmd.add_argument("--max-links", type=int, default=800)
    mvp_cmd.add_argument("--min-darija-density", type=float, default=0.15)
    for name in ["collect", "verify", "export", "run-all"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--max-links", type=int, default=None)
        cmd.add_argument("--force", action="store_true")
        if name == "collect":
            cmd.add_argument("--category", choices=["darija", "culture", "parallel"], default=None)
        if name == "verify":
            cmd.add_argument("--retry-errors", action="store_true")
    expand_cmd = sub.add_parser("expand")
    expand_cmd.add_argument("--input", required=True)
    expand_cmd.add_argument("--target-new-links", type=int, default=1000)
    expand_cmd.add_argument("--minimum-new-links", type=int, default=500)
    expand_cmd.add_argument("--max-links-per-domain", type=int, default=40)
    expand_cmd.add_argument("--force", action="store_true")
    expand_cmd.add_argument("--category", choices=["darija", "culture", "parallel"], default=None)
    audit_cmd = sub.add_parser("audit-links")
    audit_cmd.add_argument("--input", required=True)
    audit_cmd.add_argument("--output", default="catalogue_sources_marocaines_ai_audite.xlsx")
    audit_cmd.add_argument("--retry-errors", action="store_true")
    audit_cmd.add_argument("--use-playwright", action="store_true")
    audit_cmd.add_argument("--max-results-per-search", type=int, default=20)
    audit_cmd.add_argument("--max-links-per-domain", type=int, default=40)
    audit_cmd.add_argument("--force", action="store_true")
    crawler_cmd = sub.add_parser("export-crawler-input")
    crawler_cmd.add_argument("--input", default=str(REVIEW_CSV_PATH))
    crawler_cmd.add_argument("--urls-output", default=str(CRAWLER_URLS_PATH))
    crawler_cmd.add_argument("--manifest-output", default=str(CRAWLER_MANIFEST_PATH))
    return parser


def main(argv: list[str] | None = None) -> None:
    """Point d'entree executable appele par la ligne de commande."""
    setup_logging(LOGS)
    args = build_parser().parse_args(argv)
    INTERMEDIATE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.command in {None, "mvp"}:
        print(json.dumps(run_mvp_etl(args), ensure_ascii=False, indent=2))
    elif args.command == "collect":
        collect(args)
    elif args.command == "verify":
        verify(args)
    elif args.command == "export":
        export_outputs(args)
    elif args.command == "run-all":
        records = run_all(args)
        print(json.dumps({
            "records": len(records),
            "jsonl": str(JSONL_PATH),
            "csv": str(CSV_PATH),
            "xlsx": str(XLSX_PATH),
            "manual_review_csv": str(REVIEW_CSV_PATH),
        }, ensure_ascii=False, indent=2))
    elif args.command == "expand":
        print(json.dumps(expand(args), ensure_ascii=False, indent=2))
    elif args.command == "audit-links":
        print(json.dumps(audit_links(args), ensure_ascii=False, indent=2))
    elif args.command == "export-crawler-input":
        print(json.dumps(export_crawler_input_from_review(
            _resolve_output_path(args.input),
            _resolve_output_path(args.urls_output),
            _resolve_output_path(args.manifest_output),
        ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
