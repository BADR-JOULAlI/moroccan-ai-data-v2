"""Startup settings and local preflight need neither models nor network."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1] / "datatrove_extraction"
SPEC = importlib.util.spec_from_file_location("_runtime_config_tests", ROOT / "runtime_config.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
load_config = MODULE.load_config


@pytest.fixture(autouse=True)
def no_legacy_segment(monkeypatch):
    monkeypatch.delenv("SEGMENT_TO_PROCESS", raising=False)


def config_file(tmp_path, values):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def make_ready(config):
    archive = config.input_dir / "website" / "pages.warc.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"fixture presence only")
    files = [config.tokenizer_path]
    if config.mode == "full":
        files.extend([config.pdf_classifier_path, config.layout_model_path, config.layout_model_path.with_suffix(".bin")])
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture presence only")


def test_defaults_resolve_without_creating_any_files(tmp_path):
    root = tmp_path / "extract"
    config = load_config(project_root=root)

    assert config.segment == "segment-2026-01"
    assert config.mode == "full"
    assert config.word_tokenizer == "spacy"
    assert config.input_dir == root / "input" / config.segment
    assert config.output_dir == root / "output" / config.segment
    assert config.model_cache == tmp_path / "models_cache"
    assert config.tokenizer_path == config.model_cache / "aragpt2_base_tokenizer/tokenizer.json"
    assert config.ocr_model is config.ocr_endpoint is None
    assert (config.workers_io, config.workers_cpu, config.workers_heavy) == (8, 6, 4)
    assert list(tmp_path.iterdir()) == []


def test_environment_only_supplies_segment_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SEGMENT_TO_PROCESS", "segment-env")
    assert load_config(project_root=tmp_path).segment == "segment-env"
    path = config_file(tmp_path, {"segment": "segment-file"})
    assert load_config(path, project_root=tmp_path).segment == "segment-file"
    config = load_config(path, {"segment": "segment-cli"}, project_root=tmp_path)
    assert config.segment == "segment-cli"
    assert config.input_dir == tmp_path / "input/segment-cli"


def test_json_paths_use_config_directory_and_overrides_use_cwd(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    cwd = tmp_path / "command"
    cwd.mkdir()
    path = config_file(config_dir, {
        "input_dir": "archives", "output_dir": "results", "model_cache": "assets",
        "tokenizer_path": "vocab/tokenizer.json",
    })
    monkeypatch.chdir(cwd)

    config = load_config(path, {"output_dir": "cli-results"}, project_root=tmp_path / "project")

    assert config.input_dir == config_dir / "archives"
    assert config.output_dir == cwd / "cli-results"
    assert config.model_cache == config_dir / "assets"
    assert config.tokenizer_path == config_dir / "vocab/tokenizer.json"
    assert config.pdf_classifier_path == config_dir / "assets/xgb_ocr_classifier/xgb_classifier.ubj"


def test_cache_override_updates_only_derived_resource_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = config_file(tmp_path, {"model_cache": "original", "tokenizer_path": "explicit-tokenizer.json"})

    config = load_config(path, {"model_cache": "new-cache"}, project_root=tmp_path)

    assert config.model_cache == tmp_path / "new-cache"
    assert config.tokenizer_path == tmp_path / "explicit-tokenizer.json"
    assert config.layout_model_path == tmp_path / "new-cache/heron/heron_int8_quant.xml"


@pytest.mark.parametrize("segment", ["../other", "a/b", r"a\b", ".", "..", "a.", "CON", "nul.txt", "", 12])
def test_unsafe_segments_are_rejected(tmp_path, segment):
    with pytest.raises(ValueError, match="segment"):
        load_config(overrides={"segment": segment}, project_root=tmp_path)


@pytest.mark.parametrize("name", ["workers_io", "workers_cpu", "workers_heavy"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_workers_must_be_positive_integers(tmp_path, name, value):
    with pytest.raises(ValueError, match=name):
        load_config(overrides={name: value}, project_root=tmp_path)


@pytest.mark.parametrize("endpoint", [
    "", "localhost:9996", "ftp://host/", "https:///path", "http://user:password@host/",
    "http://host:bad/", "http://host:65536/", "http://host:", "http://host/#fragment",
    "http://bad host/", "http://host/\npath", r"http://host\other/path",
])
def test_invalid_endpoints_are_rejected(tmp_path, endpoint):
    with pytest.raises(ValueError, match="ocr_endpoint"):
        load_config(overrides={"ocr_endpoint": endpoint}, project_root=tmp_path)


@pytest.mark.parametrize("endpoint", ["http://localhost:9996/", "https://ocr.example.test/v1", "http://[::1]:8080/v1"])
def test_endpoint_can_be_local_or_remote_without_a_probe(tmp_path, endpoint):
    config = load_config(overrides={"ocr_endpoint": endpoint}, project_root=tmp_path)
    assert config.ocr_endpoint == endpoint
    assert not tmp_path.joinpath("output").exists()


def test_unknown_fields_do_not_silently_hide_typos(tmp_path):
    path = config_file(tmp_path, {"worker_io": 2})
    with pytest.raises(ValueError, match="worker_io"):
        load_config(path, project_root=tmp_path)
    with pytest.raises(ValueError, match="unknown"):
        load_config(overrides={"unknown": 1}, project_root=tmp_path)


@pytest.mark.parametrize("payload", ["[]", "null", "{broken"])
def test_bad_json_reports_a_readable_error(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(payload)
    with pytest.raises(ValueError, match="JSON"):
        load_config(path, project_root=tmp_path)


def test_full_preflight_reports_all_missing_resources_at_once(tmp_path):
    config = load_config(project_root=tmp_path / "extract")

    errors = config.check_prerequisites()

    assert len(errors) == 8
    assert any("Dossier d'entree" in error for error in errors)
    assert any("Tokenizer" in error for error in errors)
    assert any("Classifieur" in error for error in errors)
    assert any("XML" in error for error in errors)
    assert any("BIN" in error for error in errors)
    assert any("artefacts Docling" in error for error in errors)
    assert any("ocr_model" in error for error in errors)
    assert any("ocr_endpoint" in error for error in errors)
    assert not config.output_dir.exists()


def test_html_preflight_requires_only_archives_and_tokenizer(tmp_path):
    config = load_config(overrides={"mode": "html"}, project_root=tmp_path / "extract")
    make_ready(config)

    assert config.check_prerequisites() == []
    assert config.ocr_model is config.ocr_endpoint is None
    assert not config.output_dir.exists()


def test_full_preflight_accepts_configured_resources_without_model_loading(tmp_path):
    config = load_config(overrides={
        "ocr_model": "model-served-by-the-endpoint", "ocr_endpoint": "http://localhost:9996/v1",
    }, project_root=tmp_path / "extract")
    make_ready(config)

    assert config.check_prerequisites() == []
    assert not config.output_dir.exists()


def test_full_requires_artifacts_directory_even_with_resource_overrides(tmp_path):
    resources = tmp_path / "separate-resources"
    config = load_config(overrides={
        "model_cache": tmp_path / "missing-docling-artifacts",
        "tokenizer_path": resources / "tokenizer.json",
        "pdf_classifier_path": resources / "classifier.ubj",
        "layout_model_path": resources / "layout.xml",
        "ocr_model": "served-model",
        "ocr_endpoint": "http://localhost:9996/v1",
    }, project_root=tmp_path / "extract")
    make_ready(config)

    errors = config.check_prerequisites()

    assert len(errors) == 1
    assert "Dossier artefacts Docling" in errors[0]
    assert not config.model_cache.exists()


def test_archive_layout_must_match_the_production_reader(tmp_path):
    config = load_config(overrides={"mode": "html"}, project_root=tmp_path / "extract")
    config.input_dir.mkdir(parents=True)
    (config.input_dir / "direct.warc.gz").write_bytes(b"not in a website directory")

    assert any("*/*.warc.gz" in error for error in config.check_prerequisites())


def test_config_report_is_json_serializable(tmp_path):
    config = load_config(overrides={"mode": "html"}, project_root=tmp_path)
    report = json.loads(json.dumps(config.to_dict()))
    assert report["input_dir"] == str(config.input_dir)
    assert report["mode"] == "html"


@pytest.mark.parametrize("value", ["other", "", None, 0, [], {}])
def test_word_tokenizer_choice_must_be_explicit_and_supported(tmp_path, value):
    with pytest.raises(ValueError, match="word_tokenizer"):
        load_config(overrides={"word_tokenizer": value}, project_root=tmp_path)


def test_unicode_profile_is_an_explicit_local_validation_setting(tmp_path):
    config = load_config(overrides={"word_tokenizer": "unicode", "mode": "html"}, project_root=tmp_path)

    assert config.word_tokenizer == "unicode"
    assert config.to_dict()["word_tokenizer"] == "unicode"


def test_example_uses_lightweight_profile_without_changing_the_default():
    example = load_config(ROOT / "extraction.example.json")

    assert example.mode == "html"
    assert example.word_tokenizer == "unicode"
    assert load_config().word_tokenizer == "spacy"


def test_import_with_stdlib_only_has_no_io_or_heavy_dependencies(tmp_path):
    command = (
        "import importlib.util, pathlib, sys; "
        f"spec=importlib.util.spec_from_file_location('runtime_config', {str(ROOT / 'runtime_config.py')!r}); "
        "module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module); "
        "assert not any(name in sys.modules for name in ['datatrove','torch','pymupdf','xgboost']); "
        "assert not list(pathlib.Path('.').iterdir())"
    )
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", command], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
