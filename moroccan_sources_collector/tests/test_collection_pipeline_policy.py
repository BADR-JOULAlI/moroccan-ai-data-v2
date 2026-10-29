"""Exercise access rules, cached checks, selection and crawler export together."""

from argparse import Namespace
import pandas as pd
import pytest

from src import main
from src.storage.cache import JsonCache
from src.storage.jsonl_exporter import export_jsonl, load_jsonl
from src.validation.url_checker import UrlCheckResult


URL = "https://example.ma/page"
TEXT = "wach alpha beta gamma delta"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(main, "DATA", data)
    monkeypatch.setattr(main, "LOGS", tmp_path / "logs")
    paths = {
        "CANDIDATES_PATH": "intermediate/candidates.jsonl",
        "VERIFIED_PATH": "intermediate/verified.jsonl",
        "BLOCKED_PATH": "intermediate/blocked_candidates.jsonl",
        "REJECTED_LINGUISTIC_PATH": "intermediate/rejected_linguistic.jsonl",
        "JSONL_PATH": "output/catalogue.jsonl",
        "CSV_PATH": "output/catalogue.csv",
        "XLSX_PATH": "output/catalogue.xlsx",
        "REVIEW_CSV_PATH": "output/review.csv",
    }
    for name, relative in paths.items():
        monkeypatch.setattr(main, name, data / relative)
    monkeypatch.setattr(main, "load_yaml", lambda path: {"request_timeout_seconds": 1})
    monkeypatch.setattr(main, "robots_status", lambda *args, **kwargs: "Oui")
    return data


def candidates(*urls):
    return [{
        "url": url, "source_name": "Source", "source_url": url,
        "source_category": "Darija", "source_priority": "P1",
        "discovery_method": "seed", "anchor_text": "",
    } for url in urls]


def good_check(url=URL, text=TEXT):
    return UrlCheckResult(
        url, 200, "Accessible", "text/html", False,
        html=f"<html><body><p>{text}</p></body></html>", robots_txt="Oui",
    )


@pytest.mark.parametrize("threshold, expected", [(0.2, 1), (0.21, 0), (0, 1)])
def test_active_mvp_threshold_changes_shortlist_and_review_once(workspace, monkeypatch, threshold, expected):
    checks = []

    def collect(args):
        rows = candidates(URL)
        export_jsonl(rows, main.CANDIDATES_PATH)
        return rows

    def check(url, **kwargs):
        checks.append(url)
        return good_check(url)

    monkeypatch.setattr(main, "collect", collect)
    monkeypatch.setattr(main, "check_url", check)
    summary = main.run_mvp_etl(Namespace(max_links=10, min_darija_density=threshold, force=False))

    assert summary["validated_records"] == summary["exported_records"] == expected
    assert checks == [URL]  # An empty shortlist must not trigger a second verify.
    assert len(load_jsonl(main.JSONL_PATH)) == expected
    review = pd.read_csv(main.REVIEW_CSV_PATH, keep_default_na=False)
    assert len(review) == expected
    rejected = load_jsonl(main.REJECTED_LINGUISTIC_PATH)
    assert len(rejected) == 1 - expected
    if rejected:
        assert rejected[0]["Densite_darija"] == 0.2
        assert rejected[0]["Decision_linguistique"] == "A_recontroler"


@pytest.mark.parametrize("permission", ["Non", "A_verifier"])
def test_verify_checks_robots_before_using_cached_content(workspace, monkeypatch, permission):
    export_jsonl(candidates(URL), main.CANDIDATES_PATH)
    cache = JsonCache(workspace / "cache/url_checks.json")
    cache.set(URL, {**good_check().__dict__, "collection_policy_version": 1})
    cache.save()
    monkeypatch.setattr(main, "robots_status", lambda *args, **kwargs: permission)
    monkeypatch.setattr(main, "check_url", lambda *args, **kwargs: pytest.fail("No content request permitted"))

    assert main.verify(Namespace(max_links=None, min_darija_density=0, force=False)) == []
    assert load_jsonl(main.BLOCKED_PATH)[0]["reason"] in {"robots_interdit", "robots_a_verifier"}


