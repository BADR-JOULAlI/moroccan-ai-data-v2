from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.utils.text_utils import arabic_ratio, latin_ratio, normalize_arabic_text, normalize_latin_text

TOKEN_RE = re.compile(r"[\w\u0600-\u06ff']+", re.I)
ARABIC_TOKEN_RE = re.compile(r"[\u0600-\u06ff]+")
LATIN_TOKEN_RE = re.compile(r"[a-zA-Z0-9']*[a-zA-Z][a-zA-Z0-9']*")
URL_RE = re.compile(r"https?://|www\.", re.I)
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
TECH_TOKEN_RE = re.compile(r"^(?:python|html|http|utf|ipv|sha|version|dataset|page|api)\d+$", re.I)
ARABIZI_DIGITS = set("235789")

DEFAULT_THRESHOLDS = {
    "keep_threshold": 65,
    "review_threshold": 40,
    "weak_signal_threshold": 20,
    "minimum_strong_hits": 2,
    "max_frequency_bonus": 15,
    "max_context_bonus": 10,
    "max_arabizi_bonus": 10,
}


@dataclass(frozen=True)
class Lexicon:
    version: str
    arabic_weights: dict[str, float]
    latin_weights: dict[str, float]
    arabic_strength: dict[str, str]
    latin_strength: dict[str, str]
    arabic_phrases: dict[str, float]
    latin_phrases: dict[str, float]
    variants: dict[str, str]
    arabic_variants: dict[str, str]
    moroccan_context_arabic: set[str]
    moroccan_context_latin: set[str]
    negative_arabic: set[str]
    negative_latin: set[str]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _validate_weight_map(section: dict[str, Any], name: str) -> None:
    for level in ("strong", "medium", "weak"):
        if level not in section or not isinstance(section[level], dict):
            raise ValueError(f"darija_lexicon.yaml: section {name}.{level} is required")
        for token, weight in section[level].items():
            if not str(token).strip():
                raise ValueError(f"darija_lexicon.yaml: empty token in {name}.{level}")
            if not isinstance(weight, (int, float)):
                raise ValueError(f"darija_lexicon.yaml: weight for {token!r} must be numeric")


def _flatten_weights(section: dict[str, dict[str, float]], normalizer) -> tuple[dict[str, float], dict[str, str]]:
    weights: dict[str, float] = {}
    strengths: dict[str, str] = {}
    for level in ("strong", "medium", "weak"):
        for token, weight in section.get(level, {}).items():
            norm = normalizer(str(token))
            if norm in weights and weights[norm] != float(weight):
                raise ValueError(f"darija_lexicon.yaml: conflicting duplicate token {token!r}")
            weights[norm] = float(weight)
            strengths[norm] = level
    return weights, strengths


@lru_cache(maxsize=1)
def load_lexicon() -> Lexicon:
    path = _project_root() / "config" / "darija_lexicon.yaml"
    data = _load_yaml(path)
    if not data.get("version"):
        raise ValueError("darija_lexicon.yaml: version is required")
    for section in ("arabic", "latin"):
        _validate_weight_map(data.get(section, {}), section)
    arabic_weights, arabic_strength = _flatten_weights(data["arabic"], normalize_arabic_text)
    latin_weights, latin_strength = _flatten_weights(data["latin"], normalize_latin_text)
    phrases = data.get("phrases", {})
    arabic_phrases = {normalize_arabic_text(k): float(v) for k, v in phrases.get("arabic", {}).items()}
    latin_phrases = {normalize_latin_text(k): float(v) for k, v in phrases.get("latin", {}).items()}
    variants = {normalize_latin_text(k): normalize_latin_text(v) for k, v in (data.get("variants") or {}).items()}
    arabic_variants = {normalize_arabic_text(k): normalize_arabic_text(v) for k, v in (data.get("arabic_variants") or {}).items()}
    context = data.get("moroccan_context", {})
    negative = data.get("negative_or_ambiguous", {})
    return Lexicon(
        version=str(data["version"]),
        arabic_weights=arabic_weights,
        latin_weights=latin_weights,
        arabic_strength=arabic_strength,
        latin_strength=latin_strength,
        arabic_phrases=arabic_phrases,
        latin_phrases=latin_phrases,
        variants=variants,
        arabic_variants=arabic_variants,
        moroccan_context_arabic={normalize_arabic_text(x) for x in context.get("arabic", []) if str(x).strip()},
        moroccan_context_latin={normalize_latin_text(x) for x in context.get("latin", []) if str(x).strip()},
        negative_arabic={normalize_arabic_text(x) for x in negative.get("arabic", []) if str(x).strip()},
        negative_latin={normalize_latin_text(x) for x in negative.get("latin", []) if str(x).strip()},
    )


