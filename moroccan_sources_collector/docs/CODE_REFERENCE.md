# Référence du code

Ce document décrit le rôle des principaux fichiers Python du dossier `src/`.

## `src/main.py`

Point d’entrée CLI du projet.

Responsabilités :

- expose les commandes terminal ;
- orchestre le flux MVP `Extraction -> Transformation -> Load` ;
- conserve les commandes historiques `collect`, `verify`, `export`, `run-all`, `expand`, `audit-links` ;
- écrit les fichiers intermédiaires et finaux.

Fonctions MVP importantes :

- `mvp_extract_async` : extraction Playwright asynchrone des liens YouTube/Facebook ;
- `mvp_extract` : wrapper synchrone qui sauvegarde `candidates.jsonl` ;
- `mvp_transform` : filtrage Darija par densité linguistique ;
- `mvp_load` : export Excel, CSV et JSONL ;
- `run_mvp_etl` : orchestration de bout en bout.

## `src/discovery/`

Module responsable de la découverte de liens.

### `link_extractor.py`

Fonctions principales :

- `extract_production_links(html_content, platform)` : extrait uniquement des liens concrets prêts pour le catalogue ;
- `extract_youtube_links` : convertit les liens YouTube rendus en objets `DiscoveredLink` ;
- `extract_facebook_links` : extrait les posts, reels, vidéos et permalinks Facebook ;
- `extract_google_result_targets` : récupère les URLs cibles derrière les redirections Google ;
- `youtube_search_url` et `google_search_url` : construisent les URLs de recherche.

Règles importantes :

- ne jamais conserver les pages de recherche YouTube ;
- ne jamais conserver `google.com/search` ;
- nettoyer les paramètres de tracking ;
- dédupliquer les URLs.

### `search_adapters.py`

Adaptateur Playwright asynchrone.

Responsabilités :

- lancer Chromium headless ;
- configurer User-Agent, langue, timezone et viewport ;
- exécuter des recherches YouTube ;
- exécuter des Google dorks Facebook ;
- scroller les pages dynamiques ;
- retourner des objets `DiscoveredLink`.

Classe principale :

- `PlaywrightDiscoveryAdapter`

### `facebook_crawler.py`

Crawler spécialisé pour pages Facebook publiques.

Responsabilités :

- ouvrir une page Facebook publique avec Playwright ;
- accepter le bandeau cookies si présent ;
- scroller la page ;
- extraire les liens concrets ;
- arrêter proprement si connexion/CAPTCHA/blocage.

Classes :

- `FacebookCrawlerConfig`
- `FacebookCrawler`

### `catalog_crawler.py`

Orchestrateur historique du discovery.

Responsabilités :

- crawler HTTP classique ;
- discovery Playwright ;
- séparation seeds dynamiques et seeds HTTP ;
- déduplication des candidats.

### `seed_loader.py`

Charge `config/seed_sources.yaml` et filtre éventuellement par catégorie.

## `src/analysis/`

Module d’analyse linguistique et métier.

### `darija_detector.py`

Détecteur Darija principal.

Responsabilités :

- charger `config/darija_lexicon.yaml` ;
- normaliser les textes sociaux ;
- réduire les répétitions abusives ;
- détecter Darija arabe, Darija latine et Arabizi ;
- calculer la densité Darija ;
- retourner un dictionnaire compatible avec l’export.

Fonctions importantes :

- `calculate_darija_score(text)` ;
- `detect_darija(text)` ;
- `detect_arabizi_tokens(text)` ;
- `normalize_social_text(text)` ;
- `reduce_excessive_repetitions(text)`.

### `page_analyzer.py`

Analyse une page HTML vérifiée :

- description ;
- type de contenu ;
- langue principale ;
- Darija ;
- contenu parallèle ;
- région ;
- catégorie ;
- licence approximative.

### `language_detector.py`

Détection de langue globale à partir du résultat Darija et des scripts.

### `parallel_text_detector.py`

Détection simple de paires parallèles et contenus français-Darija.

### `category_classifier.py`

Classe une source selon ses mots-clés et son contexte.

### `region_detector.py`

Détecte des indices géographiques marocains.

## `src/storage/`

Module d’écriture des sorties.

### `excel_exporter.py`

Crée le fichier Excel final :

- feuille catalogue ;
- sources prioritaires ;
- liens à recontrôler ;
- hors périmètre ;
- français-Darija ;
- tableau de bord ;
- référentiel.

### `jsonl_exporter.py`

Lit et écrit des fichiers JSONL ligne par ligne.

### `csv_exporter.py`

Exporte les lignes en CSV.

### `cache.py`

Cache JSON avec sauvegarde atomique.

## `src/validation/`

Module de validation technique des liens.

### `url_checker.py`

Effectue :

- `HEAD` ;
- fallback `GET` ;
- suivi des redirections ;
- statut HTTP ;
- type MIME ;
- HTML extrait ;
- erreurs réseau.

### `robots_checker.py`

Vérifie `robots.txt`.

### `content_type_checker.py`

Détermine le type de contenu : HTML, PDF, audio, vidéo, archive, etc.

### `license_checker.py`

Détection simple d’indices de licence.

## `src/audit/`

Module d’audit avancé des fichiers Excel.

Il n’est pas le flux principal du MVP, mais il reste utile pour analyser un catalogue existant.

Responsabilités :

- charger un Excel ;
- vérifier les URL ;
- détecter soft 404 ;
- détecter pages de recherche ;
- détecter pages de connexion ;
- extraire remplacements concrets ;
- exporter un classeur audité.

Fichiers importants :

- `url_auditor.py`
- `audit_exporter.py`
- `excel_loader.py`
- validateurs GitHub, Hugging Face, Kaggle, Zenodo.

## `src/expansion/`

Module historique d’expansion du catalogue.

Il sert à découvrir de nouvelles URLs à partir d’un catalogue existant. Dans le MVP de soutenance, il est secondaire.

Fichiers :

- `discovery_expander.py`
- `duplicate_detector.py`
- `existing_catalog.py`

## `src/scoring/`

### `scorer.py`

Calcule :

- score de pertinence ;
- score de fiabilité ;
- priorité.

## `src/utils/`

Fonctions utilitaires transversales.

### `url_utils.py`

Normalisation, empreintes et déduplication d’URLs.

### `text_utils.py`

Nettoyage texte, normalisation arabe/latin, ratios de scripts.

### `logging_utils.py`

Configuration des logs.

### `retry_utils.py`

Utilitaires de retry.

## `tests/`

Les tests valident :

- extraction YouTube/Facebook ;
- Google dorks ;
- détection Darija ;
- Arabizi ;
- répétitions sociales ;
- export Excel ;
- audit URL ;
- déduplication ;
- scoring.

Commande :

```bash
uv run pytest -q
```
