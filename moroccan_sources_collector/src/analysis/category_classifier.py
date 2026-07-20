"""Module d?analyse linguistique ou m?tier utilis? pendant la transformation des donn?es."""

from __future__ import annotations

RULES = [
    ("Dataset_IA", ["dataset", "corpus", "huggingface", "kaggle", "zenodo", "github"]),
    ("Publication_scientifique", ["arxiv", "acl anthology", "paper", "conference", "proceedings"]),
    ("Dictionnaire_francais_darija", ["dictionary", "dictionnaire", "francais darija", "french darija"]),
    ("Lexique_francais_darija", ["lexique", "vocabulary", "vocabulaire"]),
    ("Phrases_paralleles", ["phrases", "parallel", "traduction", "translation"]),
    ("Dialogues_bilingues", ["dialogue", "conversation"]),
    ("Proverbes", ["proverbe", "proverb", "الأمثال"]),
    ("Contes", ["conte", "story", "حكايات", "قصص"]),
    ("Gastronomie", ["cuisine", "gastronomie", "المطبخ", "الطبخ"]),
    ("Artisanat", ["artisanat", "craft", "الصناعة التقليدية"]),
    ("Musique", ["music", "musique", "الموسيقى"]),
    ("Archives", ["archive", "archives"]),
    ("Bibliotheques", ["bibliotheque", "library", "bnrm"]),
    ("Presse", ["news", "presse", "journal", "hespress"]),
    ("Darija", ["darija", "دارجة", "moroccan arabic"]),
    ("Traditions", ["tradition", "culture", "patrimoine", "التراث", "الثقافة"]),
]


def classify_category(text: str, url: str = "", seed_category: str = "Autre") -> dict:
    """D?crit le fonctionnement de `classify_category` et retourne le r?sultat attendu par le module."""
    haystack = f"{text} {url}".lower()
    for category, tokens in RULES:
        if any(token.lower() in haystack for token in tokens):
            usage = "fine_tuning" if category in {"Darija", "Phrases_paralleles", "Dialogues_bilingues"} else "RAG"
            if category in {"Dataset_IA", "Publication_scientifique"}:
                usage = "benchmark"
            return {"Categorie_principale": category, "Sous_categories": seed_category, "Usage_IA": usage}
    return {"Categorie_principale": seed_category or "Autre", "Sous_categories": "", "Usage_IA": "non_determine"}
