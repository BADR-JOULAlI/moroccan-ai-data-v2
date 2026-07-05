from __future__ import annotations

import re
from bs4 import BeautifulSoup

LICENSE_PATTERNS = [
    (re.compile(r"creative commons|cc-by|cc by|licence ouverte|open license", re.I), "Probablement"),
    (re.compile(r"copyright|tous droits réservés|all rights reserved", re.I), "A_verifier"),
]


def detect_license(html: str, url: str = "") -> dict:
    soup = BeautifulSoup(html or "", "lxml")
    text = soup.get_text(" ", strip=True)
    license_url = ""
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        label = anchor.get_text(" ", strip=True).lower()
        if "license" in href.lower() or "licence" in label or "creativecommons" in href.lower():
            license_url = href
            break
    for pattern, status in LICENSE_PATTERNS:
        if pattern.search(text):
            return {"Licence": status, "URL_licence": license_url, "Autorisation_entrainement_IA": "A_verifier"}
    return {"Licence": "Inconnue", "URL_licence": license_url, "Autorisation_entrainement_IA": "Inconnue"}
