"""Startup checks must precede model imports, output writes and server access."""

import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def entry(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from datatrove_extraction import process
    return process


def ready_html_config(tmp_path):
    from datatrove_extraction.runtime_config import load_config

    archive = tmp_path / "input/test/site/pages.warc.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"presence-check-only")
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text("{}", encoding="utf-8")
    return load_config(overrides={
        "mode": "html", "segment": "test", "word_tokenizer": "unicode",
        "tokenizer_path": tokenizer,
    }, project_root=tmp_path)


def test_script_help_needs_no_site_packages_or_models(tmp_path):
    result = subprocess.run(
        [sys.executable, "-S", "-B", str(ROOT / "datatrove_extraction/process.py"), "--help"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "--check-only" in result.stdout
    assert "--word-tokenizer" in result.stdout
    assert not list(tmp_path.iterdir())


def test_package_import_is_lazy_with_stdlib_only(tmp_path):
    code = (
        f"import sys; sys.path.insert(0,{str(ROOT)!r}); "
        "import datatrove_extraction.process; "
        "assert not any(x in sys.modules for x in ['datatrove','torch','pymupdf','xgboost','transformers'])"
    )
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_check_only_reports_all_missing_resources_without_running(entry, tmp_path, monkeypatch, capsys):
    from datatrove_extraction.runtime_config import load_config

    config = load_config(project_root=tmp_path)
    monkeypatch.setattr(entry, "load_config", lambda *args: config)
    monkeypatch.setattr(entry, "missing_dependencies", lambda *args: ["missing dependency fixture"])
    monkeypatch.setattr(entry, "_run_pipeline", lambda *args: pytest.fail("Preflight must not run models"))

    assert entry.main(["--check-only"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False
    assert report["server_contacted"] is False
    assert len(report["errors"]) >= 7
    assert not config.output_dir.exists()


def test_ready_html_preflight_has_no_pdf_or_server_requirement(entry, tmp_path, monkeypatch, capsys):
    config = ready_html_config(tmp_path)
    monkeypatch.setattr(entry, "load_config", lambda *args: config)
    monkeypatch.setattr(entry, "missing_dependencies", lambda *args: [])
    monkeypatch.setattr(entry, "_run_pipeline", lambda *args: pytest.fail("Check-only must not extract"))

    assert entry.main(["--check-only"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is True
    assert report["configuration"]["ocr_endpoint"] is None
    assert not config.output_dir.exists()


def test_nonempty_untracked_output_is_rejected_without_overwrite(entry, tmp_path, monkeypatch, capsys):
    config = ready_html_config(tmp_path)
    config.output_dir.mkdir(parents=True)
    kept = config.output_dir / "keep.txt"
    kept.write_text("existing dataset", encoding="utf-8")
    monkeypatch.setattr(entry, "load_config", lambda *args: config)
    monkeypatch.setattr(entry, "missing_dependencies", lambda *args: [])

    assert entry.main(["--check-only"]) == 2
    assert "different or untracked run" in capsys.readouterr().out
    assert kept.read_text(encoding="utf-8") == "existing dataset"
    assert not (config.output_dir / "run_config.json").exists()


@pytest.mark.parametrize("nested", [False, True])
def test_output_file_or_file_parent_fails_preflight(entry, tmp_path, monkeypatch, capsys, nested):
    config = ready_html_config(tmp_path)
    blocked = tmp_path / "blocked"
    blocked.write_text("keep", encoding="utf-8")
    config = replace(config, output_dir=blocked / "child" if nested else blocked)
    monkeypatch.setattr(entry, "load_config", lambda *args: config)
    monkeypatch.setattr(entry, "missing_dependencies", lambda *args: [])

    assert entry.main(["--check-only"]) == 2
    assert "not a directory" in capsys.readouterr().out
    assert blocked.read_text(encoding="utf-8") == "keep"


def test_auto_repair_requires_explicit_validation(entry, tmp_path, monkeypatch):
    monkeypatch.setattr(entry, "load_config", lambda *args: pytest.fail("Invalid flags must stop before configuration"))
    with pytest.raises(SystemExit) as error:
        entry.main(["--auto-repair"])
    assert error.value.code == 2


def test_corrupt_warc_is_rejected_without_prompt_or_output(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from datatrove_extraction.helpers.extra_helpers.validateInputs import validate_inputs

    archive = tmp_path / "input/site/corrupt.warc.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"not a WARC or gzip archive")
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("Validation must not prompt"))
    with pytest.raises(ValueError, match="WARC validation failed"):
        validate_inputs(validate_warc=True, input_dir=archive.parent.parent)
    assert archive.read_bytes() == b"not a WARC or gzip archive"
    assert not (tmp_path / "output").exists()


def test_full_mode_can_build_initial_router_before_pdf_model_imports(entry, tmp_path, monkeypatch):
    from datatrove_extraction.runtime_config import load_config
    import datatrove.executor

    config = load_config(overrides={"word_tokenizer": "unicode"}, project_root=tmp_path)
    config.input_dir.mkdir(parents=True)

    class RouterReady(Exception):
        pass

    def inspect_router(**kwargs):
        assert len(kwargs["pipeline"]) == 3  # Reader, HTML router, PDF router.
        assert kwargs["start_method"] == "spawn"
        raise RouterReady

    monkeypatch.setattr(datatrove.executor, "LocalPipelineExecutor", inspect_router)
    with pytest.raises(RouterReady):
        entry._run_pipeline(config)


def test_unicode_word_profile_preserves_arabic_latin_and_sentence_boundaries(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "datatrove_extraction"))
    from helpers.pipeline_utils.word_tokenizer import UnicodeWordTokenizer

    tokenizer = UnicodeWordTokenizer()
    text = "سلام، كيف الحال؟ All good."
    assert tokenizer.word_tokenize(text) == ["سلام", "،", "كيف", "الحال", "؟", "All", "good", "."]
    assert tokenizer.sent_tokenize(text) == ["سلام، كيف الحال؟", "All good."]
    assert "".join(text[start:end] for start, end in tokenizer.span_tokenize(text)) == text
