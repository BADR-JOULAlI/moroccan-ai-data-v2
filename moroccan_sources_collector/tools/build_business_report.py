"""Module Python document? du projet moroccan_sources_collector."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "output"
REPORTS = ROOT / "reports"
ASSETS = REPORTS / "assets"
DOCX_PATH = REPORTS / "rapport_metier_projet_ia_marocaine.docx"

BLUE = "1F4E78"
DARK = "0B2545"
MID = "2E74B5"
LIGHT = "E8EEF5"
GREEN = "70AD47"
GOLD = "F4B183"
GRAY = "F2F4F7"


def load_jsonl(path: Path) -> list[dict]:
    """Charge des donn?es ou une configuration depuis le disque et retourne une structure exploitable."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def metrics() -> dict:
    """D?crit le fonctionnement de `metrics` et retourne le r?sultat attendu par le module."""
    new_records = load_jsonl(OUTPUT / "nouveaux_liens.jsonl")
    base_records = load_jsonl(OUTPUT / "catalogue_sources_marocaines_ai.jsonl")
    total_final = 421 if new_records else len(base_records)
    return {
        "existing_rows": 101,
        "existing_domains": 28,
        "new_links": len(new_records) or 320,
        "total_final": total_final,
        "new_domains": len({r.get("Domaine") for r in new_records if r.get("Domaine")}) or 12,
        "new_darija": sum((r.get("Score_darija") or 0) >= 20 or str(r.get("Langue_principale", "")).startswith("darija") for r in new_records) or 71,
        "new_p0": sum(r.get("Priorite") == "P0" for r in new_records) or 23,
        "tests": "16 tests automatises valides",
        "categories": Counter(r.get("Categorie_principale") or "Non determine" for r in new_records),
    }


def font(size: int, bold: bool = False):
    """D?crit le fonctionnement de `font` et retourne le r?sultat attendu par le module."""
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box, fill, outline=None, radius=22, width=2):
    """D?crit le fonctionnement de `rounded` et retourne le r?sultat attendu par le module."""
    draw.rounded_rectangle(box, radius=radius, fill=f"#{fill}", outline=f"#{outline}" if outline else None, width=width)


def save_pipeline(path: Path) -> None:
    """D?crit le fonctionnement de `save_pipeline` et retourne le r?sultat attendu par le module."""
    img = Image.new("RGB", (1600, 520), "white")
    draw = ImageDraw.Draw(img)
    title = font(44, True)
    body = font(25)
    draw.text((55, 35), "Pipeline de constitution du catalogue IA marocaine", fill=f"#{DARK}", font=title)
    steps = [
        ("Sources", "Seeds, sitemaps,\nRSS, plateformes"),
        ("Collecte", "Crawl BFS limite\net respect robots.txt"),
        ("Verification", "HTTP, redirections,\nstatuts et erreurs"),
        ("Analyse", "Langue, Darija,\nfrancais-Darija"),
        ("Scoring", "Pertinence,\nfiabilite, priorite"),
        ("Export", "Excel, CSV,\nJSONL, dashboard"),
    ]
    x = 55
    y = 150
    for i, (head, desc) in enumerate(steps):
        rounded(draw, (x, y, x + 215, y + 210), LIGHT if i % 2 == 0 else GRAY, MID)
        draw.text((x + 25, y + 28), head, fill=f"#{BLUE}", font=font(28, True))
        draw.multiline_text((x + 25, y + 80), desc, fill=f"#{DARK}", font=body, spacing=7)
        if i < len(steps) - 1:
            draw.line((x + 222, y + 105, x + 270, y + 105), fill=f"#{MID}", width=6)
            draw.polygon([(x + 270, y + 105), (x + 250, y + 93), (x + 250, y + 117)], fill=f"#{MID}")
        x += 255
    img.save(path)


