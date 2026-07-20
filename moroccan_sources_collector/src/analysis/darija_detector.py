"""D?tecteur lexical et statistique de Darija, Darija latine et Arabizi."""

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
PUNCT_RE = re.compile(r"[^\w\u0600-\u06ff']+", re.I)
REPEATED_CHAR_RE = re.compile(r"([^\W\d_])\1{2,}", re.I | re.U)
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
    "density_keep_threshold": 0.20,
    "density_review_threshold": 0.15,
    "max_density_repetition_per_token": 2,
}

HIGH_SIGNAL_KEYWORDS_LATIN = {
    "podcast",
    "darija",
    "maroc",
    "morocco",
    "moroccan",
    "maghrib",
    "maghreb",
    "bzzaf",
    "bzaf",
    "daba",
}
HIGH_SIGNAL_KEYWORDS_ARABIC = {
    "المغرب",
    "مغرب",
    "مغربي",
    "مغربية",
    "الدارجة",
    "دارجة",
    "بزاف",
    "دابا",
}


@dataclass(frozen=True)
class Lexicon:
    """Classe m?tier utilis?e pour structurer le comportement ou les donn?es de Lexicon."""
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
    """D?crit le fonctionnement de `_project_root` et retourne le r?sultat attendu par le module."""
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    """D?crit le fonctionnement de `_load_yaml` et retourne le r?sultat attendu par le module."""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _validate_weight_map(section: dict[str, Any], name: str) -> None:
    """D?crit le fonctionnement de `_validate_weight_map` et retourne le r?sultat attendu par le module."""
    for level in ("strong", "medium", "weak"):
        if level not in section or not isinstance(section[level], dict):
            raise ValueError(f"darija_lexicon.yaml: section {name}.{level} is required")
        for token, weight in section[level].items():
            if not str(token).strip():
                raise ValueError(f"darija_lexicon.yaml: empty token in {name}.{level}")
            if not isinstance(weight, (int, float)):
                raise ValueError(f"darija_lexicon.yaml: weight for {token!r} must be numeric")


def _flatten_weights(section: dict[str, dict[str, float]], normalizer) -> tuple[dict[str, float], dict[str, str]]:
    """D?crit le fonctionnement de `_flatten_weights` et retourne le r?sultat attendu par le module."""
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


def _list_to_weight_section(values: list[Any], weight: float = 2.5) -> dict[str, float]:
    """D?crit le fonctionnement de `_list_to_weight_section` et retourne le r?sultat attendu par le module."""
    return {str(value): weight for value in values if str(value).strip()}


def _compat_keyword_section(data: dict[str, Any], structured_name: str, flat_names: tuple[str, ...]) -> dict[str, Any]:
    """Support both the current weighted YAML and simpler keyword-list YAMLs."""
    if isinstance(data.get(structured_name), dict):
        return data[structured_name]
    merged: dict[str, float] = {}
    for name in flat_names:
        values = data.get(name) or []
        if isinstance(values, list):
            merged.update(_list_to_weight_section(values))
    return {"strong": {}, "medium": merged, "weak": {}}


@lru_cache(maxsize=1)
def load_lexicon() -> Lexicon:
    # The lexicon is loaded once per process; editing YAML does not require code changes.
    """Charge des donn?es ou une configuration depuis le disque et retourne une structure exploitable."""
    path = _project_root() / "config" / "darija_lexicon.yaml"
    data = _load_yaml(path)
    if not data.get("version"):
        raise ValueError("darija_lexicon.yaml: version is required")
    arabic_section = _compat_keyword_section(data, "arabic", ("darija_keywords_ar", "arabic_keywords", "darija_ar"))
    latin_section = _compat_keyword_section(data, "latin", ("darija_keywords_lat", "darija_keywords_arabizi", "latin_keywords", "arabizi_keywords"))
    for section_name, section in (("arabic", arabic_section), ("latin", latin_section)):
        _validate_weight_map(section, section_name)
    arabic_weights, arabic_strength = _flatten_weights(arabic_section, normalize_arabic_text)
    latin_weights, latin_strength = _flatten_weights(latin_section, normalize_latin_text)
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
    # Thresholds are externalized so the detector can be tuned for soutenance/demo runs.
    """Charge des donn?es ou une configuration depuis le disque et retourne une structure exploitable."""
    settings_path = _project_root() / "config" / "settings.yaml"
    settings = _load_yaml(settings_path) if settings_path.exists() else {}
    values = {**DEFAULT_THRESHOLDS, **(settings.get("darija_detection") or {})}
    if values["weak_signal_threshold"] > values["review_threshold"] or values["review_threshold"] > values["keep_threshold"]:
        raise ValueError("settings.yaml: darija_detection thresholds must be weak <= review <= keep")
    return values