@lru_cache(maxsize=1)
def load_thresholds() -> dict[str, float]:
    settings_path = _project_root() / "config" / "settings.yaml"
    settings = _load_yaml(settings_path) if settings_path.exists() else {}
    values = {**DEFAULT_THRESHOLDS, **(settings.get("darija_detection") or {})}
    if values["weak_signal_threshold"] > values["review_threshold"] or values["review_threshold"] > values["keep_threshold"]:
        raise ValueError("settings.yaml: darija_detection thresholds must be weak <= review <= keep")
    return values


def _canonical_latin(token: str, lexicon: Lexicon) -> str:
    norm = normalize_latin_text(token)
    return lexicon.variants.get(norm, norm)


def _canonical_arabic(token: str, lexicon: Lexicon) -> str:
    norm = normalize_arabic_text(token)
    return lexicon.arabic_variants.get(norm, norm)


def _is_plausible_arabizi(token: str, lexicon: Lexicon) -> bool:
    t = normalize_latin_text(token)
    if not t or URL_RE.search(t) or YEAR_RE.match(t) or t.isdigit() or TECH_TOKEN_RE.match(t):
        return False
    if len(t) < 3 or len(t) > 24:
        return False
    if not any(ch.isalpha() for ch in t) or not any(ch in ARABIZI_DIGITS for ch in t):
        return False
    if t in {"sha256", "utf8", "ipv4", "http2", "html5"}:
        return False
    canonical = _canonical_latin(t, lexicon)
    if canonical in lexicon.latin_weights:
        return True
    plausible_fragments = ("3l", "3a", "7n", "7a", "b7", "9l", "9a", "5o", "se7", "wa9", "fo9")
    return any(fragment in t for fragment in plausible_fragments)


def detect_arabizi_tokens(text: str) -> list[str]:
    lexicon = load_lexicon()
    normalized = normalize_latin_text(text or "")
    tokens = LATIN_TOKEN_RE.findall(normalized)
    return sorted(dict.fromkeys(t for t in tokens if _is_plausible_arabizi(t, lexicon)))