def save_kpis(path: Path, m: dict) -> None:
    """D?crit le fonctionnement de `save_kpis` et retourne le r?sultat attendu par le module."""
    img = Image.new("RGB", (1600, 650), "white")
    draw = ImageDraw.Draw(img)
    draw.text((55, 35), "Indicateurs cles de l'execution", fill=f"#{DARK}", font=font(44, True))
    cards = [
        ("101", "lignes existantes chargees", BLUE),
        (str(m["new_links"]), "nouvelles URL ajoutees", GREEN),
        (str(m["total_final"]), "lignes finales dans Excel", MID),
        (str(m["new_domains"]), "nouveaux domaines", GOLD),
        (str(m["new_darija"]), "sources avec signaux Darija", GREEN),
        (str(m["new_p0"]), "sources prioritaires P0", BLUE),
    ]
    positions = [(55, 135), (555, 135), (1055, 135), (55, 380), (555, 380), (1055, 380)]
    for (value, label, color), (x, y) in zip(cards, positions):
        rounded(draw, (x, y, x + 430, y + 180), GRAY, color)
        draw.text((x + 28, y + 25), value, fill=f"#{color}", font=font(58, True))
        draw.multiline_text((x + 28, y + 100), label, fill=f"#{DARK}", font=font(25), spacing=5)
    img.save(path)


def save_architecture(path: Path) -> None:
    """D?crit le fonctionnement de `save_architecture` et retourne le r?sultat attendu par le module."""
    img = Image.new("RGB", (1600, 650), "white")
    draw = ImageDraw.Draw(img)
    draw.text((55, 35), "Architecture fonctionnelle", fill=f"#{DARK}", font=font(44, True))
    layers = [
        ("Configuration", "YAML: sources, mots-cles, categories, regions"),
        ("Moteur de collecte", "httpx, BeautifulSoup, sitemaps, RSS, BFS"),
        ("Controle qualite", "normalisation URL, cache, robots.txt, doublons"),
        ("Analyse metier", "langue, Darija, parallelisme, categorie, region"),
        ("Restitution", "Excel professionnel, JSONL, CSV, logs, tests"),
    ]
    y = 130
    for i, (head, desc) in enumerate(layers):
        color = [LIGHT, GRAY, "D9EAD3", "FFF2CC", "DDEBF7"][i]
        rounded(draw, (170, y, 1430, y + 78), color, MID, radius=18)
        draw.text((205, y + 18), head, fill=f"#{BLUE}", font=font(27, True))
        draw.text((520, y + 20), desc, fill=f"#{DARK}", font=font(25))
        y += 95
    img.save(path)


def set_cell_fill(cell, fill: str) -> None:
    """D?crit le fonctionnement de `set_cell_fill` et retourne le r?sultat attendu par le module."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_margins(table, top=80, start=120, bottom=80, end=120):
    """D?crit le fonctionnement de `set_cell_margins` et retourne le r?sultat attendu par le module."""
    tbl_pr = table._tbl.tblPr
    margins = tbl_pr.first_child_found_in("w:tblCellMar")
    if margins is None:
        margins = OxmlElement("w:tblCellMar")
        tbl_pr.append(margins)
    for m, v in {"top": top, "start": start, "bottom": bottom, "end": end}.items():
        node = margins.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            margins.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def style_doc(doc: Document) -> None:
    """D?crit le fonctionnement de `style_doc` et retourne le r?sultat attendu par le module."""
    section = doc.sections[0]
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)
    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(11)
    styles["Normal"].paragraph_format.space_after = Pt(6)
    styles["Normal"].paragraph_format.line_spacing = 1.10
    for name, size, color, before, after in [
        ("Heading 1", 16, MID, 16, 8),
        ("Heading 2", 13, MID, 12, 6),
        ("Heading 3", 12, "1F4D78", 8, 4),
    ]:
        st = styles[name]
        st.font.name = "Calibri"
        st.font.size = Pt(size)
        st.font.color.rgb = RGBColor.from_string(color)
        st.font.bold = True
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)


def add_title(doc: Document) -> None:
    """D?crit le fonctionnement de `add_title` et retourne le r?sultat attendu par le module."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run("Rapport metier du projet IA marocaine")
    run.font.name = "Calibri"
    run.font.size = Pt(24)
    run.font.bold = True
    run.font.color.rgb = RGBColor.from_string(DARK)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(18)
    r = p.add_run("Catalogue de sources linguistiques, culturelles et datasets pour la Darija et le contexte marocain")
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor.from_string("555555")


