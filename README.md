# Moroccan AI Data

Ce depot regroupe un pipeline complet pour construire un jeu de donnees web utile aux projets IA lies au contexte marocain : Darija, arabe marocain, Arabizi, contenus bilingues francais-Darija, culture et patrimoine marocain.

Le mode principal travaille uniquement avec des sites web classiques. Les plateformes YouTube, Facebook, Kaggle, HuggingFace et GitHub sont exclues du flux de collecte/crawl.

L'objectif n'est pas seulement de collecter beaucoup de liens. Le projet met en place une chaine controlee :

```text
Decouverte des sources
-> Verification automatique
-> Validation manuelle humaine
-> Crawl WARC des liens acceptes
-> Extraction et nettoyage du texte
-> Dataset exploitable pour l'IA
```

## Structure du depot

```text
moroccan-ai-data/
|-- moroccan_sources_collector/
|   |-- src/
|   |-- config/
|   |-- tests/
|   `-- data/
|-- crawler_project-main/
|   `-- crawler_project-main/
|       |-- crawling/
|       `-- datatrove_extraction/
|-- AUDIT_CRAWLER_COLLECTOR_INTEGRATION.md
|-- README.md
`-- .gitignore
```

## Composants principaux

### 1. Moroccan Sources Collector

Chemin :

```text
moroccan_sources_collector/
```

Ce module sert a decouvrir, analyser, filtrer et exporter des sites web marocains ou lies au Maroc.

Il fait notamment :

- chargement des seeds depuis `config/seed_sources.yaml` ;
- exploration de catalogues et pages web ;
- normalisation des URLs ;
- deduplication ;
- verification HTTP ;
- analyse linguistique Darija / arabe / Arabizi ;
- scoring de pertinence ;
- export CSV, JSONL et Excel ;
- preparation d'un fichier de validation manuelle.

Fichier d'entree principal :

```text
moroccan_sources_collector/config/seed_sources.yaml
```

Fichier CLI principal :

```text
moroccan_sources_collector/src/main.py
```

### 2. Validation manuelle

Apres l'export, le collecteur genere :

```text
moroccan_sources_collector/data/output/liens_a_valider_manuellement.csv
```

Ce fichier permet de garder la main sur la qualite des sources avant de crawler.

La colonne importante est :

```text
Decision_validation
```

Valeurs recommandees :

```text
accept
reject
maybe
```

Seules les lignes marquees comme acceptees sont envoyees au crawler.

### 3. Crawler WARC

Chemin :

```text
crawler_project-main/crawler_project-main/crawling/
```

Le crawler utilise `wget` pour produire des archives WARC (`.warc.gz`). Ces archives gardent les reponses HTTP completes, ce qui permet ensuite d'extraire du texte proprement.

Script principal :

```text
crawler_project-main/crawler_project-main/crawling/crawl_script_batched.sh
```

Fonctions importantes :

- accepte une URL unique ou un fichier d'URLs ;
- supporte le batching pour de grands fichiers ;
- respecte `robots.txt` par defaut avec `ROBOTS=on` ;
- produit des logs ;
- produit un fichier d'URLs echouees ;
- permet un mode `DRY_RUN=1` sans lancer de crawl reel.

### 4. Extraction Datatrove

Chemin :

```text
crawler_project-main/crawler_project-main/datatrove_extraction/
```

Cette partie transforme les fichiers WARC en donnees texte exploitables.

Elle utilise notamment :

- Datatrove ;
- Trafilatura ;
- filtres qualite ;
- normalisation arabe ;
- traitement HTML ;
- traitement PDF ;
- deduplication MinHash.

Script principal :

```text
crawler_project-main/crawler_project-main/datatrove_extraction/process.py
```

## Installation

### Prerequis

- Python 3.11 ou plus ;
- `uv` ;
- Playwright Chromium pour le collecteur ;
- Bash ou Git Bash pour le crawler ;
- `wget` avec support WARC pour le crawl reel.

### Installer le collecteur

Depuis la racine :

```bash
cd moroccan_sources_collector
uv sync
uv run playwright install chromium
```

Si `uv sync` n'est pas disponible dans ton environnement :

