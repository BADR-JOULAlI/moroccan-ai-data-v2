# Fiabilisation du pipeline

## Premier lot : integrite des donnees

Ce lot corrige quatre problemes identifies dans l'analyse du depot initial :

- L'extraction WARC ne doit plus s'arreter apres 15 documents par tache. Le
  constructeur du lecteur de segment est partage avec les tests pour verifier
  le chemin utilise en production.
- Tous les codes Wget non nuls, notamment 4 et 8, sont maintenant comptes comme
  des echecs. Le script continue les lots suivants, conserve les entrees des
  lots echoues et retourne le code global 3.
- La normalisation d'URL ne decode plus les caracteres reserves avant le
  decoupage. Les chemins et valeurs de requetes encodes conservent leur sens,
  y compris pour la deduplication.
- Les positions des fins de pages OCR incluent les separateurs ajoutes pendant
  l'assemblage du texte. Le traitement des pages suivantes conserve ainsi le
  texte jusqu'au dernier caractere.

## Validation disponible

Les commandes figurent dans la section Tests du README racine.

Les regressions du collecteur couvrent les chemins encodes, les valeurs de
requete, le double encodage, les URL relatives et les faux doublons.

Les regressions du crawler et de l'extracteur couvrent :

- de vraies archives WARC locales de 24 documents et deux lots de 20 documents;
- les retours Wget 0, 4, 8 et 5 en modes URL, fichier et lots;
- la poursuite des lots apres un echec et les entrees du fichier de reprise;
- l'assemblage OCR puis le lecteur de pages et le filtre reels, avec arabe,
  pages vides, pages manquantes et generations echouees.

Le serveur d'inference et le stockage sont remplaces dans les tests OCR; les
fonctions de traitement du texte restent celles du projet. Les tests WARC
declarent le type MIME dans les en-tetes et ne valident pas la detection native
libmagic. Les tests de crawl utilisent un faux Wget, jamais le reseau.

Ces tests ne valident pas un traitement complet avec les modeles PDF/OCR.

## Prochain lot

- Appliquer le perimetre « sites web seulement » aux liens enfants,
  redirections et exports, en plus des sources initiales.
- Consulter robots.txt avant toute requete de contenu et distinguer refus,
  indisponibilite et erreur reseau.
- Rejeter les URL invalides lors de l'export vers le crawler.
- Relier le seuil `--min-darija-density` au parcours effectivement execute.

La preparation des modeles, la configuration du serveur OCR, les positions des
enregistrements WARC et la protection des delais d'extraction necessitent encore
un lot ulterieur. La documentation historique du collecteur reste egalement a
aligner avec le mode web actuel.
