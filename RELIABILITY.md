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

## Deuxieme lot : regles de collecte

- Une politique partagee valide les URL et exclut les plateformes aux etapes
  de decouverte, expansion, redirection et export du collecteur.
- Les regles robots sont consultees avant chaque requete de contenu HTTP. Leurs
  propres redirections sont aussi controlees. Les politiques certaines ont un
  cache d'une heure limite a 512 entrees; les erreurs temporaires ne sont pas
  figees comme des interdictions.
- Le navigateur du collecteur applique les controles URL/robots aux requetes,
  bloque les service workers et resout les redirections HTTP avant navigation.
  Une nouvelle redirection pendant le rendu est refusee et journalisee. Ce
  choix conservateur peut laisser certaines pages dynamiques inaccessibles.
- La verification ignore les anciens caches crees avant ces controles et
  revalide les permissions avant d'utiliser les nouvelles entrees.
- L'export exige une decision humaine positive, une URL HTTP(S) valide du
  perimetre et un statut robots connu comme autorise. Les refus sont comptes
  et expliques dans le resume de la commande.
- Le seuil Darija utilise le texte du corps HTML, sans les metadonnees du head.
  Les exceptions et les PDF a revoir sont explicites. Les rejets linguistiques
  restent dans un fichier distinct pour ne pas perdre les candidats.
- Une selection vide ne declenche plus une deuxieme verification/collecte.
- L'audit historique de plateformes garde un perimetre de diagnostic explicite;
  ses statuts robots ne peuvent plus etre classes comme des ressources validees.

Les tests sont hors reseau. Les tests du navigateur simulent les routes et les
pages; ils ne valident pas un navigateur Chromium reel. Le controle des requetes
du collecteur ne remplace pas la validation de bout en bout du crawl Wget.

## Travaux restants

La preparation des modeles, la configuration du serveur OCR, les positions des
enregistrements WARC et la protection des delais d'extraction necessitent encore
un lot ulterieur. Un essai complet sur des donnees locales fixes doit ensuite
valider l'enchainement catalogue, WARC et extraction, avant un crawl reel.
