"""Module de stockage et d?export des donn?es du pipeline."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

EXPANDED_COLUMNS = [
    "ID", "Nom_source", "URL_originale", "URL_finale", "URL_canonique", "Domaine",
    "Categorie_principale", "Sous_categories", "Description_source", "Type_source", "Type_contenu",
    "Langue_principale", "Score_darija", "Mots_darija_detectes", "Contenu_parallele",
    "Type_alignement", "Nombre_paires_detectees", "Exemples_paires", "Region_marocaine", "Usage_IA",
    "Statut_HTTP", "Statut_lien", "Robots_txt", "Licence", "Autorisation_entrainement_IA",
    "Priorite", "Score_pertinence", "Score_fiabilite", "Date_verification", "Date_decouverte",
    "Source_decouverte", "Methode_decouverte", "Requete_decouverte", "Profondeur_crawl",
    "Est_nouveau", "Batch_id", "Hash_URL", "Hash_contenu", "Doublon_de", "Notes", "Ouvrir",
]


def _format(ws, name: str) -> None:
    """D?crit le fonctionnement de `_format` et retourne le r?sultat attendu par le module."""
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        values = {ws.cell(1, idx + 1).value: row[idx].value for idx in range(len(row))}
        row_fill = None
        if values.get("Est_nouveau") == "Oui":
            row_fill = PatternFill("solid", fgColor="E2F0D9")
        if values.get("Statut_lien") not in {"Accessible", "Accessible_avec_redirection", ""}:
            row_fill = PatternFill("solid", fgColor="FCE4D6")
        if row_fill:
            for cell in row:
                cell.fill = row_fill
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col[:200])
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 60)
    if ws.max_row >= 2:
        table = Table(displayName=f"T_{name[:24]}", ref=ws.dimensions)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(table)


def _write_records(wb: Workbook, title: str, records: list[dict], columns: list[str] = EXPANDED_COLUMNS) -> None:
    """D?crit le fonctionnement de `_write_records` et retourne le r?sultat attendu par le module."""
    ws = wb.create_sheet(title)
    ws.append(columns)
    for record in records:
        row_num = ws.max_row + 1
        ws.append([f'=HYPERLINK(D{row_num},"Ouvrir")' if col == "Ouvrir" else record.get(col, "") for col in columns])
    _format(ws, title.replace(" ", "_"))


def _write_dashboard(wb: Workbook, all_records: list[dict], new_records: list[dict], duplicates: list[dict], initial_count: int) -> None:
    """D?crit le fonctionnement de `_write_dashboard` et retourne le r?sultat attendu par le module."""
    ws = wb.create_sheet("Tableau_de_bord")
    new_domains = {r.get("Domaine") for r in new_records if r.get("Domaine")}
    metrics = [
        ("Nombre initial de liens", initial_count),
        ("Nombre de nouveaux liens", len(new_records)),
        ("Total final", len(all_records)),
        ("Nombre de doublons rejetes", len(duplicates)),
        ("Nombre de domaines nouveaux", len(new_domains)),
        ("Liens accessibles", sum(r.get("Statut_lien") in {"Accessible", "Accessible_avec_redirection"} for r in new_records)),
        ("Liens a recontroler", sum(r.get("Statut_lien") not in {"Accessible", "Accessible_avec_redirection"} or r.get("Licence") == "Inconnue" for r in new_records)),
        ("Sources P0", sum(r.get("Priorite") == "P0" for r in new_records)),
        ("Sources P1", sum(r.get("Priorite") == "P1" for r in new_records)),
        ("Sources P2", sum(r.get("Priorite") == "P2" for r in new_records)),
        ("Sources Darija arabe", sum(r.get("Langue_principale") == "darija_arabe" for r in new_records)),
        ("Sources Darija latine", sum(r.get("Langue_principale") == "darija_latine" for r in new_records)),
        ("Sources Arabizi", sum(r.get("Arabizi_detecte") == "Oui" or r.get("Langue_principale") == "darija_arabizi" for r in new_records)),
        ("Sources francais-Darija", sum(r.get("Contenu_parallele") == "Oui" for r in new_records)),
    ]
    ws.append(["Indicateur", "Valeur"])
    for metric in metrics:
        ws.append(list(metric))
    start = ws.max_row + 2
    charts = [("categorie", "Categorie_principale"), ("domaine", "Domaine"), ("langue", "Langue_principale"), ("region", "Region_marocaine"), ("batch", "Batch_id")]
    for label, field in charts:
        ws.cell(start, 1, f"Repartition par {label}")
        ws.cell(start, 2, "Nombre")
        counts = Counter(r.get(field) or "Inconnu" for r in new_records)
        row = start + 1
        for key, value in counts.most_common(25):
            ws.cell(row, 1, key)
            ws.cell(row, 2, value)
            row += 1
        chart = PieChart() if label == "langue" else BarChart()
        chart.title = f"Repartition par {label}"
        chart.add_data(Reference(ws, min_col=2, min_row=start, max_row=row - 1), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=start + 1, max_row=row - 1))
        ws.add_chart(chart, f"D{start}")
        start = row + 15
    _format(ws, "Dashboard_expansion")


def _write_domains(wb: Workbook, records: list[dict]) -> None:
    """D?crit le fonctionnement de `_write_domains` et retourne le r?sultat attendu par le module."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("Domaine"):
            grouped[record["Domaine"]].append(record)
    rows = []
    for domain, items in sorted(grouped.items()):
        rows.append({
            "domaine": domain,
            "nombre_de_nouveaux_liens": len(items),
            "categorie_dominante": Counter(i.get("Categorie_principale") for i in items).most_common(1)[0][0],
            "langue_dominante": Counter(i.get("Langue_principale") for i in items).most_common(1)[0][0],
            "score_moyen": round(sum(int(i.get("Score_pertinence") or 0) for i in items) / len(items), 2),
            "statut_robots_txt": Counter(i.get("Robots_txt") for i in items).most_common(1)[0][0],
        })
    _write_records(wb, "Domaines_decouverts", rows, ["domaine", "nombre_de_nouveaux_liens", "categorie_dominante", "langue_dominante", "score_moyen", "statut_robots_txt"])


