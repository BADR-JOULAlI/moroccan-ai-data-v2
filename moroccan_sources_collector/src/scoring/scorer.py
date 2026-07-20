"""Module de calcul des scores de pertinence et de fiabilit?."""

from __future__ import annotations


def score_record(record: dict) -> dict:
    """Attribue un score de pertinence ou de fiabilit? ? une ressource."""
    relevance = 0
    text = " ".join(str(record.get(k, "")) for k in ["URL_finale", "Description_source", "Categorie_principale", "Mots_cles_associes"]).lower()
    if any(token in text for token in ["maroc", "morocco", "moroccan", "المغرب", "darija", "دارجة"]):
        relevance += 25
    if int(record.get("Score_darija") or 0) >= 20:
        relevance += 20
    if record.get("Contenu_parallele") == "Oui":
        relevance += 20
    if record.get("Categorie_principale") in {"Dataset_IA", "Corpus_linguistique"}:
        relevance += 15
    if record.get("Priorite") == "P0" or record.get("Categorie_principale") == "Publication_scientifique":
        relevance += 10
    if record.get("Licence") in {"Oui", "Probablement"}:
        relevance += 5
    if record.get("Description_source") and record.get("Statut_HTTP"):
        relevance += 5
    if record.get("Decision_linguistique") == "Exclure":
        relevance -= 20
    if record.get("Statut_lien") not in {"Accessible", "Accessible_avec_redirection"}:
        relevance -= 10
    if record.get("Langue_principale") == "autre_langue" and record.get("Categorie_principale") not in {"Dataset_IA", "Publication_scientifique"}:
        relevance -= 20
    relevance = max(0, min(100, relevance))

    reliability = 50
    if record.get("Statut_lien") in {"Accessible", "Accessible_avec_redirection"}:
        reliability += 25
    if record.get("Robots_txt") == "Oui":
        reliability += 10
    if record.get("Licence") in {"Oui", "Probablement"}:
        reliability += 10
    if record.get("Priorite") == "P0":
        reliability += 5
    if record.get("Statut_lien") in {"Timeout", "Bloque", "Erreur_SSL"}:
        reliability -= 20
    reliability = max(0, min(100, reliability))

    priority = record.get("Priorite") or "P2"
    if relevance >= 70 and reliability >= 70:
        priority = "P0"
    elif relevance >= 45:
        priority = "P1"
    else:
        priority = "P2"
    record.update({"Score_pertinence": relevance, "Score_fiabilite": reliability, "Priorite": priority})
    return record