```bash
uv add playwright httpx beautifulsoup4 openpyxl pyyaml pytest pandas requests trafilatura
uv run playwright install chromium
```

### Installer le crawler / extraction

```bash
cd crawler_project-main/crawler_project-main
uv sync
```

## Lancement du collecteur

Depuis :

```bash
cd moroccan_sources_collector
```

### Lancer le MVP complet

```bash
uv run python -m src.main
```

Equivalent explicite :

```bash
uv run python -m src.main mvp --max-links 800 --min-darija-density 0.15
```

Ce flux execute uniquement les seeds de type site web. Les seeds YouTube, Facebook, Kaggle, HuggingFace et GitHub sont ignorees.

La meme politique s'applique aux liens enfants, aux destinations des redirections,
a l'expansion du catalogue et a l'export vers le crawler. Les requetes du
collecteur consultent `robots.txt` avant de demander le contenu. Une interdiction
ou des regles momentanement indisponibles suspendent la collecte de cette URL;
une erreur reseau n'est pas presentee comme une interdiction definitive.

`--min-darija-density` agit sur le texte du corps de la page, sans utiliser le
titre ou le nom de la source pour relever sa densite. L'arabe standard, le
contenu parallele francais-Darija confirme et la culture marocaine attestee dans
le texte restent des exceptions. Les PDF sans texte extrait restent disponibles
pour revue humaine et extraction ulterieure. La valeur `0` desactive seulement
ce filtre linguistique.

Les candidats bloques sont traces dans `data/intermediate/blocked_candidates.jsonl`.
Les pages sous le seuil sont conservees dans `data/intermediate/rejected_linguistic.jsonl`,
avec leur densite et motif, sans alimenter le catalogue actif. Une selection vide
est exportee telle quelle, sans relancer automatiquement la collecte.

Ce flux execute :

```text
Extraction -> Verification -> Export
```

### Commandes separees

Collecter des candidats :

```bash
uv run python -m src.main collect --max-links 200
```

Verifier les candidats :

```bash
uv run python -m src.main verify --max-links 200
```

Exporter les resultats :

```bash
uv run python -m src.main export
```

Tout lancer en mode historique :

```bash
uv run python -m src.main run-all --max-links 200
```

Auditer un fichier Excel de liens :

```bash
uv run python -m src.main audit-links --input catalogue_sources_marocaines_ai.xlsx
```

## Validation manuelle avant crawl

Apres l'export, ouvrir :

```text
moroccan_sources_collector/data/output/liens_a_valider_manuellement.csv
```

Remplir la colonne :

```text
Decision_validation
```

Exemple :

```text
accept
reject
maybe
```

Puis generer l'entree du crawler :

```bash
uv run python -m src.main export-crawler-input
```

Sorties produites :

```text
moroccan_sources_collector/data/output/crawler_urls.txt
moroccan_sources_collector/data/output/crawl_manifest.jsonl
```

`crawler_urls.txt` contient uniquement les URLs acceptees manuellement.

L'export exige aussi une URL HTTP(S) absolue dans le perimetre des sites web
et un statut `Robots_txt` egal a `Oui` dans le fichier de revue. Une decision
`accept` ne permet pas de contourner ces controles. Le resume d'export donne
le nombre de liens retenus, ecartes et leurs motifs. Si les robots etaient
indisponibles, relancer la verification avant de valider le lien.

## Lancement du crawler

Depuis la racine du depot :

```bash
cd crawler_project-main/crawler_project-main/crawling
```

### Tester sans crawler

Commande recommandee avant un vrai crawl :

```bash
DRY_RUN=1 ./crawl_script_batched.sh ../../../moroccan_sources_collector/data/output/crawler_urls.txt moroccan_validated_sources
```

### Lancer le crawl reel

```bash
./crawl_script_batched.sh ../../../moroccan_sources_collector/data/output/crawler_urls.txt moroccan_validated_sources
```

### Parametrer le crawl

Exemple avec profondeur, pause et quota :

```bash
DEPTH=3 WAIT_SECS=2 QUOTA=2G ./crawl_script_batched.sh ../../../moroccan_sources_collector/data/output/crawler_urls.txt moroccan_validated_sources
```

Variables utiles :

