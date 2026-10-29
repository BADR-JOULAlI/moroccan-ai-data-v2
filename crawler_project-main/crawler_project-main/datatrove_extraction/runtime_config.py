"""Resolve extraction settings without loading models or creating directories.

Precedence is defaults, a JSON file, then explicit overrides. The legacy
SEGMENT_TO_PROCESS environment variable supplies only the default segment.
Paths in JSON are relative to that JSON file; override paths are relative to
the current working directory. No other environment settings are implicit.
The explicit ``unicode`` word-tokenizer profile permits lightweight local
validation; ``spacy`` remains the default for compatibility with existing runs.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit


_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
_PATH_FIELDS = (
    "input_dir", "output_dir", "model_cache", "tokenizer_path",
    "pdf_classifier_path", "layout_model_path",
)


def _endpoint_error(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\\" in value or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        return "ocr_endpoint doit etre une URL HTTP(S) sans espaces ni caracteres de controle."
    try:
        parsed = urlsplit(value)
        parsed.port  # Validate malformed and out-of-range ports.
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.netloc.endswith(":")
        ):
            raise ValueError
    except ValueError:
        return "ocr_endpoint doit etre une URL HTTP(S) absolue sans identifiants ni fragment."
    return None


@dataclass(frozen=True)
class ExtractionConfig:
    segment: str
    mode: str
    input_dir: Path
    output_dir: Path
    model_cache: Path
    tokenizer_path: Path
    pdf_classifier_path: Path
    layout_model_path: Path
    ocr_model: str | None = None
    ocr_endpoint: str | None = None
    word_tokenizer: str = "spacy"
    workers_io: int = 8
    workers_cpu: int = 6
    workers_heavy: int = 4

    def __post_init__(self) -> None:
        errors = []
        if (
            not isinstance(self.segment, str)
            or not _SEGMENT.fullmatch(self.segment)
            or self.segment.endswith(".")
            or self.segment.split(".", 1)[0].upper() in _WINDOWS_RESERVED
        ):
            errors.append("segment doit etre un nom simple, sans separateur de chemin ni traversal.")
        if not isinstance(self.mode, str) or self.mode not in {"full", "html"}:
            errors.append("mode doit etre 'full' ou 'html'.")
        if not isinstance(self.word_tokenizer, str) or self.word_tokenizer not in {"spacy", "unicode"}:
            errors.append("word_tokenizer doit etre 'spacy' ou 'unicode'.")
        for name in ("workers_io", "workers_cpu", "workers_heavy"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                errors.append(f"{name} doit etre un entier strictement positif.")
        if self.ocr_model is not None and (
            not isinstance(self.ocr_model, str)
            or not self.ocr_model.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in self.ocr_model)
        ):
            errors.append("ocr_model doit etre un nom de modele non vide ou null.")
        endpoint_error = _endpoint_error(self.ocr_endpoint)
        if endpoint_error:
            errors.append(endpoint_error)
        for name in _PATH_FIELDS:
            if not isinstance(getattr(self, name), Path):
                errors.append(f"{name} doit etre un Path resolu par load_config().")
        if errors:
            raise ValueError("Configuration d'extraction invalide:\n- " + "\n- ".join(errors))

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible settings, suitable for a startup report."""
        return {
            item.name: str(value) if isinstance(value := getattr(self, item.name), Path) else value
            for item in fields(self)
        }

    def check_prerequisites(self) -> list[str]:
        """Collect missing local resources without writes or network probes.

        Presence checks do not validate model contents or contact the OCR
        endpoint. WARC integrity and model loading are separate runtime checks.
        """
        errors: list[str] = []
        try:
            output_parent = self.output_dir
            while not output_parent.exists() and output_parent != output_parent.parent:
                output_parent = output_parent.parent
            if output_parent.exists() and not output_parent.is_dir():
                errors.append(f"Output path or parent is a file, not a directory: {output_parent}")
        except OSError as exc:
            errors.append(f"Output path inaccessible: {self.output_dir} ({exc.__class__.__name__})")
        try:
            if not self.input_dir.is_dir():
                errors.append(f"Dossier d'entree introuvable: {self.input_dir}")
            elif not any(path.is_file() for path in self.input_dir.glob("*/*.warc.gz")):
                errors.append(f"Aucune archive */*.warc.gz dans: {self.input_dir}")
        except OSError as exc:
            errors.append(f"Dossier d'entree illisible: {self.input_dir} ({exc.__class__.__name__})")

        required_files = [("Tokenizer local", self.tokenizer_path)]
        if self.mode == "full":
            try:
                if not self.model_cache.is_dir():
                    errors.append(f"Dossier artefacts Docling introuvable: {self.model_cache}")
            except OSError as exc:
                errors.append(f"Dossier artefacts Docling inaccessible: {self.model_cache} ({exc.__class__.__name__})")
            required_files.extend([
                ("Classifieur PDF", self.pdf_classifier_path),
                ("Modele OpenVINO XML", self.layout_model_path),
                ("Poids OpenVINO BIN", self.layout_model_path.with_suffix(".bin")),
            ])
            if self.ocr_model is None:
                errors.append("ocr_model doit etre configure pour le mode full.")
            if self.ocr_endpoint is None:
                errors.append("ocr_endpoint doit etre configure pour le mode full.")
        for label, path in required_files:
            try:
                if not path.is_file():
                    errors.append(f"{label} introuvable: {path}")
            except OSError as exc:
                errors.append(f"{label} inaccessible: {path} ({exc.__class__.__name__})")
        return errors