def test_legacy_cache_is_refetched_through_current_access_policy(workspace, monkeypatch):
    export_jsonl(candidates(URL), main.CANDIDATES_PATH)
    cache = JsonCache(workspace / "cache/url_checks.json")
    cache.set(URL, good_check(text="Legacy content").__dict__)
    cache.save()
    checks = []

    def check(url, **kwargs):
        checks.append(url)
        return good_check(url)

    monkeypatch.setattr(main, "check_url", check)
    records = main.verify(Namespace(max_links=None, min_darija_density=0.2, force=False))

    assert checks == [URL]
    assert records[0]["Texte_extrait"] == TEXT
    assert JsonCache(workspace / "cache/url_checks.json").get(URL)["collection_policy_version"] == 1


def test_cached_redirect_destination_must_still_allow_collection(workspace, monkeypatch):
    target = "https://other.ma/private"
    export_jsonl(candidates(URL), main.CANDIDATES_PATH)
    cache = JsonCache(workspace / "cache/url_checks.json")
    cache.set(URL, {**good_check(target).__dict__, "collection_policy_version": 1})
    cache.save()
    monkeypatch.setattr(main, "robots_status", lambda url, *args, **kwargs: "Non" if url == target else "Oui")
    monkeypatch.setattr(main, "check_url", lambda *args, **kwargs: pytest.fail("Blocked cached destination"))

    assert main.verify(Namespace(max_links=None, min_darija_density=0, force=False)) == []
    assert load_jsonl(main.BLOCKED_PATH) == [{"url": target, "reason": "robots_interdit"}]


def test_verify_drops_excluded_candidate_before_any_request(workspace, monkeypatch):
    export_jsonl(candidates("https://github.com/owner/darija"), main.CANDIDATES_PATH)
    monkeypatch.setattr(main, "robots_status", lambda *args, **kwargs: pytest.fail("Excluded host must not be contacted"))
    monkeypatch.setattr(main, "check_url", lambda *args, **kwargs: pytest.fail("Excluded host must not be contacted"))

    assert main.verify(Namespace(max_links=None, min_darija_density=0, force=False)) == []


def test_existing_empty_candidate_file_does_not_restart_discovery(workspace, monkeypatch):
    export_jsonl([], main.CANDIDATES_PATH)
    monkeypatch.setattr(main, "collect", lambda *args, **kwargs: pytest.fail("Discovery already ran"))

    assert main.verify(Namespace(max_links=None, min_darija_density=0.15, force=False)) == []


def test_pdf_without_text_stays_in_human_review(workspace, monkeypatch):
    pdf_url = "https://example.ma/book.pdf"
    export_jsonl(candidates(pdf_url), main.CANDIDATES_PATH)
    monkeypatch.setattr(main, "check_url", lambda url, **kwargs: UrlCheckResult(
        url, 200, "Accessible", "application/pdf", False, robots_txt="Oui",
    ))

    records = main.verify(Namespace(max_links=None, min_darija_density=1, force=False))

    assert len(records) == 1
    assert records[0]["Type_contenu"] == "PDF"
    assert records[0]["Densite_darija"] is None
    assert records[0]["Decision_linguistique"] == "A_recontroler"
    main.export_outputs(Namespace())
    assert len(pd.read_csv(main.REVIEW_CSV_PATH)) == 1


