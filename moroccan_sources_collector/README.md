# Moroccan Sources Collector

Application Python pour découvrir, analyser, filtrer et exporter des sources utiles à la constitution d’un corpus IA marocain.

Le MVP actuel se concentre sur les sources sociales de haute qualité :

- vidéos et chaînes YouTube ;
- posts Facebook publics ;
- contenus liés à la Darija, l’Arabizi, la culture et le patrimoine marocain.

Le livrable principal est :

```text
data/output/catalogue_sources_marocaines_ai.xlsx
```

## Documentation

La documentation technique complète est disponible ici :

- [Architecture ETL](docs/ARCHITECTURE_ETL.md)
- [Référence du code](docs/CODE_REFERENCE.md)

## Installation avec uv

Commandes recommandées pour un environnement propre :

```bash
uv init
uv add playwright httpx beautifulsoup4 openpyxl pyyaml pytest
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
Extraction -> Transformation/Analyse -> Chargement/Export
```

## Étape 1 : Extraction

Le projet utilise Playwright pour ouvrir des pages dynamiques et extraire uniquement des URLs concrètes :

- `https://www.youtube.com/watch?v=...`
- `https://www.youtube.com/@Createur`
- `https://facebook.com/[page]/posts/[id]`
- `https://facebook.com/watch?v=[id]`
- `https://facebook.com/reel/[id]`
- `https://facebook.com/permalink.php?id=...&story_fbid=...`

Les pages de recherche comme `youtube.com/results?search_query=...` ne sont pas conservées.

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
- calcule une densité Darija ;
- filtre selon `--min-darija-density`.

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

## Commandes héritées

Les commandes historiques restent disponibles :

```bash
uv run python -m src.main collect --max-links 200
uv run python -m src.main verify --max-links 200
uv run python -m src.main export
uv run python -m src.main run-all --max-links 200
uv run python -m src.main audit-links --input catalogue_sources_marocaines_ai.xlsx
```

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
