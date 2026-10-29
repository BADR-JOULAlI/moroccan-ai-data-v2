# Extraction WARC configurable

Le pipeline extrait le texte des archives WARC, applique les filtres qualite,
puis deduplique le corpus avec MinHash. Le mode HTML fonctionne independamment
des modules PDF/OCR. Le mode complet exige leurs ressources locales et un serveur
OCR configure.

## Preparer la configuration

Copier `extraction.example.json` vers `extraction.local.json` et adapter les
chemins des archives, des sorties et du tokenizer local. Les chemins JSON sont
relatifs au fichier; les options de ligne de commande sont relatives au dossier
courant. Les options explicites prennent priorite sur le JSON.

Les archives attendues sont organisees ainsi :

```text
input/<segment>/<site>/*.warc.gz
```

Le JSON peut designer un autre dossier d'entree contenant directement les
sous-dossiers des sites. Le nom du segment est conserve dans les metadonnees.

## Controler puis lancer le mode HTML

Depuis ce dossier :

```bash
uv run --no-project --with-requirements ../requirements-html.txt python process.py --config extraction.local.json --check-only
uv run --no-project --with-requirements ../requirements-html.txt python process.py --config extraction.local.json --validate-warc
```

`--help` fonctionne sans charger les dependances PDF. `--check-only` regroupe les
ressources manquantes, sans creer de sortie ni contacter de serveur. Ce controle
verifie la presence des fichiers; il ne valide pas le contenu des poids.

L'exemple choisit explicitement `word_tokenizer: "unicode"`. Ce profil de mots
est deterministe et fonctionne sans modele linguistique natif. Ses limites de
mots different de celles de `spacy`, qui reste le profil historique par defaut.
Le choix influence les filtres et signatures; utiliser un nouveau dossier de
sortie pour changer de profil. Le tokenizer de comptage des tokens est une
ressource distincte : `tokenizer_path` doit designer un fichier JSON valide.

## Mode PDF/OCR complet

Le mode `full` exige les champs et ressources suivants :

- `pdf_classifier_path` : classifieur XGBoost local;
- `layout_model_path` : XML OpenVINO, accompagne du fichier BIN de meme nom;
- `model_cache` : dossier d'artefacts Docling local;
- `tokenizer_path` : tokenizer de comptage local;
- `ocr_model` : nom du modele servi par l'endpoint;
- `ocr_endpoint` : URL HTTP(S) explicite du serveur.

Renseigner ces champs dans le JSON avant :

```bash
uv run process.py --config extraction.local.json --mode full --check-only
uv run process.py --config extraction.local.json --mode full --validate-warc
```

Cette invocation suppose les dependances completes du projet installees avec
`uv sync`. Le preflight ne prouve ni la validite des poids, ni la disponibilite
du serveur. Le chargement des vrais modeles et leur serialisation dans les
travailleurs restent a valider. Docling recoit un dossier d'artefacts explicite
pour eviter son telechargement de layout implicite.

## Deroulement et sorties

Le traitement HTML utilise le lecteur WARC, l'extracteur Trafilatura avec delai,
la normalisation arabe, les filtres Gopher/C4, puis les signatures, buckets,
clusters et filtres MinHash. Les archives sont lues sans limite d'echantillonnage.

Sous le `output_dir` configure :

```text
run_config.json
data_filtering/html/*.jsonl.zst
base_processing/html/output/*.jsonl.zst
base_processing/html/removed/<filtre>/
minhash/html/{signatures,buckets,remove_ids}/
final_data/html/*.jsonl.zst
logs/stage*/
```

Le mode complet ajoute les sorties PDF, OCR et leur deduplication. Les
metadonnees finales conservent le segment et les URL sources. Les positions et
longueurs WARC sont des plages d'octets relisibles dans l'archive gzip originale.
Les MIME HTTP explicites servent a router HTML et PDF; les types ambigus sans
libmagic restent inconnus.

Une sortie non vide avec une configuration differente ou absente est refusee.
Utiliser `--output-dir` pour une nouvelle destination. La reprise Datatrove
reutilise les completions seulement pour la meme configuration enregistree.

## Validation et erreurs

`--validate-warc` refuse les archives vides, les faux enregistrements ARC et les
erreurs detectees sans demander de confirmation interactive. Pour une tentative
de reparation avec sauvegardes conservees :

```bash
uv run process.py --config extraction.local.json --validate-warc --auto-repair
```

Codes de sortie : `0` succes, `2` configuration ou prerequis invalides,
`1` echec pendant validation ou execution. Un document en echec d'extraction est
trace dans les rejets; un echec d'arret d'un travailleur est fatal au traitement.

## Tests locaux

Depuis la racine du projet crawler, un dossier au-dessus :

```bash
uv run --no-project --with-requirements requirements-test.txt python -m pytest tests crawling/tests -q
```

Le test `tests/test_local_html_pipeline.py` parcourt le collecteur sur reponses
HTTP simulees, une revue humaine de fixture, des WARC reels, puis toute la chaine
HTML. Il verifie filtrage, deduplication, provenance et compteurs avec un et deux
travailleurs. Le tokenizer de comptage du test est genere localement.

Ces tests ne lancent pas de vrai Wget ni de serveur OCR. Le profil spaCy natif,
Chromium reel et le mode PDF/OCR complet restent a verifier dans leur environnement
cible. Le [guide racine](../../../README.md) et le [suivi](../../../RELIABILITY.md)
detaillent les autres validations disponibles.
