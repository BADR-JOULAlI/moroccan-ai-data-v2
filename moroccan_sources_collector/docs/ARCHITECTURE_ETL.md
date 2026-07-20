# Architecture technique ETL

Ce document décrit le fonctionnement actuel du projet `moroccan_sources_collector`.

## Objectif du projet

Le projet construit un catalogue de sources numériques utiles pour un corpus IA marocain. Le périmètre principal est :

- Darija marocaine en alphabet arabe ;
- Darija marocaine en alphabet latin ;
- Arabizi ;
- contenus mixtes arabe-Darija ;
- contenus français-Darija ;
- culture, histoire, traditions et patrimoine marocain ;
- vidéos YouTube, chaînes, posts Facebook publics et ressources web exploitables.

Le flux MVP se concentre volontairement sur YouTube et Facebook afin de rester robuste, compréhensible et démontrable.

## Exécution avec uv

Commandes d’installation utiles pour la soutenance :

```bash
uv init
uv add playwright httpx beautifulsoup4 openpyxl pyyaml pytest
uv run playwright install chromium
```

Commande MVP par défaut :

```bash
uv run python -m src.main
```

Commande paramétrée :

```bash
uv run python -m src.main mvp --max-links 800 --min-darija-density 0.15
```

## Flux ETL MVP

Le mode MVP de `src/main.py` suit un flux linéaire strict.

```text
Extraction Playwright
        |
        v
data/intermediate/candidates.jsonl
        |
        v
Transformation + détection Darija
        |
        v
data/intermediate/verified.jsonl
        |
        v
Export Excel / CSV / JSONL
```

## Étape 1 : Extraction

Fonctions principales :

- `mvp_extract_async`
- `mvp_extract`

Entrées :

- `config/seed_sources.yaml`
- `config/settings.yaml`
- argument CLI `--max-links`

Fonctionnement :

- charge uniquement les seeds sociales : YouTube, chaînes YouTube, Facebook public, Google dorks Facebook ;
- ouvre les pages dynamiques avec Playwright ;
- applique le scroll contrôlé ;
- extrait uniquement les liens concrets avec `extract_production_links` ;
- supprime les doublons ;
- sauvegarde les candidats dans `data/intermediate/candidates.jsonl`.

Sortie candidate :

```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "source_name": "YouTube Darija podcasts",
  "source_url": "https://www.youtube.com/results?...",
  "source_category": "Audio_video",
  "source_priority": "P0",
  "discovery_method": "youtube_search_result",
  "platform": "YouTube",
  "anchor_text": "...",
  "query": "darija podcast",
  "date_capture": "2026-07-08",
  "status": "DISCOVERED"
}
```

## Étape 2 : Transformation et analyse

Fonctions principales :

- `mvp_transform`
- `calculate_darija_score`
- `detect_darija`

Entrée :

- `data/intermediate/candidates.jsonl`

Fonctionnement :

- combine l’URL, le nom de source, les mots-clés et le texte d’ancre ;
- normalise les écritures sociales comme `bzaaaaf` vers `bzaf` ;
- détecte les mots Darija, Arabizi et indices marocains ;
- calcule une densité Darija ;
- conserve uniquement les lignes dont la densité dépasse `--min-darija-density`.

Sortie :

- `data/intermediate/verified.jsonl`

## Étape 3 : Chargement et export

Fonction principale :

- `mvp_load`

Sorties :

- `data/output/catalogue_sources_marocaines_ai.xlsx`
- `data/output/catalogue_sources_marocaines_ai.csv`
- `data/output/catalogue_sources_marocaines_ai.jsonl`

Le fichier Excel contient une colonne `Ouvrir` avec formule :

```excel
=HYPERLINK(D2,"Ouvrir")
```

## Gestion des plateformes

### YouTube

Le projet extrait uniquement :

- vidéos : `https://www.youtube.com/watch?v=...`
- chaînes : `https://www.youtube.com/@Createur`

Le projet ignore :

- `youtube.com/results?search_query=...`
- `/feed/...`
- URLs de navigation interne ;
- paramètres de tracking.

### Facebook

Le projet extrait uniquement :

- `facebook.com/[page]/posts/[id]`
- `facebook.com/watch?v=[id]`
- `facebook.com/reel/[id]`
- `facebook.com/permalink.php?id=...&story_fbid=...`

Le projet ignore :

- login ;
- groupes privés ;
- pages de navigation ;
- shares ;
- paramètres Meta comme `fbclid`, `__tn__`, `__cft__`.

## Politique anti-blocage

Le projet utilise Playwright pour rendre des pages publiques dynamiques. Il ne contourne jamais :

- CAPTCHA ;
- authentification obligatoire ;
- protections anti-robot ;
- contenus privés.

Si une page exige une connexion, le crawler journalise l’événement et passe à la source suivante.

## Commandes héritées

Les anciennes commandes restent disponibles pour comparaison ou démonstration avancée :

```bash
uv run python -m src.main collect --max-links 200
uv run python -m src.main verify --max-links 200
uv run python -m src.main export
uv run python -m src.main run-all --max-links 200
uv run python -m src.main audit-links --input catalogue_sources_marocaines_ai.xlsx
```

Le MVP recommandé pour la soutenance reste :

```bash
uv run python -m src.main
```