def _write_reference(wb: Workbook) -> None:
    """D?crit le fonctionnement de `_write_reference` et retourne le r?sultat attendu par le module."""
    rows = [
        {"Element": "Normalisation", "Definition": "Fragments retires, tracking retire, www retire, slash final normalise, parametres utiles tries."},
        {"Element": "Doublons", "Definition": "Rejet par URL normalisee, empreinte URL, URL finale ou hash de contenu."},
        {"Element": "Langues", "Definition": "arabe_standard, darija_arabe, darija_latine, darija_arabizi, arabe_darija_mixte, francais_darija, francais_culture_marocaine, anglais_dataset_darija, autre_langue, indeterminee."},
        {"Element": "Scores", "Definition": "+Maroc, +Darija, +parallel, +dataset/corpus, +officiel/academique, +licence; penalites doublon, hors sujet, inaccessible."},
        {"Element": "Priorites", "Definition": "P0 critique, P1 pertinent, P2 complementaire ou a recontroler."},
    ]
    _write_records(wb, "Referentiel", rows, ["Element", "Definition"])


def export_expanded_excel(all_records: list[dict], new_records: list[dict], duplicates: list[dict], path: Path, initial_count: int) -> None:
    """?crit les donn?es transform?es dans un format de sortie exploitable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    _write_records(wb, "Catalogue_liens", all_records)
    _write_records(wb, "Nouveaux_liens", new_records)
    _write_records(wb, "Sources_prioritaires", [r for r in all_records if r.get("Priorite") == "P0"])
    _write_records(wb, "Sources_francais_darija", [r for r in all_records if r.get("Contenu_parallele") == "Oui" or r.get("Langue_principale") == "francais_darija"])
    _write_records(wb, "Sources_darija", [r for r in all_records if str(r.get("Langue_principale", "")).startswith("darija") or r.get("Arabizi_detecte") == "Oui"])
    _write_records(wb, "Liens_a_recontroler", [r for r in all_records if r.get("Statut_lien") not in {"Accessible", "Accessible_avec_redirection"} or r.get("Licence") == "Inconnue"])
    _write_records(wb, "Sources_hors_perimetre", [r for r in all_records if r.get("Decision_linguistique") == "Exclure" or r.get("Langue_principale") == "autre_langue"])
    _write_records(wb, "Doublons_detectes", duplicates, ["URL_candidate", "URL_existante_correspondante", "type_doublon", "raison", "score_similarite", "source", "methode"])
    _write_domains(wb, new_records)
    _write_dashboard(wb, all_records, new_records, duplicates, initial_count)
    _write_reference(wb)
    wb.save(path)