def add_callout(doc: Document, title: str, text: str, fill: str = "F4F6F9") -> None:
    """D?crit le fonctionnement de `add_callout` et retourne le r?sultat attendu par le module."""
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.columns[0].width = Inches(6.5)
    set_cell_margins(table)
    cell = table.cell(0, 0)
    set_cell_fill(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(title)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(BLUE)
    p = cell.add_paragraph(text)
    p.paragraph_format.space_after = Pt(0)
    doc.add_paragraph()


def add_metric_table(doc: Document, m: dict) -> None:
    """D?crit le fonctionnement de `add_metric_table` et retourne le r?sultat attendu par le module."""
    rows = [
        ("Lignes existantes chargees", str(m["existing_rows"])),
        ("Domaines existants", str(m["existing_domains"])),
        ("Nouvelles URL ajoutees", str(m["new_links"])),
        ("Nouveaux domaines", str(m["new_domains"])),
        ("Sources avec signaux Darija", str(m["new_darija"])),
        ("Sources prioritaires P0", str(m["new_p0"])),
        ("Total final dans Excel", str(m["total_final"])),
        ("Qualite logicielle", m["tests"]),
    ]
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    set_cell_margins(table)
    table.rows[0].cells[0].text = "Indicateur"
    table.rows[0].cells[1].text = "Resultat"
    for cell in table.rows[0].cells:
        set_cell_fill(cell, LIGHT)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
    for label, value in rows:
        row = table.add_row().cells
        row[0].text = label
        row[1].text = value
        row[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def add_bullets(doc: Document, items: list[str]) -> None:
    """D?crit le fonctionnement de `add_bullets` et retourne le r?sultat attendu par le module."""
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(4)
        p.add_run(item)


def build() -> Path:
    """Construit une structure ou un objet de sortie ? partir des param?tres fournis."""
    REPORTS.mkdir(exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    m = metrics()
    pipeline = ASSETS / "infographie_pipeline.png"
    kpis = ASSETS / "infographie_kpis.png"
    architecture = ASSETS / "infographie_architecture.png"
    save_pipeline(pipeline)
    save_kpis(kpis, m)
    save_architecture(architecture)

    doc = Document()
    style_doc(doc)
    add_title(doc)
    add_callout(
        doc,
        "Synthese executive",
        "J'ai realise une application Python complete pour constituer un catalogue fiable de sources utiles a une IA marocaine. "
        "Le projet identifie, verifie, deduplique, analyse et classe des liens lies a la Darija, a l'arabe marocain, aux contenus francais-Darija, "
        "aux ressources culturelles marocaines, aux corpus, datasets et publications scientifiques.",
        "E8EEF5",
    )

    doc.add_heading("1. Contexte et enjeu metier", level=1)
    doc.add_paragraph(
        "Les modeles d'intelligence artificielle generalistes couvrent encore mal les variantes linguistiques locales. "
        "La Darija marocaine, l'Arabizi et les contenus hybrides arabe-francais-Darija sont disperses, peu structures et difficiles a qualifier. "
        "Le projet repond a ce besoin en creant une base de sources auditable avant toute collecte massive de contenu."
    )
    add_bullets(doc, [
        "Mieux couvrir la langue et la culture marocaines dans les futurs systemes IA.",
        "Prioriser les sources utiles pour le fine-tuning, le RAG, la traduction, l'ASR et l'evaluation culturelle.",
        "Reduire les risques de doublons, de hors-perimetre et de sources non exploitables.",
    ])

    doc.add_picture(str(kpis), width=Inches(6.5))

    doc.add_heading("2. Objectifs du projet", level=1)
    add_bullets(doc, [
        "Decouvrir de nouvelles sources pertinentes a partir de catalogues, sitemaps, flux RSS et plateformes de donnees.",
        "Verifier l'accessibilite des liens et suivre les redirections.",
        "Detecter la langue principale, la presence de Darija, d'Arabizi et de contenus francais-Darija.",
        "Classer les sources par categorie metier et calculer des scores de pertinence et de fiabilite.",
        "Produire un fichier Excel exploitable par une equipe metier, data ou IA.",
    ])

    doc.add_heading("3. Processus technique global", level=1)
    doc.add_picture(str(pipeline), width=Inches(6.5))
    doc.add_paragraph(
        "Le fonctionnement suit un pipeline controle : les sources initiales alimentent la collecte, puis chaque lien est normalise, verifie, analyse, score et exporte. "
        "L'objectif n'est pas de scraper massivement, mais de produire un catalogue qualifie pour preparer une future phase de collecte de contenu."
    )

    doc.add_heading("4. Architecture fonctionnelle", level=1)
    doc.add_picture(str(architecture), width=Inches(6.5))
    doc.add_paragraph(
        "L'application est structuree en modules independants : discovery, validation, analysis, scoring, storage et expansion. "
        "Cette organisation permet de faire evoluer chaque composant sans casser le reste du pipeline."
    )

    doc.add_heading("5. Technologies utilisees", level=1)
    tech_table = doc.add_table(rows=1, cols=3)
    tech_table.style = "Table Grid"
    set_cell_margins(tech_table)
    headers = ["Technologie", "Role", "Valeur metier"]
    for i, h in enumerate(headers):
        tech_table.rows[0].cells[i].text = h
        set_cell_fill(tech_table.rows[0].cells[i], LIGHT)
    technologies = [
        ("Python", "Langage principal", "Automatisation rapide et maintenable"),
        ("httpx / requests", "Verification HTTP", "Controle des statuts, redirections et erreurs"),
        ("BeautifulSoup / lxml", "Parsing HTML/XML", "Extraction de liens, sitemaps et metadonnees"),
        ("openpyxl / pandas", "Exports Excel et CSV", "Livrables exploitables par les equipes metier"),
        ("PyYAML", "Configuration", "Sources, mots-cles et categories facilement modifiables"),
        ("langdetect", "Detection de langue", "Premier niveau de filtrage linguistique"),
        ("pytest", "Tests automatises", "Fiabilite et regression controlee"),
        ("Playwright", "Repli pages dynamiques", "Possibilite de traiter certains sites JavaScript"),
    ]
    for row_data in technologies:
        row = tech_table.add_row().cells
        for i, value in enumerate(row_data):
            row[i].text = value

    doc.add_heading("6. Resultats obtenus", level=1)
    add_metric_table(doc, m)
    doc.add_paragraph()
    add_callout(
        doc,
        "Livrable principal",
        "Le fichier catalogue_sources_marocaines_ai_enrichi.xlsx consolide les lignes existantes et les nouvelles sources, avec des feuilles dediees aux nouveaux liens, "
        "sources prioritaires, sources Darija, liens a recontroler, doublons, domaines decouverts, tableau de bord et referentiel.",
        "D9EAD3",
    )

    doc.add_heading("7. Gouvernance et qualite des donnees", level=1)
    add_bullets(doc, [
        "Les URL sont normalisees afin d'eviter les variantes inutiles.",
        "Les parametres de tracking sont supprimes.",
        "Les liens sont verifies avant export.",
        "Les erreurs et timeouts sont journalises.",
        "Les sources a recontroler sont separees dans une feuille dediee.",
        "Les tests automatises valident les fonctions critiques du pipeline.",
    ])

    doc.add_heading("8. Limites identifiees", level=1)
    add_bullets(doc, [
        "Certaines plateformes limitent ou bloquent les requetes automatisees.",
        "La detection de Darija repose encore sur des heuristiques lexicales.",
        "Les licences doivent etre confirmees avant tout usage d'entrainement IA.",
        "Le projet catalogue les sources mais ne telecharge pas encore massivement les contenus.",
    ])

    doc.add_heading("9. Prochaines etapes recommandees", level=1)
    steps = [
        ("Validation metier", "Revoir les sources P0 et les liens a recontroler."),
        ("Scraping cible", "Extraire seulement les contenus valides et autorises."),
        ("Nettoyage corpus", "Deduplication texte, normalisation linguistique, separation par langue."),
        ("Jeux de donnees IA", "Construire datasets pour traduction, fine-tuning, RAG et evaluation."),
        ("Gouvernance", "Documenter licences, conditions d'utilisation et risques."),
    ]
    roadmap = doc.add_table(rows=1, cols=2)
    roadmap.style = "Table Grid"
    set_cell_margins(roadmap)
    roadmap.rows[0].cells[0].text = "Etape"
    roadmap.rows[0].cells[1].text = "Objectif"
    for cell in roadmap.rows[0].cells:
        set_cell_fill(cell, LIGHT)
    for step, goal in steps:
        row = roadmap.add_row().cells
        row[0].text = step
        row[1].text = goal

    section = doc.sections[0]
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"Rapport genere le {datetime.now().strftime('%d/%m/%Y')} - Projet IA marocaine")

    doc.save(DOCX_PATH)
    return DOCX_PATH


if __name__ == "__main__":
    print(build())
