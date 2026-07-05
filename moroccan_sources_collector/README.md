# Moroccan Sources Collector

Application Python pour decouvrir, verifier, analyser, classer et exporter des liens utiles a la constitution d'un corpus pour une IA marocaine.

Le livrable principal est le fichier Excel :

`data/output/catalogue_sources_marocaines_ai.xlsx`

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Playwright est seulement utilise comme repli lorsque les requetes HTTP classiques ne suffisent pas.

## Commandes

```bash
python -m src.main collect
python -m src.main verify
python -m src.main export
python -m src.main run-all --max-links 200
python -m src.main run-all --force
python -m src.main collect --category darija
python -m src.main collect --category culture
python -m src.main collect --category parallel
python -m src.main verify --retry-errors
```

## Perimetre linguistique

Le francais n'est pas collecte de maniere generale. Une source en francais est conservee seulement si elle contient une traduction, un lexique, des phrases paralleles, des dialogues bilingues, des sous-titres bilingues, des expressions marocaines, ou des donnees culturelles marocaines directement utiles au modele.

Les pages principalement en anglais, espagnol, amazigh ou autres langues sont classees hors perimetre, sauf si elles decrivent ou distribuent un dataset Darija.

## Sorties

- `data/output/catalogue_sources_marocaines_ai.jsonl`
- `data/output/catalogue_sources_marocaines_ai.csv`
- `data/output/catalogue_sources_marocaines_ai.xlsx`

Le classeur Excel contient les feuilles demandees : catalogue, priorites, liens a recontroler, hors perimetre, francais-Darija, tableau de bord et referentiel.

## Detection de la Darija

Le detecteur de Darija se trouve dans `src/analysis/darija_detector.py`. Il utilise un lexique pondere externalise dans `config/darija_lexicon.yaml`, afin que les mots, variantes et expressions puissent etre modifies sans toucher au code Python.

Le detecteur applique plusieurs etapes :

1. normalisation arabe : suppression des diacritiques, suppression du tatweel, normalisation de `أ`, `إ`, `آ`, `ٱ` vers `ا`, de `ى` vers `ي`, de `ؤ` vers `و`, et de `ئ` vers `ي` ;
2. normalisation latine : minuscules, espaces propres, ponctuation non utile retiree, chiffres Arabizi conserves, repetitions excessives reduites ;
3. detection de mots ponderes : niveaux `strong`, `medium`, `weak` ;
4. detection d'expressions de deux a cinq mots ;
5. detection Arabizi stricte : un token doit contenir au moins une lettre latine, au moins un chiffre Arabizi plausible, ne pas etre une annee, un nombre pur, une URL ou un identifiant technique ;
6. detection du contexte marocain ;
7. calcul de sous-scores : lexical, expressions, contexte marocain, Arabizi, densite et penalite d'ambiguite.

Les seuils sont configurables dans `config/settings.yaml` :

```yaml
darija_detection:
  keep_threshold: 65
  review_threshold: 40
  weak_signal_threshold: 20
  minimum_strong_hits: 2
  max_frequency_bonus: 15
  max_context_bonus: 10
  max_arabizi_bonus: 10
```

Pour ajouter un mot, modifier `config/darija_lexicon.yaml` dans la section appropriee :

```yaml
latin:
  strong:
    wach: 4.0
```

Pour ajouter une variante :

```yaml
variants:
  diyal: dyal
```

Pour ajouter une variante arabe :

```yaml
arabic_variants:
  أشنو: اشنو
```

Pour ajouter une expression :

```yaml
phrases:
  latin:
    "chno smitek": 7.0
```

Les mots faibles comme `salam`, `مرحبا` ou `chokran` ne suffisent pas seuls a classer un texte comme Darija avec confiance elevee. Les annees et tokens techniques comme `2024`, `Python3`, `HTML5`, `UTF8`, `HTTP2`, `sha256` ou `ipv4` ne sont pas consideres comme Arabizi.

Un jeu de validation indicatif est disponible dans `data/validation/darija_detection_samples.csv`. Pour l'executer :

```bash
python scripts/evaluate_darija_detector.py
```

Cette evaluation est indicative : les exemples sont courts et artificiels, donc elle sert surtout a detecter les regressions.
