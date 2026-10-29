# Moroccan Sources Collector

Application Python pour découvrir, analyser, filtrer et exporter des sources utiles à la constitution d’un corpus IA marocain.

Le MVP actuel collecte uniquement des sites web classiques :

- contenus liés à la Darija, l’Arabizi et l'arabe standard ;
- contenus parallèles français-Darija ;
- culture et patrimoine marocains.

YouTube, Facebook, GitHub, HuggingFace et Kaggle sont exclus des sources,
liens enfants, redirections et exports du parcours de collecte. Les anciens
extracteurs sociaux restent disponibles pour les expériences historiques;
ils ne décrivent pas le MVP exécuté par défaut.

Le livrable principal est :

```text
data/output/catalogue_sources_marocaines_ai.xlsx
```

## Documentation

La documentation technique complète est disponible ici :

- [Architecture ETL](docs/ARCHITECTURE_ETL.md)
- [Référence du code](docs/CODE_REFERENCE.md)

Le [README racine](../README.md) et le [suivi de fiabilisation](../RELIABILITY.md)
décrivent le parcours actuel. Les documents historiques d'architecture et de
référence peuvent encore présenter l'ancien parcours social.

## Installation avec uv

Commandes recommandées pour un environnement propre :

```bash
uv sync --frozen
uv run playwright install chromium
```

Le fichier `pyproject.toml` contient aussi les dépendances nécessaires au projet.

## Lancement MVP

Commande par défaut :

```bash
uv run python -m src.main
```

Commande paramétrée :

```bash
uv run python -m src.main mvp --max-links 800 --min-darija-density 0.15
```

Le flux exécuté est :

```text
Découverte web -> Vérification et sélection -> Catalogue -> Revue humaine
```

## Étape 1 : Extraction

Le collecteur découvre les liens depuis `config/seed_sources.yaml` par HTTP et,
pour les sources configurées, avec Playwright. Chaque requête du parcours actif
est soumise au périmètre et aux règles robots avant de télécharger du contenu.
Les redirections sont contrôlées avant de contacter leur destination. Les
erreurs de lecture des robots suspendent la requête et restent réessayables.

Sortie intermédiaire :

```text
data/intermediate/candidates.jsonl
```

## Étape 2 : Transformation et analyse

Le projet analyse les textes disponibles avec :

```text
src/analysis/darija_detector.py
```

Le détecteur :

- charge `config/darija_lexicon.yaml` ;
- normalise les écritures sociales ;
- réduit les répétitions abusives comme `bzaaaaf` vers `bzaf` ;
- détecte Darija arabe, Darija latine et Arabizi ;
- calcule une densité Darija sur le texte du corps de la page ;
- applique `--min-darija-density` dans le parcours actif, avant le scoring.

La valeur zéro désactive seulement le filtre de densité. L'arabe standard,
les contenus parallèles français-Darija confirmés et les contenus culturels
avec preuves du contexte marocain restent éligibles. Les PDF sans texte restent
à valider manuellement avant leur extraction ultérieure.

Les rejets linguistiques sont conservés dans
`data/intermediate/rejected_linguistic.jsonl`; les blocages d'accès et de
périmètre dans `data/intermediate/blocked_candidates.jsonl`.

Sortie intermédiaire :

```text
data/intermediate/verified.jsonl
```

## Étape 3 : Export

Sorties finales :

```text
data/output/catalogue_sources_marocaines_ai.xlsx
data/output/catalogue_sources_marocaines_ai.csv
data/output/catalogue_sources_marocaines_ai.jsonl
```

Le fichier Excel contient une colonne `Ouvrir` avec une formule `HYPERLINK`.

Le CSV `data/output/liens_a_valider_manuellement.csv` permet de renseigner
`accept`, `reject` ou `maybe` dans `Decision_validation`. Après validation :

```bash
uv run python -m src.main export-crawler-input
```

L'export écrit `crawler_urls.txt` et `crawl_manifest.jsonl`. Il exige une URL
valide du périmètre web et un statut `Robots_txt=Oui`, même si le lien a été
accepté manuellement. Il affiche les motifs des lignes écartées.

## Commandes héritées

Les commandes historiques restent disponibles :

```bash
uv run python -m src.main collect --max-links 200
uv run python -m src.main verify --max-links 200
uv run python -m src.main export
uv run python -m src.main run-all --max-links 200
uv run python -m src.main audit-links --input catalogue_sources_marocaines_ai.xlsx
```

`expand` applique les mêmes contrôles web/robots pendant la découverte.
`audit-links` est un diagnostic explicite qui peut analyser des plateformes
exclues de la collecte, tout en respectant leurs robots. Cet audit ne fournit
pas une dérogation à l'export vers le crawler.

## Tests

Lancer la suite de tests :

```bash
uv run pytest -q
```

Les tests couvrent :

- extraction YouTube stricte ;
- extraction Facebook stricte ;
- Google dorks ;
- détection Darija ;
- Arabizi ;
- export Excel ;
- audit URL ;
- déduplication.

Les régressions du mode web couvrent aussi le périmètre, chaque destination
HTTP, le cache et les erreurs robots, les routes navigateur simulées, les
sitemaps XML, le seuil linguistique réel et la validation avant export. Tous
ces tests utilisent des réponses simulées et n'effectuent pas de crawl réel.

## Périmètre linguistique

Le français général n’est pas collecté. Une source en français est conservée uniquement si elle est utile pour :

- traduction français-Darija ;
- dictionnaire ou lexique ;
- phrases parallèles ;
- dialogues bilingues ;
- culture marocaine ;
- patrimoine marocain ;
- données utiles à l’entraînement du modèle.

## Notes de soutenance

Le projet démontre :

- un pipeline ETL clair ;
- une extraction dynamique avec Playwright ;
- un filtrage linguistique Darija ;
- des exports structurés ;
- une séparation propre entre configuration, discovery, analyse et storage ;
- une base de tests automatisés.