def test_threshold_is_applied_before_a_single_scoring_pass(workspace, monkeypatch):
    row = candidates(URL)[0]
    row["source_priority"] = "P0"
    export_jsonl([row], main.CANDIDATES_PATH)
    check = good_check()
    baseline = main._base_record(main.candidate_from_dict(row), 1, check.__dict__, {}, {})
    monkeypatch.setattr(main, "check_url", lambda *args, **kwargs: good_check())

    actual = main.verify(Namespace(max_links=None, min_darija_density=0, force=False))[0]

    assert actual["Score_pertinence"] == baseline["Score_pertinence"]
    assert actual["Score_fiabilite"] == baseline["Score_fiabilite"]


def test_html_title_cannot_supply_darija_tokens_to_the_body(workspace, monkeypatch):
    export_jsonl(candidates(URL), main.CANDIDATES_PATH)
    checked = good_check()
    checked.html = (
        "<html><head><title>wach daba bzzaf</title></head>"
        "<body>Annual financial results report strong growth.</body></html>"
    )
    monkeypatch.setattr(main, "check_url", lambda *args, **kwargs: checked)

    assert main.verify(Namespace(max_links=None, min_darija_density=0.15, force=False)) == []
    rejected = load_jsonl(main.REJECTED_LINGUISTIC_PATH)[0]
    assert rejected["Texte_extrait"] == "Annual financial results report strong growth."
    assert rejected["Densite_darija"] == 0
    assert rejected["Titre"] == "wach daba bzzaf"


@pytest.mark.parametrize("url", [
    "", "ftp://example.ma/file", "https:///page", "https://example.ma:bad/page",
    "https://example.ma/a\nb", "https://m.youtube.com:443/watch?v=123",
    "https://github.com./owner/repo", "https://fb.watch/video",
])
def test_manual_acceptance_does_not_bypass_url_policy(tmp_path, url):
    review = tmp_path / "review.csv"
    pd.DataFrame([{"Decision_validation": "accept", "URL_finale": url, "Robots_txt": "Oui"}]).to_csv(review, index=False)

    summary = main.export_crawler_input_from_review(review, tmp_path / "urls.txt", tmp_path / "manifest.jsonl")

    assert summary["accepted_links"] == 0
    assert summary["rejected_links"] == 1
    assert (tmp_path / "urls.txt").read_text() == ""


@pytest.mark.parametrize("permission", ["Non", "A_verifier", "", None])
def test_manual_acceptance_requires_recorded_robots_permission(tmp_path, permission):
    review = tmp_path / "review.csv"
    pd.DataFrame([{"Decision_validation": "accept", "URL_finale": URL, "Robots_txt": permission}]).to_csv(review, index=False)

    summary = main.export_crawler_input_from_review(review, tmp_path / "urls.txt", tmp_path / "manifest.jsonl")

    assert summary["accepted_links"] == 0
    assert summary["rejection_reasons"] == {"robots_non_autorise_ou_inconnu": 1}


def test_accepted_export_preserves_encoded_url_and_recomputes_domain(tmp_path):
    url = "https://example.ma/doc/a%23b?q=art%26culture"
    review = tmp_path / "review.csv"
    pd.DataFrame([{
        "Decision_validation": "accept", "URL_finale": url,
        "Domaine": "stale.ma", "Robots_txt": "Oui",
    }]).to_csv(review, index=False)

    summary = main.export_crawler_input_from_review(review, tmp_path / "urls.txt", tmp_path / "manifest.jsonl")

    assert summary["accepted_links"] == 1
    assert (tmp_path / "urls.txt").read_text().splitlines() == [url]
    assert load_jsonl(tmp_path / "manifest.jsonl")[0]["domain"] == "example.ma"


@pytest.mark.parametrize("threshold", ["-0.1", "1.01", "nan", "inf", "oops"])
def test_cli_rejects_invalid_threshold_before_collection(threshold):
    with pytest.raises(SystemExit):
        main.build_parser().parse_args(["mvp", "--min-darija-density", threshold])


def test_cli_preserves_global_threshold_for_explicit_mvp():
    assert main.build_parser().parse_args(["--min-darija-density", "0.7", "mvp"]).min_darija_density == 0.7
