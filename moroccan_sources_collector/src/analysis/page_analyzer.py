"""Module d?analyse linguistique ou m?tier utilis? pendant la transformation des donn?es."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.analysis.category_classifier import classify_category
from src.analysis.language_detector import detect_language
from src.analysis.parallel_text_detector import detect_parallel_text
from src.analysis.region_detector import detect_regions
from src.utils.text_utils import clean_text, truncate
from src.validation.license_checker import detect_license


def analyze_page(html: str, url: str, seed_category: str, regions_config: dict) -> dict:
    """D?crit le fonctionnement de `analyze_page` et retourne le r?sultat attendu par le module."""
    soup = BeautifulSoup(html or "", "lxml")
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    meta = soup.find("meta", attrs={"name": "description"})
    description = clean_text(meta.get("content", "")) if meta else ""
    h1 = clean_text(soup.find("h1").get_text(" ", strip=True)) if soup.find("h1") else ""
    h2 = "; ".join(clean_text(tag.get_text(" ", strip=True)) for tag in soup.find_all("h2")[:5])
    lang_html = soup.html.get("lang", "") if soup.html else ""
    text = truncate(soup.get_text("\n", strip=True), 5000)
    combined = " ".join([title, description, h1, h2, text])
    language = detect_language(combined)
    parallel = detect_parallel_text(html, text)
    category = classify_category(combined, url, seed_category)
    license_data = detect_license(html, url)
    org = ""
    author = ""
    date = ""
    for meta_tag in soup.find_all("meta"):
        name = (meta_tag.get("name") or meta_tag.get("property") or "").lower()
        content = meta_tag.get("content", "")
        if name in {"author", "article:author"}:
            author = content
        if "published" in name or "date" == name:
            date = content
        if "site_name" in name:
            org = content
    if parallel["Contenu_parallele"] == "Oui":
        language["Langue_principale"] = "francais_darija"
        language["Decision_linguistique"] = "Conserver"
    return {
        "Description_source": description or h1 or title,
        "Titre": title,
        "Langue_HTML": lang_html,
        "H1": h1,
        "H2": h2,
        "Organisme": org,
        "Auteur": author,
        "Date_publication": date,
        "Texte_extrait": text,
        "Region_marocaine": detect_regions(combined, regions_config),
        "Type_contenu": "HTML",
        **language,
        **parallel,
        **category,
        **license_data,
    }