def _resolve_path(value: Any, base: Path, field_name: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip() or "\x00" in str(value):
        raise ValueError(f"{field_name} doit etre un chemin non vide.")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def load_config(
    config_path: str | os.PathLike | None = None,
    overrides: Mapping[str, Any] | None = None,
    *,
    project_root: str | os.PathLike | None = None,
) -> ExtractionConfig:
    """Load and resolve configuration, with no output or model initialization."""
    root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parent
    cwd = Path.cwd()
    settings: dict[str, Any] = {"segment": os.environ.get("SEGMENT_TO_PROCESS", "segment-2026-01"), "mode": "full"}
    origins: dict[str, Path] = {}
    known_fields = {item.name for item in fields(ExtractionConfig)}

    def apply(values: Mapping[str, Any], base: Path, source: str) -> None:
        unknown = set(values) - known_fields
        if unknown:
            raise ValueError(f"Champs inconnus dans {source}: {', '.join(sorted(unknown))}")
        settings.update(values)
        origins.update({name: base for name in values})

    if config_path is not None:
        path = _resolve_path(config_path, cwd, "config_path")
        try:
            values = json.loads(path.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise ValueError(f"Configuration illisible: {path} ({exc.__class__.__name__})") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Configuration JSON invalide: {path} (ligne {exc.lineno}, colonne {exc.colno})") from exc
        if not isinstance(values, dict):
            raise ValueError("La configuration JSON doit etre un objet.")
        apply(values, path.parent, "la configuration JSON")
    if overrides is not None:
        if not isinstance(overrides, Mapping):
            raise ValueError("overrides doit etre un dictionnaire de parametres.")
        apply(overrides, cwd, "les overrides")

    # Resolve explicit paths using their own origin; derive unspecified paths
    # from the final segment/cache so a later override cannot leave stale defaults.
    segment = settings["segment"]
    if not isinstance(segment, str) or not _SEGMENT.fullmatch(segment):
        raise ValueError("segment doit etre un nom simple, sans separateur de chemin ni traversal.")
    defaults = {
        "input_dir": root / "input" / segment,
        "output_dir": root / "output" / segment,
        "model_cache": root.parent / "models_cache",
    }
    resolved = {
        name: _resolve_path(settings[name], origins[name], name) if name in settings else default.resolve()
        for name, default in defaults.items()
    }
    cache = resolved["model_cache"]
    resource_defaults = {
        "tokenizer_path": cache / "aragpt2_base_tokenizer" / "tokenizer.json",
        "pdf_classifier_path": cache / "xgb_ocr_classifier" / "xgb_classifier.ubj",
        "layout_model_path": cache / "heron" / "heron_int8_quant.xml",
    }
    resolved.update({
        name: _resolve_path(settings[name], origins[name], name) if name in settings else default.resolve()
        for name, default in resource_defaults.items()
    })
    return ExtractionConfig(**{**settings, **resolved})
