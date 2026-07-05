from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import yaml

from src.audit.audit_exporter import export_audit_excel
from src.audit.excel_loader import load_url_rows, resolve_excel_path
from src.audit.url_auditor import AuditConfig, UrlAuditor
from src.analysis.page_analyzer import analyze_page
from src.discovery.catalog_crawler import CatalogCrawler
from src.discovery.seed_loader import load_seed_sources
from src.expansion.discovery_expander import ExpansionDiscoverer
from src.expansion.duplicate_detector import DuplicateDetector
from src.expansion.existing_catalog import load_existing_catalog, resolve_input_path
from src.scoring.scorer import score_record
from src.storage.cache import JsonCache
from src.storage.csv_exporter import export_csv
from src.storage.expansion_excel_exporter import EXPANDED_COLUMNS, export_expanded_excel
from src.storage.excel_exporter import CATALOG_COLUMNS, export_excel
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

LOGGER = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def candidate_to_dict(candidate: LinkCandidate) -> dict:
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
    settings = load_yaml(CONFIG / "settings.yaml")
    seeds = load_seed_sources(CONFIG / "seed_sources.yaml", getattr(args, "category", None))
    crawler = CatalogCrawler(settings, LOGS)
    candidates = crawler.crawl(seeds, max_links=getattr(args, "max_links", None))
    records = [candidate_to_dict(candidate) for candidate in candidates]
    export_jsonl(records, CANDIDATES_PATH)
    LOGGER.info("Collected %s candidates", len(records))
    return records


def _base_record(candidate: LinkCandidate, idx: int, check: dict, settings: dict, regions_config: dict) -> dict:
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
    if not html:
        return fallback_url
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    return normalize_url(tag.get("href"), fallback_url) if tag and tag.get("href") else fallback_url


def _to_expanded_record(record: dict, idx: int, batch_id: str = "") -> dict:
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
    records = load_jsonl(VERIFIED_PATH)
    if not records:
        records = verify(args)
    export_jsonl(records, JSONL_PATH)
    export_csv(records, CSV_PATH, CATALOG_COLUMNS)
    export_excel(records, XLSX_PATH)
    LOGGER.info("Exported JSONL, CSV and Excel")
    return records


def run_all(args: argparse.Namespace) -> list[dict]:
    collect(args)
    verify(args)
    return export_outputs(args)


def audit_links(args: argparse.Namespace) -> dict:
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
    parser = argparse.ArgumentParser(description="Moroccan AI sources collector")
    sub = parser.add_subparsers(dest="command", required=True)
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
    return parser


def main(argv: list[str] | None = None) -> None:
    setup_logging(LOGS)
    args = build_parser().parse_args(argv)
    INTERMEDIATE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.command == "collect":
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
        }, ensure_ascii=False, indent=2))
    elif args.command == "expand":
        print(json.dumps(expand(args), ensure_ascii=False, indent=2))
    elif args.command == "audit-links":
        print(json.dumps(audit_links(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
