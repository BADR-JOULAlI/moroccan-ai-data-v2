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

## Troisieme lot : demarrage et extraction locale

- Configuration JSON et options explicites pour les chemins, ressources locales,
  modele servi, endpoint OCR et nombres de travailleurs. Le preflight regroupe
  les ressources manquantes avant tout import PDF ou creation de sortie.
- `--help` et `--check-only` fonctionnent sans les modeles. Le package ne charge
  plus ses modules lourds a l'import. Le preflight ne contacte pas le serveur.
- Mode HTML independant des modules PDF, avec profil de mots Unicode explicite
  pour les tests locaux. Le profil spaCy historique reste le defaut; les deux
  tokenisations ne sont pas interchangeables pour les seuils et signatures.
- Les processus utilisent `spawn`. L'extraction HTML et media dispose d'un
  delai reel et nettoie ses travailleurs sur erreur, timeout ou arret. Un echec
  de nettoyage est fatal plutot que transforme en simple rejet.
- Les erreurs d'encodage Windows sont evitees pour les JSONL et logs arabes.
- Les positions et longueurs WARC portent sur les octets archives reels. Les
  tests relisent chaque plage gzip et retrouvent l'URL et le contenu d'origine.
  Les MIME HTML/PDF explicites des en-tetes HTTP ne dependent plus de libmagic;
  les types ambigus sans detection native restent inconnus.
- Une validation WARC refuse les archives vides, les faux enregistrements ARC,
  les champs requis absents et les erreurs detectees. Elle ne demande plus de
  confirmation interactive et ne continue pas apres une erreur. Une reparation
  exige une option explicite et conserve les sauvegardes.
- Le dossier de sortie conserve `run_config.json`. Une configuration differente
  ou un ancien dossier non suivi impose une nouvelle destination pour eviter
  de reutiliser silencieusement les completions d'un autre traitement.
- Le test hors reseau passe par catalogue, acceptations humaines simulees,
  ecriture de WARC reels et extraction HTML complete : quatre pages donnent deux
  textes distincts, apres rejet de la page courte et du doublon. Le resultat
  et la provenance sont verifies avec un et deux travailleurs.

## Travaux restants

Les fichiers des modeles PDF/OCR et un serveur compatible doivent encore etre
fournis et charges pour valider le mode complet. Le preflight verifie leur
presence, pas la validite des poids ni la disponibilite du serveur. Docling
recoit un dossier d'artefacts explicite pour eviter son telechargement de layout
implicite. La serialisation des modeles natifs reels reste a tester.

Le profil spaCy n'a pas ete valide dans l'environnement local de ce lot : ses
imports natifs y bloquent. Le test HTML utilise explicitement Unicode; il ne
demontre pas l'equivalence des deux profils. Chromium reel et le crawl Wget
reseau restent aussi a valider. Le test d'integration genere les WARC a partir
des reponses de fixture; il ne fait pas intervenir un vrai Wget.
