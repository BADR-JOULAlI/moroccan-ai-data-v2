"""Legacy platform audits must not approve a resource that was not fetched."""

import pytest

from src.audit import url_auditor
from src.audit.url_auditor import AuditConfig, UrlAuditor
from src.validation.url_checker import UrlCheckResult


URL = "https://github.com/morocco/darija-corpus"


@pytest.mark.parametrize("status, robots", [
    ("Robots_interdit", "Non"), ("Robots_a_verifier", "A_verifier"),
    ("Hors_perimetre", "A_verifier"),
])
def test_blocked_platform_is_not_kept_even_when_url_looks_relevant(tmp_path, monkeypatch, status, robots):
    auditor = UrlAuditor(tmp_path / "audit.json", AuditConfig(max_attempts=1, request_delay_seconds=0))
    monkeypatch.setattr(url_auditor, "check_url", lambda *args, **kwargs: UrlCheckResult(
        URL, None, status, "unknown", False, robots_txt=robots,
    ))

    record = auditor.audit({"_input_url": URL})

    assert record["Decision_finale"] == "A_RECONTROLER"
    assert record["Raison_decision"] == status
    assert record["Robots_txt"] == robots


def test_temporary_robots_failure_is_not_cached_for_the_next_audit(tmp_path, monkeypatch):
    auditor = UrlAuditor(tmp_path / "audit.json", AuditConfig(max_attempts=1, request_delay_seconds=0))
    responses = iter([
        UrlCheckResult(URL, None, "Robots_a_verifier", "unknown", False),
        UrlCheckResult(URL, 200, "Accessible", "text/html", False, html="<p>Darija corpus</p>", robots_txt="Oui"),
    ])
    calls = []

    def checked(url, **kwargs):
        assert kwargs["url_policy"] is None  # Explicit diagnostic scope, still subject to robots.
        calls.append(url)
        return next(responses)

    monkeypatch.setattr(url_auditor, "check_url", checked)
    assert auditor.audit({"_input_url": URL})["Decision_finale"] == "A_RECONTROLER"
    assert auditor.audit({"_input_url": URL})["Statut_HTTP"] == 200
    assert calls == [URL, URL]