def _canonical_latin(token: str, lexicon: Lexicon) -> str:
    """D?crit le fonctionnement de `_canonical_latin` et retourne le r?sultat attendu par le module."""
    norm = normalize_latin_text(token)
    return lexicon.variants.get(norm, norm)


def _canonical_arabic(token: str, lexicon: Lexicon) -> str:
    """D?crit le fonctionnement de `_canonical_arabic` et retourne le r?sultat attendu par le module."""
    norm = normalize_arabic_text(token)
    return lexicon.arabic_variants.get(norm, norm)


def reduce_excessive_repetitions(text: str) -> str:
    """Collapse social-media elongations: bzaaaaf -> bzaf, بزاففف -> بزاف."""
    # One repeated character is enough for dictionary matching and avoids score inflation.
    return REPEATED_CHAR_RE.sub(lambda match: match.group(1), text or "")


def normalize_social_text(text: str) -> str:
    """Light normalization before matching social content.

    The goal is not aggressive stemming; it only removes noisy punctuation and
    collapses exaggerated repeated letters so dictionary matching stays robust.
    """
    reduced = reduce_excessive_repetitions(text or "")
    return PUNCT_RE.sub(" ", reduced).strip()


def tokenize_social_text(text: str) -> list[str]:
    """D?crit le fonctionnement de `tokenize_social_text` et retourne le r?sultat attendu par le module."""
    return TOKEN_RE.findall(normalize_social_text(text))


def _is_plausible_arabizi(token: str, lexicon: Lexicon) -> bool:
    """D?crit le fonctionnement de `_is_plausible_arabizi` et retourne le r?sultat attendu par le module."""
    t = normalize_latin_text(token)
    # Guardrails avoid classifying years, versions, URLs or technical ids as Arabizi.
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
    """D?tecte un signal linguistique, technique ou m?tier et retourne un r?sultat structur?."""
    lexicon = load_lexicon()
    normalized = normalize_latin_text(normalize_social_text(text or ""))
    tokens = LATIN_TOKEN_RE.findall(normalized)
    return sorted(dict.fromkeys(t for t in tokens if _is_plausible_arabizi(t, lexicon)))


def calculate_darija_score(text: str | None) -> dict:
    """Calculate a density-first Darija signal for short social-media texts."""
    detector = get_default_detector()
    lexicon = detector.lexicon
    social_text = normalize_social_text(text or "")
    arabic_tokens = ARABIC_TOKEN_RE.findall(normalize_arabic_text(social_text))
    latin_tokens = LATIN_TOKEN_RE.findall(normalize_latin_text(social_text))
    total_tokens = len(arabic_tokens) + len(latin_tokens)
    arabic_counter = Counter(_canonical_arabic(token, lexicon) for token in arabic_tokens)
    latin_counter = Counter(_canonical_latin(token, lexicon) for token in latin_tokens)
    high_signal_tokens = sorted(
        {
            token
            for token in arabic_counter
            if token in HIGH_SIGNAL_KEYWORDS_ARABIC
            or lexicon.arabic_strength.get(token) == "strong"
            or token in lexicon.moroccan_context_arabic
        }
        | {
            token
            for token in latin_counter
            if token in HIGH_SIGNAL_KEYWORDS_LATIN
            or lexicon.latin_strength.get(token) == "strong"
            or token in lexicon.moroccan_context_latin
        }
    )
    # Cap repeated matches: "wach wach wach" should not behave like a rich Darija sentence.
    max_repeats = int(detector.thresholds.get("max_density_repetition_per_token", 2))
    arabic_matches = sum(min(count, max_repeats) for token, count in arabic_counter.items() if token in lexicon.arabic_weights)
    latin_matches = sum(min(count, max_repeats) for token, count in latin_counter.items() if token in lexicon.latin_weights)
    matched_tokens = arabic_matches + latin_matches
    density = matched_tokens / total_tokens if total_tokens else 0.0
    arabizi_tokens = detect_arabizi_tokens(text or "")
    if arabizi_tokens and total_tokens:
        # Arabizi tokens are strong signals in short social text, so they lift density.
        density = max(density, min(1.0, (matched_tokens + len(arabizi_tokens)) / total_tokens))
    keep_threshold = float(detector.thresholds.get("density_keep_threshold", 0.20))
    review_threshold = float(detector.thresholds.get("density_review_threshold", 0.15))
    is_short_text = total_tokens < 8
    probable_keep = bool(high_signal_tokens)
    if probable_keep and total_tokens:
        # Short YouTube titles often contain only one strong Moroccan/Darija signal.
        # Keep the raw density truthful, but expose a relaxed decision to the ETL.
        density = max(density, 1 / total_tokens if is_short_text else review_threshold)
    detected_variant = "indeterminee"
    if arabizi_tokens:
        detected_variant = "darija_arabizi"
    elif arabic_matches and latin_matches:
        detected_variant = "arabe_darija_mixte"
    elif arabic_matches:
        detected_variant = "darija_arabe"
    elif latin_matches:
        detected_variant = "darija_latine"
    return {
        "is_darija": density >= keep_threshold or probable_keep,
        "needs_review": review_threshold <= density < keep_threshold,
        "decision": "CONSERVER_PROBABLE" if probable_keep and density < keep_threshold else "CONSERVER" if density >= keep_threshold else "REJETER",
        "probable_keep": probable_keep,
        "is_short_text": is_short_text,
        "high_signal_tokens": high_signal_tokens,
        "rejection_reason": "" if density >= keep_threshold or probable_keep else "Densite Darija insuffisante",
        "score": round(density, 4),
        "density": round(density, 4),
        "total_tokens": total_tokens,
        "matched_tokens": matched_tokens,
        "distinct_matches": sum(1 for token in arabic_counter if token in lexicon.arabic_weights)
        + sum(1 for token in latin_counter if token in lexicon.latin_weights),
        "detected_variant": detected_variant,
        "arabizi_tokens": arabizi_tokens,
    }