```text
DEPTH        Profondeur de crawl, defaut 5
ROBOTS       Respect robots.txt, defaut on
WAIT_SECS    Pause entre requetes
RANDOM_WAIT  Jitter aleatoire, defaut 1
TIMEOUT_SECS Timeout reseau
TRIES        Nombre de tentatives
QUOTA        Quota total, ex: 2G ou 500M
BATCH_SIZE   Taille des batches
DRY_RUN      1 pour tester sans wget
```

Sorties du crawler :

```text
crawler_project-main/crawler_project-main/crawling/crawl_out/<prefix>/
```

Fichiers importants :

```text
<prefix>/*.warc.gz
logs/<prefix>.log
logs/<prefix>.rejected.log
logs/<prefix>.failed_urls.txt
```

## Lancement de l'extraction Datatrove

Le point d'entree charge sa configuration et verifie les ressources avant les
modeles. `--help` fonctionne sans les dependances PDF. `--check-only` produit un
rapport JSON, ne cree aucune sortie et ne contacte aucun serveur OCR.

Pour commencer par le mode HTML, depuis le dossier `datatrove_extraction` :

```bash
uv run --no-project --with-requirements ../requirements-html.txt python process.py --config extraction.example.json --check-only
uv run --no-project --with-requirements ../requirements-html.txt python process.py --config extraction.example.json --validate-warc
```

Adapter d'abord les chemins du JSON vers les WARC et un tokenizer local valide.
Les chemins JSON sont relatifs au fichier de configuration; les chemins passes
en options sont relatifs au dossier courant. L'exemple utilise explicitement le
profil de mots `unicode`, sans modele linguistique natif. Il permet les tests
locaux, mais ses limites de mots ne sont pas identiques a celles de `spacy`.
Le profil historique `spacy` reste la valeur par defaut hors de cet exemple.

Le mode `full` exige en plus le classifieur PDF, le XML et les poids BIN
OpenVINO, un dossier d'artefacts Docling local et les champs `ocr_model` et
`ocr_endpoint`. Ces valeurs ne sont plus des chemins HPC ou serveurs implicites.
Le controle de presence ne charge pas les poids et ne prouve pas que le serveur
est joignable. Le mode PDF/OCR complet reste a valider avec ces ressources.

Les parametres sont enregistres dans `run_config.json`. Pour changer de profil,
de segment, de chemins ou de nombre de travailleurs, choisir un nouveau dossier
de sortie; les sorties existantes d'une autre configuration ne sont pas reutilisees.

Les WARC doivent etre places dans :

```text
crawler_project-main/crawler_project-main/datatrove_extraction/input/<segment>/
```

Exemple :

```text
datatrove_extraction/input/segment-2026-07/site_001/*.warc.gz
```

Copier `extraction.example.json` vers `extraction.local.json`, puis adapter les
chemins d'entree, de sortie et du tokenizer. Avec ces ressources preparees :

```bash
cd crawler_project-main/crawler_project-main/datatrove_extraction
uv run process.py --config extraction.local.json
```

Valider les WARC avant traitement :

```bash
uv run process.py --config extraction.local.json --validate-warc
```

Valider et tenter une reparation automatique :

```bash
uv run process.py --config extraction.local.json --validate-warc --auto-repair
```

Sorties principales :

```text
crawler_project-main/crawler_project-main/datatrove_extraction/output/<segment>/
```

## Flux complet recommande

Depuis la racine :

```bash
cd moroccan_sources_collector
uv sync
uv run playwright install chromium
uv run python -m src.main mvp --max-links 800 --min-darija-density 0.15
```

Ensuite :

```text
1. Ouvrir data/output/liens_a_valider_manuellement.csv
2. Mettre accept/reject/maybe dans Decision_validation
3. Sauvegarder le fichier
```

Puis :

```bash
uv run python -m src.main export-crawler-input
```

Crawler :

```bash
cd ../crawler_project-main/crawler_project-main/crawling
DRY_RUN=1 ./crawl_script_batched.sh ../../../moroccan_sources_collector/data/output/crawler_urls.txt moroccan_validated_sources
./crawl_script_batched.sh ../../../moroccan_sources_collector/data/output/crawler_urls.txt moroccan_validated_sources
```