class DarijaDetector:
    def __init__(self, lexicon: Lexicon | None = None, thresholds: dict[str, float] | None = None):
        self.lexicon = lexicon or load_lexicon()
        self.thresholds = thresholds or load_thresholds()

    def detect(self, text: str | None) -> dict:
        original = text or ""
        normalized_arabic = normalize_arabic_text(original)
        normalized_latin = normalize_latin_text(original)
        arabic_tokens = ARABIC_TOKEN_RE.findall(normalized_arabic)
        latin_tokens = LATIN_TOKEN_RE.findall(normalized_latin)
        arabic_counter = Counter(_canonical_arabic(t, self.lexicon) for t in arabic_tokens)
        latin_counter = Counter(_canonical_latin(t, self.lexicon) for t in latin_tokens)
        arabic_hits = self._weighted_hits(arabic_counter, self.lexicon.arabic_weights, self.lexicon.arabic_strength)
        latin_hits = self._weighted_hits(latin_counter, self.lexicon.latin_weights, self.lexicon.latin_strength)
        phrase_hits = self._phrase_hits(normalized_arabic, normalized_latin)
        arabizi_tokens = detect_arabizi_tokens(original)
        context_hits = self._context_hits(normalized_arabic, normalized_latin)
        negative_hits = self._negative_hits(normalized_arabic, normalized_latin)

        lexical_score = self._lexical_score(arabic_hits + latin_hits)
        phrase_score = min(45.0, sum(weight for _, weight in phrase_hits) * 6.0)
        density_score = self._density_score(len(arabic_hits) + len(latin_hits), len(arabic_tokens) + len(latin_tokens))
        arabizi_score = min(float(self.thresholds["max_arabizi_bonus"]), self._arabizi_score(arabizi_tokens))
        context_score = min(float(self.thresholds["max_context_bonus"]), len(context_hits) * 2.0)
        ambiguity_penalty = min(25.0, len(negative_hits) * 3.0 + self._technical_penalty(latin_tokens))
        score = max(0.0, min(100.0, lexical_score + phrase_score + density_score + arabizi_score + context_score - ambiguity_penalty))
        if phrase_hits and max(weight for _, weight in phrase_hits) >= 6.0:
            score = max(score, float(self.thresholds["keep_threshold"]))

        strong_hits = {hit["canonical"] for hit in arabic_hits + latin_hits if hit["strength"] == "strong"}
        medium_hits = {hit["canonical"] for hit in arabic_hits + latin_hits if hit["strength"] == "medium"}
        weak_only = bool(arabic_hits or latin_hits) and not strong_hits and not medium_hits and not phrase_hits
        if weak_only:
            score = min(score, float(self.thresholds["weak_signal_threshold"]) - 1)

        lang = self._language_label(score, arabic_hits, latin_hits, phrase_hits, arabizi_tokens, context_hits, original)
        decision, confidence, reasons, review = self._decision(score, lang, weak_only, arabizi_tokens, arabic_tokens, latin_tokens, context_hits)
        detected_words = self._format_limited([hit["found"] for hit in arabic_hits + latin_hits] + arabizi_tokens, 30)
        canonical_words = self._format_limited([hit["canonical"] for hit in arabic_hits + latin_hits], 30)
        return {
            "Pourcentage_script_arabe": arabic_ratio(original),
            "Pourcentage_script_latin": latin_ratio(original),
            "Score_darija": int(round(score)),
            "Score_lexical": round(lexical_score, 2),
            "Score_expressions": round(phrase_score, 2),
            "Score_contexte_marocain": round(context_score, 2),
            "Penalite_ambiguite": round(ambiguity_penalty, 2),
            "Confiance_darija": confidence,
            "Mots_darija_detectes": detected_words,
            "Mots_darija_canoniques": canonical_words,
            "Expressions_darija_detectees": self._format_limited([phrase for phrase, _ in phrase_hits], 10),
            "Arabizi_detecte": "Oui" if arabizi_tokens else "Non",
            "Tokens_arabizi_detectes": self._format_limited(arabizi_tokens, 10),
            "Indices_contexte_marocain": self._format_limited(context_hits, 10),
            "Langue_principale": lang,
            "Decision_linguistique": decision,
            "Raisons_detection": "; ".join(reasons[:8]),
            "Raisons_recontrole": "; ".join(review[:8]),
            "Version_lexique": self.lexicon.version,
        }

    def _weighted_hits(self, counter: Counter[str], weights: dict[str, float], strengths: dict[str, str]) -> list[dict[str, Any]]:
        hits = []
        for canonical, count in counter.items():
            if canonical not in weights:
                continue
            hits.append({
                "found": canonical,
                "canonical": canonical,
                "count": count,
                "weight": weights[canonical],
                "strength": strengths[canonical],
            })
        return hits

    def _phrase_hits(self, arabic_text: str, latin_text: str) -> list[tuple[str, float]]:
        hits: list[tuple[str, float]] = []
        padded_ar = " " + " ".join(ARABIC_TOKEN_RE.findall(arabic_text)) + " "
        padded_lat = " " + " ".join(LATIN_TOKEN_RE.findall(latin_text)) + " "
        for phrase, weight in self.lexicon.arabic_phrases.items():
            if 2 <= len(phrase.split()) <= 5 and f" {phrase} " in padded_ar:
                hits.append((phrase, weight))
        for phrase, weight in self.lexicon.latin_phrases.items():
            if 2 <= len(phrase.split()) <= 5 and f" {phrase} " in padded_lat:
                hits.append((phrase, weight))
        return hits

    def _context_hits(self, arabic_text: str, latin_text: str) -> list[str]:
        hits = []
        for token in self.lexicon.moroccan_context_arabic:
            if token and token in arabic_text:
                hits.append(token)
        latin_words = set(LATIN_TOKEN_RE.findall(latin_text))
        for token in self.lexicon.moroccan_context_latin:
            if token in latin_words:
                hits.append(token)
        return sorted(dict.fromkeys(hits))

    def _negative_hits(self, arabic_text: str, latin_text: str) -> list[str]:
        hits = []
        for token in self.lexicon.negative_arabic:
            if token and token in arabic_text:
                hits.append(token)
        latin_words = set(LATIN_TOKEN_RE.findall(latin_text))
        for token in self.lexicon.negative_latin:
            if token in latin_words:
                hits.append(token)
        return sorted(dict.fromkeys(hits))

    def _lexical_score(self, hits: list[dict[str, Any]]) -> float:
        if not hits:
            return 0.0
        distinct = sum(hit["weight"] * 5.0 for hit in hits)
        frequency_bonus = 0.0
        for hit in hits:
            frequency_bonus += min(max(hit["count"] - 1, 0), 3) * hit["weight"]
        return min(55.0, distinct + min(float(self.thresholds["max_frequency_bonus"]), frequency_bonus))

    def _density_score(self, hit_count: int, token_count: int) -> float:
        if token_count == 0 or hit_count == 0:
            return 0.0
        density = hit_count / max(token_count, 1)
        return min(15.0, density * 100)

    def _arabizi_score(self, tokens: list[str]) -> float:
        score = 0.0
        for token in tokens:
            canonical = _canonical_latin(token, self.lexicon)
            score += 4.0 if canonical in self.lexicon.latin_weights else 1.5
        return score

    def _technical_penalty(self, tokens: list[str]) -> float:
        return sum(2.0 for token in tokens if TECH_TOKEN_RE.match(token) or YEAR_RE.match(token) or token.isdigit())

    def _language_label(self, score: float, arabic_hits, latin_hits, phrase_hits, arabizi_tokens, context_hits, original: str) -> str:
        ar_ratio = arabic_ratio(original)
        lat_ratio = latin_ratio(original)
        review = float(self.thresholds["review_threshold"])
        if score >= review and arabic_hits and latin_hits:
            return "arabe_darija_mixte"
        if score >= review and phrase_hits:
            has_arabic_phrase = any(ARABIC_TOKEN_RE.search(phrase) for phrase, _ in phrase_hits)
            has_latin_phrase = any(LATIN_TOKEN_RE.search(phrase) for phrase, _ in phrase_hits)
            if has_arabic_phrase and has_latin_phrase:
                return "arabe_darija_mixte"
            if has_arabic_phrase:
                return "darija_arabe"
            if has_latin_phrase:
                return "darija_latine"
        if score >= review and arabizi_tokens and latin_hits:
            return "darija_arabizi"
        if score >= review and arabic_hits:
            return "darija_arabe"
        if score >= review and latin_hits:
            french_hints = {"bonjour", "comment", "merci", "francais", "français", "veut", "dire"}
            if french_hints.intersection(set(normalize_latin_text(original).split())):
                return "francais_darija_probable"
            return "darija_latine"
        if ar_ratio > 40:
            return "arabe_standard_probable" if context_hits or ar_ratio > 60 else "indeterminee"
        if score >= float(self.thresholds["weak_signal_threshold"]):
            return "indeterminee"
        return "indeterminee"

    def _decision(self, score: float, lang: str, weak_only: bool, arabizi_tokens, arabic_tokens, latin_tokens, context_hits):
        keep = float(self.thresholds["keep_threshold"])
        review = float(self.thresholds["review_threshold"])
        token_count = len(arabic_tokens) + len(latin_tokens)
        reasons = []
        recontrol = []
        if score >= keep:
            reasons.append(f"score >= {int(keep)}")
        if context_hits:
            reasons.append("contexte marocain detecte")
        if arabizi_tokens:
            reasons.append("tokens Arabizi plausibles")
        if weak_only:
            recontrol.append("mots faibles seuls")
        if token_count < 3:
            recontrol.append("texte tres court")
        if arabizi_tokens and score < keep:
            recontrol.append("Arabizi detecte mais signal lexical insuffisant")
        if lang == "arabe_standard_probable" and context_hits:
            return "Conserver", "moyenne", reasons or ["arabe marocain probable"], recontrol
        if score >= keep and not weak_only:
            return "Conserver", "elevee", reasons, recontrol
        if score >= review or recontrol:
            return "A_recontroler", "moyenne" if score >= review else "faible", reasons, recontrol
        return "Exclure", "faible", reasons, ["score faible et aucun signal suffisant"]

    @staticmethod
    def _format_limited(values: list[str], limit: int) -> str:
        return ", ".join(list(dict.fromkeys(str(v) for v in values if str(v).strip()))[:limit])


@lru_cache(maxsize=1)
def get_default_detector() -> DarijaDetector:
    return DarijaDetector()


def detect_darija(text: str | None) -> dict:
    return get_default_detector().detect(text)


# Backward-compatible constants used by the parallel text detector.
_LEXICON = load_lexicon()
DARija_LATIN_WORDS = set(_LEXICON.latin_weights)
DARija_ARABIC_WORDS = set(_LEXICON.arabic_weights)