class DarijaDetector:
    """Classe responsable de la d?tection et de la d?cision associ?es ? DarijaDetector."""
    def __init__(self, lexicon: Lexicon | None = None, thresholds: dict[str, float] | None = None):
        """D?crit le fonctionnement de `__init__` et retourne le r?sultat attendu par le module."""
        self.lexicon = lexicon or load_lexicon()
        self.thresholds = thresholds or load_thresholds()

    def detect(self, text: str | None) -> dict:
        """D?tecte un signal linguistique, technique ou m?tier et retourne un r?sultat structur?."""
        original = text or ""
        social_text = normalize_social_text(original)
        normalized_arabic = normalize_arabic_text(social_text)
        normalized_latin = normalize_latin_text(social_text)
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
        density_info = self._density_info(arabic_counter, latin_counter, len(arabic_tokens) + len(latin_tokens))

        # The final score mixes lexical weight, expressions, density, Arabizi and context.
        lexical_score = self._lexical_score(arabic_hits + latin_hits)
        phrase_score = min(45.0, sum(weight for _, weight in phrase_hits) * 6.0)
        density_score = self._density_score(density_info["matched_tokens"], density_info["total_tokens"])
        arabizi_score = min(float(self.thresholds["max_arabizi_bonus"]), self._arabizi_score(arabizi_tokens))
        context_score = min(float(self.thresholds["max_context_bonus"]), len(context_hits) * 2.0)
        ambiguity_penalty = min(25.0, len(negative_hits) * 3.0 + self._technical_penalty(latin_tokens))
        score = max(0.0, min(100.0, lexical_score + phrase_score + density_score + arabizi_score + context_score - ambiguity_penalty))
        strong_hits = {hit["canonical"] for hit in arabic_hits + latin_hits if hit["strength"] == "strong"}
        medium_hits = {hit["canonical"] for hit in arabic_hits + latin_hits if hit["strength"] == "medium"}
        weak_only = bool(arabic_hits or latin_hits) and not strong_hits and not medium_hits and not phrase_hits
        if phrase_hits and max(weight for _, weight in phrase_hits) >= 6.0:
            score = max(score, float(self.thresholds["keep_threshold"]))
        if (
            density_info["density"] >= float(self.thresholds.get("density_keep_threshold", 0.20))
            and density_info["distinct_matches"] >= int(self.thresholds.get("minimum_strong_hits", 2))
            and not weak_only
        ):
            # High density is accepted only when it is not caused by a single repeated word.
            score = max(score, float(self.thresholds["keep_threshold"]))
        if weak_only:
            score = min(score, float(self.thresholds["weak_signal_threshold"]) - 1)

        lang = self._language_label(score, arabic_hits, latin_hits, phrase_hits, arabizi_tokens, context_hits, original)
        decision, confidence, reasons, review = self._decision(score, lang, weak_only, arabizi_tokens, arabic_tokens, latin_tokens, context_hits)
        detected_words = self._format_limited([hit["found"] for hit in arabic_hits + latin_hits] + arabizi_tokens, 30)
        canonical_words = self._format_limited([hit["canonical"] for hit in arabic_hits + latin_hits], 30)
        return {
            "is_darija": decision == "Conserver",
            "score": round(score / 100, 4),
            "detected_variant": lang,
            "Pourcentage_script_arabe": arabic_ratio(original),
            "Pourcentage_script_latin": latin_ratio(original),
            "Score_darija": int(round(score)),
            "Densite_darija": density_info["density"],
            "Tokens_total": density_info["total_tokens"],
            "Tokens_darija_detectes": density_info["matched_tokens"],
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
        """D?crit le fonctionnement de `_weighted_hits` et retourne le r?sultat attendu par le module."""
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
        """D?crit le fonctionnement de `_phrase_hits` et retourne le r?sultat attendu par le module."""
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
        """D?crit le fonctionnement de `_context_hits` et retourne le r?sultat attendu par le module."""
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
        """D?crit le fonctionnement de `_negative_hits` et retourne le r?sultat attendu par le module."""
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
        """D?crit le fonctionnement de `_lexical_score` et retourne le r?sultat attendu par le module."""
        if not hits:
            return 0.0
        distinct = sum(hit["weight"] * 5.0 for hit in hits)
        frequency_bonus = 0.0
        for hit in hits:
            frequency_bonus += min(max(hit["count"] - 1, 0), 3) * hit["weight"]
        return min(55.0, distinct + min(float(self.thresholds["max_frequency_bonus"]), frequency_bonus))

    def _density_info(self, arabic_counter: Counter[str], latin_counter: Counter[str], token_count: int) -> dict[str, Any]:
        """D?crit le fonctionnement de `_density_info` et retourne le r?sultat attendu par le module."""
        max_repeats = int(self.thresholds.get("max_density_repetition_per_token", 2))
        # Distinct matches and capped counts keep density useful on short social posts.
        arabic_matches = sum(min(count, max_repeats) for token, count in arabic_counter.items() if token in self.lexicon.arabic_weights)
        latin_matches = sum(min(count, max_repeats) for token, count in latin_counter.items() if token in self.lexicon.latin_weights)
        matched = arabic_matches + latin_matches
        distinct = sum(1 for token in arabic_counter if token in self.lexicon.arabic_weights) + sum(1 for token in latin_counter if token in self.lexicon.latin_weights)
        density = matched / token_count if token_count else 0.0
        return {"matched_tokens": matched, "total_tokens": token_count, "distinct_matches": distinct, "density": round(density, 4)}

    def _density_score(self, hit_count: int, token_count: int) -> float:
        """D?crit le fonctionnement de `_density_score` et retourne le r?sultat attendu par le module."""
        if token_count == 0 or hit_count == 0:
            return 0.0
        density = hit_count / max(token_count, 1)
        return min(15.0, density * 100)

    def _arabizi_score(self, tokens: list[str]) -> float:
        """D?crit le fonctionnement de `_arabizi_score` et retourne le r?sultat attendu par le module."""
        score = 0.0
        for token in tokens:
            canonical = _canonical_latin(token, self.lexicon)
            score += 4.0 if canonical in self.lexicon.latin_weights else 1.5
        return score

    def _technical_penalty(self, tokens: list[str]) -> float:
        """D?crit le fonctionnement de `_technical_penalty` et retourne le r?sultat attendu par le module."""
        return sum(2.0 for token in tokens if TECH_TOKEN_RE.match(token) or YEAR_RE.match(token) or token.isdigit())

    def _language_label(self, score: float, arabic_hits, latin_hits, phrase_hits, arabizi_tokens, context_hits, original: str) -> str:
        """D?crit le fonctionnement de `_language_label` et retourne le r?sultat attendu par le module."""
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
        """D?crit le fonctionnement de `_decision` et retourne le r?sultat attendu par le module."""
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
        """D?crit le fonctionnement de `_format_limited` et retourne le r?sultat attendu par le module."""
        return ", ".join(list(dict.fromkeys(str(v) for v in values if str(v).strip()))[:limit])


@lru_cache(maxsize=1)
def get_default_detector() -> DarijaDetector:
    """D?crit le fonctionnement de `get_default_detector` et retourne le r?sultat attendu par le module."""
    return DarijaDetector()


def detect_darija(text: str | None) -> dict:
    """D?tecte un signal linguistique, technique ou m?tier et retourne un r?sultat structur?."""
    return get_default_detector().detect(text)


# Backward-compatible constants used by the parallel text detector.
_LEXICON = load_lexicon()
DARija_LATIN_WORDS = set(_LEXICON.latin_weights)
DARija_ARABIC_WORDS = set(_LEXICON.arabic_weights)