Extraction :

```bash
cd ../datatrove_extraction
uv run process.py --config extraction.local.json
```

## Tests

Tests du collecteur :

```bash
cd moroccan_sources_collector
uv run pytest -q
```

Validation syntaxe du crawler avec Git Bash :

```bash
"C:\Program Files\Git\bin\bash.exe" -n crawler_project-main/crawler_project-main/crawling/crawl_script_batched.sh
```

Compilation rapide du script d'extraction :

```bash
uv run python -m py_compile crawler_project-main/crawler_project-main/datatrove_extraction/process.py
```

Tests de regression du crawler et de l'extraction, depuis leur racine :

```bash
cd crawler_project-main/crawler_project-main
uv run --no-project --with-requirements requirements-test.txt python -m pytest tests crawling/tests -q
```

Ces tests utilisent des archives WARC generees localement, un faux `wget` et
des reponses OCR simulees. Ils ne lancent aucun crawl ni telechargement de modele.
Bash est requis pour les tests du script de crawl (Git Bash sous Windows).
Le fichier `requirements-test.txt` suffit pour ces regressions sans installer
l'ensemble des dependances PDF/OCR du projet.

Le test `tests/test_local_html_pipeline.py` execute aussi le collecteur avec
des reponses HTTP locales simulees, une revue humaine de test, de vraies archives
WARC, puis l'extraction HTML, les filtres qualite et MinHash reels. Il verifie
le meme resultat avec un et deux travailleurs. Son petit tokenizer de tokens
est genere localement pour le test, sans representer un modele de production.

L'extraction normale lit desormais tous les documents du segment, sans plafond
de 15 documents par tache. Tout code Wget non nul produit un bilan d'echec, ajoute
les entrees du lot concerne au fichier de reprise et termine le script avec le
code 3. La reprise se fait au niveau du lot : certaines URL du lot peuvent deja
avoir ete telechargees.

Voir [le suivi de fiabilisation](RELIABILITY.md) pour le perimetre des corrections
et les points qui restent a traiter avant un traitement complet.

Le mode navigateur du collecteur applique aussi les controles URL/robots aux
requetes et resout les redirections HTTP avant navigation. Une redirection qui
apparait seulement pendant le rendu est refusee et journalisee, meme si sa
destination serait autorisee. Les tests de cette protection utilisent des
routes simulees; ils ne remplacent pas un essai avec Chromium.

## Perimetre linguistique V1

Pour cette premiere version, la collecte vise principalement :

1. Arabe standard.
2. Darija marocaine ecrite en alphabet arabe.
3. Darija marocaine ecrite en alphabet latin.
4. Darija ecrite en Arabizi.
5. Contenus mixtes arabe-Darija.
6. Contenus paralleles francais-Darija.
7. Dictionnaires, lexiques, tableaux et phrases traduites entre le francais et la Darija.

Le francais ne doit pas etre collecte de maniere generale.

## Regles de conservation des sources en francais

Une source en francais peut etre conservee uniquement si elle respecte au moins une des conditions suivantes :

- elle contient une traduction vers la Darija ;
- elle contient un dictionnaire francais-Darija ;
- elle contient des phrases alignees francais-Darija ;
- elle explique des expressions marocaines ;
- elle contient des dialogues en francais et en Darija ;
- elle contient des sous-titres ou transcriptions bilingues ;
- elle decrit directement la culture, les traditions ou le patrimoine marocain ;
- elle permet de produire des paires utiles pour la traduction ou le fine-tuning.

## Exclusions

Exclure les pages entierement en francais qui n'ont aucun rapport direct avec :

- la Darija ;
- la langue arabe marocaine ;
- la culture marocaine ;
- les traditions marocaines ;
- les donnees utiles a l'entrainement du modele.

## Notes importantes

- Les fichiers `.env` ne doivent pas etre commits.
- Les sorties de crawl `crawl_out/` ne sont pas versionnees.
- Les outputs du collecteur dans `data/output/` ne sont pas versionnes.
- Les caches et modeles locaux ne sont pas versionnes.
- La validation manuelle est une etape volontaire : elle evite de crawler des liens inutiles ou hors perimetre.
