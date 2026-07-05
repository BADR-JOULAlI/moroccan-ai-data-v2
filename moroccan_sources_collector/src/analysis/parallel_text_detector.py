from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.analysis.darija_detector import DARija_LATIN_WORDS, detect_darija

FRENCH_HINTS = {"bonjour", "merci", "comment", "je", "tu", "vous", "avec", "beaucoup", "appelles", "français", "francais"}
PAIR_SEP_RE = re.compile(r"(.{2,80}?)(?:\||:|=>|-{2,})(.{2,100})")


def _looks_french(text: str) -> bool:
    words = set(re.findall(r"[A-Za-zÀ-ÿ]+", text.lower()))
    return bool(words & FRENCH_HINTS) or any(ch in text.lower() for ch in "éèàùç")


def _looks_darija(text: str) -> bool:
    result = detect_darija(text)
    return result["Score_darija"] > 0 or bool(set(re.findall(r"\w+", text.lower())) & DARija_LATIN_WORDS)


def detect_parallel_text(html: str, text: str) -> dict:
    examples: list[str] = []
    alignment = "non_aligne"
    soup = BeautifulSoup(html or "", "lxml")

    for row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) >= 2 and _looks_french(cells[0]) and _looks_darija(cells[1]):
            examples.append(f"{cells[0]} | {cells[1]}")

    for line in (text or "").splitlines():
        match = PAIR_SEP_RE.search(line.strip())
        if match and _looks_french(match.group(1)) and _looks_darija(match.group(2)):
            examples.append(f"{match.group(1).strip()} | {match.group(2).strip()}")

    examples = examples[:5]
    if examples:
        joined = " ".join(examples).lower()
        has_arabic = bool(re.search(r"[\u0600-\u06ff]", joined))
        has_arabizi = bool(re.search(r"\w*[2379]\w*", joined))
        if has_arabic and has_arabizi:
            alignment = "francais_darija_multiformat"
        elif has_arabic:
            alignment = "francais_darija_arabe"
        elif has_arabizi:
            alignment = "francais_arabizi"
        else:
            alignment = "francais_darija_latine"
    count = len(examples)
    return {
        "Contenu_parallele": "Oui" if count else "Non",
        "Langue_source": "francais" if count else "",
        "Langue_cible": "darija" if count else "",
        "Type_alignement": alignment,
        "Nombre_paires_detectees": count,
        "Exemples_paires": " || ".join(examples),
        "Score_alignement": min(100, count * 25),
    }
