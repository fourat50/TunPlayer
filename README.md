# TunPlayer

Lecteur IPTV de bureau, développé d’abord pour Linux. Interface française graphite et citron vert, panorama vectoriel original, cartes illustrées et bibliothèque locale. Projet inspiré des usages d’[UHF](https://getuhf.com/), avec une identité et une implémentation propres.

**Version 1.3.1 : démarrage vidéo stabilisé, catégories protégées par PIN, fermeture du contenu clarifiée, volume visible et double-clic pour le plein écran. Radio, IPTV, téléchargements et distribution autonome Linux.**

## Démarrer sous Linux

Depuis votre session graphique :

```bash
git clone https://github.com/fourat50/TunPlayer.git
cd TunPlayer
./start.sh
```

Le fichier `TunPlayer.desktop` sert aussi de lanceur ; ses chemins correspondent au dossier d’origine `/home/fourat/Desktop/TunPlayer` et doivent être adaptés si vous installez le projet ailleurs. Votre gestionnaire de fichiers peut demander de l’autoriser comme lanceur de confiance.

Dépendances utilisées sur cette machine : Python 3.12, PyGObject / GTK 3.24, libmpv 2 et FFmpeg. Aucune dépendance pip n’est nécessaire. Sur Debian, Ubuntu ou Mint, si elles manquent :

```bash
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 libmpv2 ffmpeg
```

L’application impose X11 pour GTK et utilise X11 / EGL pour la vidéo mpv, avec repli logiciel X11 si nécessaire. Sous Wayland, XWayland doit être disponible. La sortie mpv est limitée à `gpu,x11`, sans retour à la sélection automatique d’un autre environnement graphique. L’identifiant de la zone vidéo GTK est obligatoire : si cette zone est indisponible, une erreur est affichée et aucun lecteur autonome n’est lancé. `start.sh` emploie le Python système, qui dispose des modules GTK installés par la distribution.

## Paquet Linux .deb

Les paquets publies se trouvent dans les [releases GitHub](https://github.com/fourat50/TunPlayer/releases). Pour installer un fichier telecharge, depuis son dossier :

```bash
sudo apt install ./tunplayer_1.0.0_all.deb
```

Lancez ensuite **TunPlayer** depuis le menu des applications, ou avec `tunplayer`. APT installe les bibliotheques declarees dans le paquet. Celui-ci contient le programme Python et les ressources, sans profil utilisateur ni playlist. Il vise Debian, Ubuntu et Linux Mint disposant de Python >= 3.10 et des dependances indiquees. La verification locale a ete faite sur Linux Mint 22.3, base Ubuntu 24.04 ; aucune validation sur les autres distributions n'est revendiquee.

Pour supprimer le programme tout en gardant votre profil :

```bash
sudo apt remove tunplayer
```

### Construire et verifier le paquet

Les outils d'empaquetage sont sur `main`. Le programme embarque est lu dans le tag fige `v1.0.0` : le tag n'est pas deplace et le contenu de l'application reste identique a cette version.

```bash
sudo apt install dpkg fakeroot desktop-file-utils
python3 scripts/build_deb.py --ref v1.0.0
python3 scripts/verify_deb.py dist/tunplayer_1.0.0_all.deb --install-test
```

La construction ne demande pas les droits root. Elle produit le `.deb` et `dist/SHA256SUMS`, avec dates de source fixes et proprietaires root dans l'archive. Deux constructions identiques ont ete comparees octet par octet. Le test d'installation utilise une base dpkg et une racine temporaires : il ne modifie pas votre installation systeme. Une simulation APT distincte verifie la resolution des dependances sur la machine courante.

Le paquet installe `/usr/bin/tunplayer`, `/usr/share/tunplayer`, une entree dans le menu et une icone standard. Le lanceur utilise le Python systeme ; aucune dependance pip et aucun script de maintenance privilegie ne sont ajoutes. Le demarrage `--help`, les chemins, les permissions, les MD5 et le fichier desktop sont verifies. Le rendu graphique complet reste a tester dans une session de bureau.

### Publier la release

Depuis un terminal ou GitHub CLI est installe et authentifie :

```bash
python3 scripts/publish_release.py --tag v1.0.0 --push-source
```

Cette commande pousse les outils de construction sur `main`, construit et verifie le paquet depuis le tag existant, prepare une release brouillon, joint le `.deb` et `SHA256SUMS`, puis telecharge ces deux fichiers pour les comparer aux originaux avant de publier la release. Un tag different ou un fichier distant incompatible arrete la publication ; aucun fichier existant n'est ecrase automatiquement. Les notes sont dans `packaging/releases/v1.0.0.md`.

## Version Linux autonome

Une recette distincte embarque Python 3.12, PyGObject / Cairo, GTK 3, mpv,
FFmpeg et leurs bibliothèques, les décodeurs SVG, les certificats HTTPS et
une police. Le programme reste celui du tag **v1.0.0**, sans changement du
lecteur ni des données utilisateur. Le petit `.deb` existant reste disponible.

Cette première construction cible **Ubuntu 24.04 / Linux Mint 22, x86_64**.
Le noyau, glibc 2.39 ou ultérieure, le serveur X11 / XWayland et les pilotes
matériels restent fournis par le système. Ce n’est pas une promesse de
compatibilité avec toutes les distributions. La séparation des bibliothèques
système suit le [principe des paquets Linux autonomes](https://docs.appimage.org/introduction/concepts.html).

Depuis le projet, sur la machine de construction disposant des dépendances :

```bash
/usr/bin/python3 scripts/build_standalone.py --output-dir dist/linux-standalone
/usr/bin/python3 scripts/verify_standalone.py dist/linux-standalone/tunplayer_1.0.0+standalone1_amd64.deb
```

La recette refuse d’écraser un dossier de construction existant. Elle produit :

- `tunplayer_1.0.0+standalone1_amd64.deb` : installation dans `/opt/tunplayer`, entrée dans le menu ; remplace le paquet léger sans toucher au profil ;
- `TunPlayer-1.0.0-linux-x86_64-standalone.tar.gz` : archive portable à extraire, puis lancer `./AppRun` sans sudo ;
- `Standalone-SHA256SUMS` : empreintes des deux fichiers.

Installation du paquet autonome :

```bash
sudo apt install ./tunplayer_1.0.0+standalone1_amd64.deb
```

APT n’a plus à installer Python, GTK, mpv ou FFmpeg pour cette variante.
Le paquet déclare seulement sa version minimale de glibc et recommande
XWayland. Le runtime reste privé ; les autres logiciels ne sont pas modifiés.
Ses composants doivent être mis à jour en reconstruisant le paquet autonome.

`build-info.json` conserve le commit de l’application et les versions des
paquets embarqués ; `licenses/` contient leurs notices et licences. Les sources
des paquets sont référencées dans le fichier README fourni avec le runtime.

La vérification extrait le vrai `.deb` dans un chemin avec espaces et accents,
contrôle la résolution des dépendances ELF vers les bibliothèques privées,
importe GTK, décode un SVG, charge les certificats, décode le média local avec
FFmpeg et mpv et teste l’installation / suppression dans une racine dpkg
temporaire. Elle ne modifie pas l’installation système. La lecture graphique
complète et les autres distributions restent à valider dans une session de bureau.

Pour ajouter les fichiers autonomes vérifiés à la release 1.0.0 existante,
depuis un terminal connecté à GitHub CLI :

```bash
python3 scripts/publish_standalone.py --push-source
```

Cette commande vérifie le rapport local et les empreintes, compare le tag
GitHub au programme embarqué, pousse `main`, ajoute les deux fichiers avec
leurs empreintes et instructions, puis télécharge les fichiers publiés pour
les comparer. Les fichiers existants ne sont pas écrasés. Les notes de release
sont complétées après vérification des téléchargements.

## Radio : pays et catégories

Ouvrez **Radio** dans **Votre espace**. Aucun import de playlist ni compte
n’est nécessaire. Sélectionnez un **pays** dans la colonne latérale et un
**genre** dans les catégories ; les deux filtres se combinent. La recherche
du haut porte sur le nom des stations. Un rappel indique les filtres actifs,
y compris « Mes radios » lorsqu’il est sélectionné. Les tris proposent popularité, nom
et pays, avec des pages de 40 résultats. Le nombre de stations affiché concerne
la page courante. Les catégories sont les tags libres
de l’annuaire, avec les 150 genres les plus représentés.

Les compteurs globaux de genres ne sont pas affichés : ils ne représentent
pas le résultat d’un filtre combinant pays, genre, recherche et favoris.
« Indie » est un genre musical. Une sélection vide peut être élargie à tous
les pays ou à tous les genres sans effacer les autres critères.

**Écouter** ouvre le lecteur intégré en mode audio, avec le nom, le pays et
les genres de la station. Les commandes restent visibles. **Stations** ouvre
la liste pendant la lecture ; Précédent / Suivant parcourent la sélection
chargée. **Parcourir les radios** revient à l’annuaire en laissant l’audio
continuer ; Retour et Stop coupent le flux et reviennent à Radio.

Le cœur ajoute la station à **Mes radios**, une sélection locale séparée
des favoris IPTV. Elle reste consultable sans annuaire disponible. Les pages
déjà consultées peuvent aussi être affichées depuis le cache en cas de
coupure, avec une indication explicite. L’écoute des flux nécessite Internet.
Les logos non disponibles utilisent un visuel de remplacement.

OpenRadio est une application utilisant **Radio Browser**, comme l’indiquent
son [README](https://github.com/raj-khan/openradio) et son
[fournisseur de stations](https://github.com/raj-khan/openradio/blob/main/lib/stations/radio-browser-provider.ts).
TunPlayer intègre directement cette même API publique, sans héberger OpenRadio
ni reprendre son interface. Les appels suivent la [documentation Radio Browser](https://docs.radio-browser.info/).
Les pays, tags et recherches sont chargés hors du fil GTK, avec délais bornés,
miroirs HTTPS et cache disque limité à 48 réponses. Les stations marquées en
échec, les URL non HTTP(S) et les doublons d’une page sont écartés.

Cette fonctionnalité appartient aux sources **1.1.0**. Les paquets de la
release 1.0.0 ne la contiennent pas. Pour construire le programme courant,
utilisez `--ref HEAD` avec les scripts de construction, après avoir commité
les sources. Pour publier la version Radio avec les fichiers déjà vérifiés :

```bash
python3 scripts/publish_standalone.py --directory dist/radio-1.1.0 --push-source
```

La commande pousse `main` et le tag `v1.1.0`, qui désigne le commit du paquet,
prépare la release en brouillon, joint les installateurs et leurs empreintes,
puis vérifie les téléchargements avant publication. Les versions et fichiers
existants ne sont pas écrasés.

## Télécharger films, saisons et épisodes

- **Film** : ouvrez sa fiche puis cliquez sur **Télécharger**.
- **Épisode** : utilisez l’icône de téléchargement dans sa ligne.
- **Saison** : choisissez une saison dans sa liste, puis **Télécharger la saison**.
  Tous ses épisodes sont ajoutés, même lorsqu’une recherche ou une pagination en masque certains.

Choisissez le dossier de destination. La rubrique **Téléchargements** dans
**Votre espace** affiche les transferts et leur progression. Un transfert
s’exécute à la fois, hors du fil GTK. Vous pouvez mettre en pause, reprendre,
annuler, ouvrir le dossier et lire un fichier terminé directement dans TunPlayer.
Les épisodes sont rangés dans des dossiers par série et saison.

À la fermeture, les transferts sont mis en pause ; **Reprendre tout** permet
de relancer la file. La reprise d’un fichier HTTP utilise une plage validée
et un ETag fort pour éviter de mélanger deux versions du fichier. Sinon le
transfert recommence au début. Les téléchargements HLS / DASH passent par
FFmpeg et reprennent depuis le début. Les fichiers existants ne sont pas
écrasés et un transfert incomplet reste séparé du fichier terminé.

L’historique est conservé dans `downloads.json` dans le profil de l’application,
avec des permissions privées. Les liens peuvent contenir les identifiants du
fournisseur ; ils ne sont pas affichés dans la liste des transferts. Le direct
et les radios gardent leur fonction d’enregistrement existante.

Le catalogue et le lecteur utilisent désormais des [Gtk.Stack](https://docs.gtk.org/gtk3/class.Stack.html)
sans transition : une seule vue est affichée à la fois. L’écran Radio est
également séparé de la fenêtre vidéo native. Le flux est lancé après la mise
en place de sa surface ; Stop et les changements rapides annulent un lancement
en attente. La navigation latérale peut défiler si la hauteur disponible diminue.

Les tests de téléchargement utilisent des réponses HTTP contrôlées et une
conversion HLS locale avec le vrai FFmpeg. Les lancements différés et la lecture
locale sont testés ; le rendu X11 complet reste à vérifier depuis le bureau avec
`python3 scripts/smoke_ui.py`. Les mécanismes de reprise suivent le
[protocole HTTP](https://www.rfc-editor.org/rfc/rfc9110.html#name-range) et le
suivi de transfert utilise la [sortie de progression de FFmpeg](https://ffmpeg.org/ffmpeg.html#Generic-options).

## Interface

L’interface adopte une palette graphite, ivoire et citron vert. L’accueil **Découvrir** présente uniquement trois rangées d’affiches : derniers films ajoutés, dernières séries ajoutées et Tendances. Il ne comporte ni colonne de catégories ni panneau de filtres. Les rangées défilent horizontalement ; **Tout voir** ouvre la rubrique correspondante avec le tri des ajouts récents. La recherche de l’en-tête filtre aussi ces sélections.

Les chaînes présentent le logo fourni par leur source, cadré entièrement. Les films et les séries utilisent des affiches verticales. Un monogramme coloré prend le relais si le visuel manque ou échoue. Chaque carte conserve son badge, ses métadonnées disponibles et un favori accessible au clavier. Les noms longs disposent d’une infobulle. Les images sont chargées en arrière-plan et mises en cache localement.

Le lecteur occupe la fenêtre avec une zone vidéo intégrée, un panneau de contenus repliable et une barre anthracite sobre sous la vidéo. Le titre et le statut apparaissent en haut des commandes, à côté du retour et du type de contenu. La progression et le temps partagent une ligne fine. La rangée inférieure réunit le contenu précédent, les déplacements de dix secondes / Lecture-Pause / Stop au centre et le contenu suivant. Le volume, les pistes, les réglages et le plein écran restent accessibles dans l’en-tête compact du lecteur. Le bouton Lecture / Pause blanc constitue le repère principal. Les noms des contenus voisins restent visibles avec des ellipses et une infobulle complète.

Le menu **Réglages** contient le format d’image, le rechargement du flux et REC. Son ouverture maintient les commandes visibles ; Échap le ferme et la navigation clavier reste disponible dans ce menu. Lors d’un enregistrement, le bouton Réglages prend une teinte rouge et son infobulle le signale. L’en-tête général, le pied de page et la navigation latérale sont masqués dans le lecteur, puis restaurés au retour dans la bibliothèque. Les commandes restent accessibles par leurs infobulles et noms accessibles, et disparaissent après cinq secondes d’inactivité.

Les écrans vides, les sources et les préférences reprennent la même identité visuelle.

Les illustrations Cairo et les 35 icônes SVG fonctionnent sans téléchargement. La feuille de style et les fichiers SVG ont été validés, et les dessins rendus dans une image pour inspection. La capture de l’application complète nécessite toujours une session graphique accessible.

## Utilisation

1. Cliquez sur **Ajouter une source**.
2. Donnez un nom à la source, puis choisissez une playlist M3U locale / distante ou un serveur Xtream avec identifiant et mot de passe.
3. Retrouvez le direct dans **Télévision**, les vidéos dans **Films** et les séries dans **Séries**. À la première ouverture de Séries pour une ancienne source Xtream, le catalogue des séries est récupéré automatiquement, sans réimporter le direct ni les films. **Actualiser les séries** permet de réessayer ou de mettre à jour ce seul catalogue.
4. Utilisez la recherche, les filtres par source, le menu vertical des catégories et le cœur pour composer vos favoris. Plusieurs mots peuvent être combinés ; ils sont recherchés dans le titre, la catégorie et le genre, sans accents ni distinction de casse.
5. Dans **Mes sources**, importez votre guide XMLTV depuis un fichier XML non compressé ou une URL. Les `channel` du guide doivent correspondre aux `tvg-id` des chaînes.
6. Cliquez sur une affiche ou sur le bouton d’information pour consulter la fiche. **Regarder** lance directement la lecture ; les séries Xtream proposent leurs saisons, épisodes et une action pour continuer.

Sans source, les trois sections de **Découvrir** restent vides avec une indication de connexion des sources. Aucune chaîne ni abonnement n’est fourni. Le média local de démonstration reste utilisé dans les tests.

### Navigation et réactivité

- Dans les rubriques Télévision, Films, Séries, Favoris et Historique, la colonne **Catégories** affiche les catégories et leurs compteurs pour la rubrique et la source sélectionnées. La recherche de catégorie filtre cette liste localement ; **Tout afficher** retire la sélection. Le menu utilise un modèle GTK afin de ne pas créer un bouton par catégorie.
- Faites glisser la séparation verticale à droite des **Catégories** pour ajuster leur largeur. Elle est mémorisée entre les lancements, de 150 à 480 pixels selon l’espace disponible. Le panneau et sa séparation disparaissent dans Découvrir et les pages sans catégories.
- La flèche à côté de **Votre espace** réduit la navigation principale en barre d’icônes. Les rubriques restent accessibles avec des infobulles. Le choix est mémorisé au prochain lancement.
- La recherche est conservée séparément dans chaque rubrique : une recherche de film ne masque plus involontairement les séries.
- Les requêtes du catalogue, les compteurs et les catégories s’exécutent hors du fil GTK. Les filtres avancés sont calculés uniquement lorsqu’ils sont ouverts. Une nouvelle recherche annule les résultats dépassés.
- Les cartes sont construites par petits lots, avec annulation du lot précédent lors d’un changement de page. Les icônes SVG sont réutilisées, et les images décodées disposent d’un cache mémoire de 64 Mo avec vignettes limitées à 360 × 540 pixels.
- Les réglages, favoris et positions sont enregistrés dans une file d’écriture indépendante. Une transaction d’import ne bloque plus l’interface pour attendre l’écriture du volume ou de la reprise. Les modifications déjà acceptées sont terminées à la fermeture.

Le retour d’une fiche, des préférences ou du lecteur conserve désormais la page de chaque rubrique, sa recherche, ses filtres et la position de défilement. Cette mémoire reste limitée à la session, avec au plus 32 positions. Si vous commencez à défiler pendant la construction d’une page, votre action prend priorité sur sa restauration automatique.

Les résultats disposent d’un cache mémoire LRU de 12 pages pendant 15 secondes. Les changements enregistrés dans l’application rendent les anciennes versions inéligibles. Les comptages sont réutilisés entre pages d’une même sélection. Après affichage, seule la page suivante est préparée en arrière-plan ; une nouvelle action annule cette préparation. Elle lit uniquement la bibliothèque locale, sans ouvrir de flux vidéo ni télécharger les affiches de la page suivante.

La création des cartes vise des lots de quatre éléments et un budget de quatre millisecondes par passage, à une priorité laissant passer les événements et le rendu GTK. Ce budget peut être dépassé par la création d’un seul widget et ne constitue pas une garantie de fréquence d’affichage. La recherche utilise le regroupement natif de saisie de GTK, sans temporisation supplémentaire. Les cœurs se mettent à jour sur les cartes concernées après enregistrement ; la liste est reconstruite lorsqu’un filtre de favoris impose de recalculer ses résultats.

La récupération ciblée des séries reconnaît aussi les listes enveloppées et les dictionnaires à clés numériques de certains fournisseurs. Les épisodes peuvent être reçus par saison, sous forme de listes imbriquées ou sous forme de liste plate. Une erreur reste visible avec possibilité de réessayer ; une réponse vide ne supprime pas un catalogue de séries déjà disponible.

### Recherche et affichage

- Filtres combinables : source, catégorie, type de contenu, genre, année, langue, qualité déclarée, note minimale, favoris, jamais regardés et présence d’un visuel fourni.
- **Plus de filtres** ouvre les critères détaillés. Les critères sans métadonnées disponibles sont désactivés. Une qualité affichée est celle déclarée dans les métadonnées ou le titre ; elle n’est pas une mesure du flux.
- Tris : titre A–Z / Z–A, ajouts récents, derniers regardés, note et année. Les derniers tris dépendent des métadonnées réellement fournies.
- **Grille** pour les affiches, **Liste** pour parcourir rapidement le catalogue, option **Compact**, et pagination de 30 / 60 / 120 résultats. Ces préférences d’affichage sont mémorisées au prochain lancement.
- Les filtres restent conservés dans chaque rubrique pendant la session. Le bouton de réinitialisation efface la recherche et les critères.
- Dans une série Xtream, un sélecteur de saison et une recherche d’épisode facilitent le parcours. Les épisodes ont leur propre reprise de lecture et peuvent être ajoutés aux favoris.

Un import complet Xtream utilise les actions de direct, VOD et séries ; la récupération ciblée des séries ne fait que les deux requêtes de catégories et de séries. Les épisodes sont demandés à l’ouverture d’une série, puis conservés dans la bibliothèque. Si un chargement échoue, les épisodes déjà chargés restent disponibles. Les imports complets restent transactionnels : une réponse de catalogue invalide, y compris pour les séries, fait échouer l’actualisation et conserve la bibliothèque précédente.

Pour les M3U, les liens `/series/`, les types explicites et les noms `S01E02` sont classés dans Séries ; il s’agit alors de fichiers directement lisibles. Leur regroupement automatique en saisons n’est pas implémenté. Les logos proviennent de `tvg-logo`, les langues de `tvg-language` ou `language`, et les autres métadonnées sont utilisées lorsqu’elles existent.

### Nouveautés et Tendances

**Découvrir** charge au plus douze affiches par rangée, en arrière-plan. Les ajouts récents suivent la date fournie par la source ; sinon, la première date d’import connue par cette version de TunPlayer sert de repli. Un renommage ou une actualisation ne modifie pas cette date de première arrivée. Pour les anciennes entrées sans date connue, l’interface indique que la source doit être actualisée.

**Tendances** classe les films et séries selon les notes disponibles chez vos fournisseurs, puis leur date d’ajout. Sans notes, la sélection utilise les ajouts récents. Ce n’est pas un classement mondial en temps réel et aucune API extérieure n’est appelée pour inventer une popularité.

### Fiches et progression

Les fiches affichent une grande affiche, le synopsis, le genre, l’année, la note, la durée, la distribution et la réalisation lorsque la source les fournit. Elles proposent la lecture, la reprise ou le revisionnage, les favoris et une actualisation manuelle. Les séries montrent aussi les saisons, les épisodes et leur état de progression.

Les informations Xtream sont récupérées en arrière-plan avec `get_vod_info` ou `get_series_info`. Le cache des films est réutilisé pendant 24 heures ; celui des séries et épisodes pendant une heure. Une erreur laisse la fiche enregistrée et la lecture disponibles. Les métadonnées enrichies sont conservées lors des actualisations du catalogue. Les playlists M3U utilisent leurs seules informations disponibles : aucune donnée manquante n’est inventée.

Un film ou épisode arrivé à sa fin est marqué comme terminé. **Continuer** reprend le dernier épisode inachevé ou propose le suivant, y compris lors d’un changement de saison.

### Actualiser une source

Dans **Mes sources**, **Actualiser** relit la playlist locale, son URL ou le compte Xtream enregistré. **Modifier** permet de changer le nom, l’adresse ou les identifiants avant de réimporter.

Les favoris, l’historique et les positions sont conservés pour les contenus identifiés par leur URL, leur identifiant Xtream ou un `tvg-id` non ambigu dans le même type de contenu. Une rotation de jeton dans l’URL peut ainsi préserver votre sélection. Les entrées nouvelles sont ajoutées et les entrées retirées par la source sont supprimées. Un import vide, invalide ou échoué ne remplace pas la bibliothèque. Sans identifiant fiable, un flux dont l’URL change est traité comme nouveau ; aucun rapprochement approximatif par nom n’est effectué.

La base de la version 0.1 est migrée automatiquement sans changer les identifiants ni les favoris. Comme cette version n’enregistrait pas les paramètres de connexion, utilisez **Reconnecter** une première fois pour ses sources existantes.

### Lecture

- Moteur libmpv : prise en charge des formats selon les codecs du système ; décodage matériel automatique si disponible.
- Pause, arrêt, réessai manuel, volume et format d’image mémorisés, déplacement dans les médias avec durée, plein écran. Le bouton **Retour au lecteur** reste accessible pendant la navigation dans la bibliothèque.
- Choix des pistes audio et des sous-titres intégrés ; ajout de sous-titres externes.
- Historique et position de lecture sauvegardés toutes les dix secondes et à la fermeture. Choix de reprise pour les films et les épisodes déjà commencés ; reprise automatique lors des reconnexions et de l’enchaînement des épisodes. Une ouverture échouée ou une reprise encore en cours ne remet plus la position enregistrée à zéro.
- Enregistrement manuel avec FFmpeg, sans réencodage, vers un fichier Matroska (`.mkv`). Le lecteur reste sur le contenu enregistré jusqu’à l’arrêt de REC. La source peut ouvrir une seconde connexion côté fournisseur pour l’enregistrement.
- Erreurs de lecture et d’import affichées dans l’application. Un fournisseur réel reste nécessaire pour valider votre service IPTV.

**Parcourir pendant la lecture :** le panneau de droite s’ouvre sur la catégorie du contenu regardé, dans la même source. Le bouton **Chaînes**, **Films**, **Séries** ou **Épisodes** pendant la lecture d’un épisode, ainsi que la croix, permettent de masquer / réafficher la liste ; ce choix est mémorisé. Le panneau conserve la lecture pendant les changements de catégorie, les recherches et la pagination. Il affiche au plus 40 éléments par page et se positionne sur le contenu en cours. `Ctrl+K` ouvre la recherche de ce panneau pendant la lecture.

Pour une série Xtream, le panneau présente les épisodes de la série regardée. **Toutes les séries** revient aux séries de cette catégorie ; le sélecteur permet de changer de catégorie. Cliquer sur une série charge ses épisodes en arrière-plan sans changer le média en cours. Cliquer sur un épisode lance celui-ci dans le même lecteur. Les épisodes déjà enregistrés sont réutilisés ; une série sans épisodes locaux est récupérée auprès de sa source.

**Précédent / Suivant :** les deux commandes indiquent le nom exact de la chaîne, du film ou de l’épisode cible. Pour les chaînes et films, elles suivent l’ordre alphabétique de la catégorie et de la source du contenu en cours. Pour les épisodes, elles suivent les saisons et numéros d’épisode de la même série, y compris entre saisons. Parcourir une autre catégorie ne modifie pas ces cibles tant qu’un nouveau média n’a pas été lancé. Une commande sans cible est désactivée : aucune boucle automatique entre le premier et le dernier élément. La protection d’un enregistrement en cours reste appliquée lors d’un changement de média.

Le panneau est redimensionnable en faisant glisser sa séparation ; la largeur choisie est mémorisée entre les lancements (préférence de 240 à 460 pixels selon les limites natives de GTK). Sous 1 120 pixels de largeur de lecteur, il se replie automatiquement sans effacer cette préférence. Le bouton de liste ou `B` permet de le rouvrir volontairement dans une petite fenêtre. Une préférence de fermeture explicite reste respectée lors des agrandissements. Le contenu en cours est indiqué au-dessus de la liste et sélectionné lorsqu’il figure dans la page.

**Choix de reprise :** un contenu non terminé déjà regardé au moins dix secondes propose **Reprendre à…**, **Depuis le début** et **Annuler**. Annuler laisse le média en cours intact. Les reconnexions, le réessai manuel du même média et l’enchaînement automatique conservent leur reprise sans dialogue supplémentaire. Un contenu terminé redémarre au début.

**États et diagnostic :** le lecteur affiche des messages simples : Connexion, Lecture en cours, Pause, Mise en mémoire tampon ou Reconnexion. **Réglages → Diagnostic de lecture** affiche les codecs, la résolution, les images par seconde, le tampon, les images perdues et la sortie vidéo. Ces informations ne sont interrogées que lorsque le diagnostic est ouvert, au plus toutes les deux secondes, ou à son ouverture.

**Retour pendant la lecture :** les boutons **Retour** et **Stop**, dans les commandes du lecteur, arrêtent le flux et annulent toute reconnexion ou proposition d’épisode suivant. Pour le direct, ils reviennent à la rubrique Télévision avec sa navigation conservée ; pour un épisode, aux saisons et épisodes de sa série ; pour un film, à sa fiche avec la position de reprise enregistrée. En plein écran, le retour rétablit aussi la fenêtre normale. Un enregistrement doit être arrêté avant de fermer son contenu.

**Reconnexion automatique :** après une interruption d’un flux distant, le lecteur effectue au maximum quatre tentatives espacées de 1, 2, 4 et 8 secondes, avec un bouton **Annuler**. Une connexion sans chargement pendant 25 secondes ou une mise en mémoire tampon bloquée pendant 15 secondes peut déclencher cette récupération. Le budget est rétabli après dix secondes de lecture continue. Les films et épisodes conservent leur position ; la reprise dépend de la capacité du serveur à accepter les déplacements. Les fichiers locaux et les fins normales de vidéo ne déclenchent pas de reconnexion. Cette option peut être désactivée dans les préférences.

**Épisode suivant :** à la fin d’un épisode, un compte à rebours de cinq secondes propose la suite, avec **Lire maintenant** et **Annuler**. L’enchaînement fonctionne uniquement dans la vue du lecteur, sans enregistrement en cours. Quitter cette vue, arrêter, déplacer la lecture ou mettre en pause annule le compte à rebours. L’option est désactivable dans les préférences.

**Format d’image :** choisissez Auto, 16:9, 4:3, 21:9, Carré, Remplir ou Étirer dans le sélecteur du lecteur. Auto reprend le format natif ; Remplir recadre pour remplir la zone ; Étirer adapte l’image à la zone en modifiant ses proportions. Le choix est mémorisé et appliqué aux prochaines lectures.

**Inactivité :** après cinq secondes sans action dans le lecteur chargé, le curseur, la barre de temps et les commandes disparaissent, en fenêtre comme en plein écran. Un mouvement de souris, un clic ou une touche les fait réapparaître. Une manipulation de la barre de temps ou un menu ouvert maintient les commandes visibles. Le chargement, les erreurs et la sortie du lecteur rétablissent leur visibilité. Le suivi du pointeur couvre aussi la fenêtre native intégrée de mpv. La console est retirée de la disposition lorsqu’elle se masque : la vidéo récupère toute sa hauteur et s’agrandit. Au réveil des commandes, elle retrouve sa place au-dessus de la console. Les messages de reconnexion et d’épisode suivant utilisent également un emplacement réservé. Le choix de reprise maintient les commandes visibles.

**Raccourcis :** `Espace` pause, `F` ou double-clic dans la vidéo pour le plein écran / mode normal, `M` muet, molette ou `↑` / `↓` volume par pas de 5 %, `B` afficher / masquer la liste, `A` parcourir les formats d’image, `←` / `→` déplacement de dix secondes, `Page ↑` / `Page ↓` contenu précédent / suivant hors de la liste, `Ctrl+K` recherche. `Échap` ferme d’abord le menu, puis la liste, puis le plein écran, puis le contenu. Les champs de recherche, la liste, les curseurs et la séparation redimensionnable conservent leurs touches de navigation natives ; les boutons affichent un indicateur de focus.

Le volume est affiché par un curseur et un pourcentage, avec un bouton Muet qui conserve le niveau précédent. Le bouton de retour indique explicitement **Arrêter la chaîne**, **Fermer le film** ou **Fermer l’épisode**. Il arrête le contenu et ramène à sa liste ou sa fiche. La croix de la fenêtre et `Ctrl+Q` proposent de fermer seulement le contenu, de quitter l’application ou d’annuler si une lecture est active. Quitter avec des téléchargements actifs demande également confirmation.

### Catégories protégées par PIN

Dans Télévision, Films, Séries ou Radio, sélectionnez une catégorie dans le menu vertical et cliquez sur **Verrouiller** en bas du panneau. Créez un PIN de 4 à 8 chiffres lors du premier verrouillage. Le cadenas reste associé à la catégorie et au type de contenu, indépendamment de la source et de la casse du nom. Pour la radio, les catégories correspondent aux genres ; une station portant plusieurs genres est protégée si l’un d’eux est verrouillé.

Un PIN valide autorise la catégorie pendant la session. Dans **Préférences → Protection des catégories**, vous pouvez modifier le PIN, désactiver la protection ou **Reverrouiller maintenant**. Cette dernière action arrête une lecture protégée et met ses téléchargements actifs en pause. Les catégories se reverrouillent au prochain lancement. Le PIN est également demandé pour retirer un verrou, et cinq erreurs consécutives déclenchent un délai avant un nouvel essai.

Les accès par recherche, favoris, historique, guide, liste du lecteur et téléchargements sont contrôlés ; les épisodes héritent de la catégorie de leur série. Le PIN n’est jamais conservé en clair : le profil contient une empreinte scrypt salée dans `parental.json`, avec des permissions privées. Cette protection concerne la navigation dans TunPlayer : elle ne chiffre pas les fichiers téléchargés et ne remplace pas des comptes système séparés pour les personnes ayant accès au profil.

Pour les M3U, les URL de séries sont reconnues avant les extensions de vidéo. Les URL `.mp4`, `.mkv`, `.avi` ou `.mov` et les chemins `/movie/` sont ensuite classés comme films. Les autres flux sont classés dans Télévision. Les protocoles HTTP(S), RTSP, RTMP, UDP et RTP sont admis ; leur lecture dépend de mpv et du réseau. Les directives M3U propres à Kodi, les en-têtes HTTP particuliers et le DRM ne sont pas implémentés.

La bibliothèque et le guide sont paginés par lots de **30, 60 ou 120 contenus** (60 par défaut), avec total, page courante et boutons précédent / suivant. Tous les résultats restent accessibles. Les filtres et les compteurs sont exécutés dans SQLite ; l’interface ne charge pas le catalogue entier pour afficher une page. Les noms de recherche sont normalisés à l’import. Les imports et les actualisations, y compris leurs écritures SQLite, s’exécutent en arrière-plan.

## Données et confidentialité

Base SQLite : `~/.local/share/tunplayer/library.sqlite3` ou `$XDG_DATA_HOME/tunplayer/library.sqlite3`.

```bash
./start.sh --data-dir /tmp/tunplayer-profile
```

Aucun service cloud, compte TunPlayer ou télémétrie. Les visuels HTTP(S) référencés par vos sources sont téléchargés directement ; aucune recherche d’affiche sur un service tiers n’est ajoutée. Le cache se trouve dans `~/.cache/tunplayer/artwork` ou `$XDG_CACHE_HOME/tunplayer/artwork` ; un profil `--data-dir` garde son propre sous-dossier `artwork-cache`. Le cache est borné à 160 Mo, avec renouvellement après 14 jours, au plus quatre téléchargements concurrents, 8 Mo par image et un délai de requête de huit secondes. PNG, JPEG, GIF et WebP sont acceptés selon les décodeurs disponibles. Les SVG distants restent remplacés par le monogramme. Les URL complètes ne figurent pas dans les noms des fichiers en cache. Les URL de lecture et les paramètres de connexion nécessaires à l’actualisation peuvent inclure vos identifiants ; la base est locale, protégée par les permissions du fichier sous Linux, mais **non chiffrée**. Ne partagez pas cette base. Supprimer une source retire aussi ses favoris et son historique. Les imports réseau s’exécutent hors du thread d’interface avec un délai de requête de 25 secondes et une limite de 64 Mo par réponse. Les imports XMLTV contenant une DTD ou des entités sont refusés.

## Vérification

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q tunplayer run.py scripts tests
```

**Résultat dans l’environnement de développement : 158 tests réussis.** Ils couvrent les formats, les transactions, la migration de la base 0.1, les rotations d’URL, les identifiants ambigus, la pagination sans doublons, la recherche sans accents et la conservation des données après un échec. Les tests du contrôleur utilisent la vraie boucle GLib et des connexions SQLite distinctes pour vérifier l’import et l’actualisation asynchrones. La lecture, la reprise, l’arrêt et la protection de la position après un échec sont vérifiés avec le **vrai moteur libmpv** et le média local. Les nouveaux tests couvrent aussi les filtres combinés, les métadonnées, les séries, la persistance des épisodes et de leur reprise, le décodage réel des images, le cache et les changements de page pendant les téléchargements. Les régressions ajoutent la récupération des séries pour une ancienne source sans toucher aux films, les variantes de réponse fournisseur, les écritures pendant un verrou SQLite, la réactivité de GLib pendant une requête et le rejet des réponses de recherche dépassées. Les tests ajoutés vérifient les trois sélections de Découvrir, les tris, le repli sur la date d’import, les limites du délai de cinq secondes et les formats d’image sur le vrai moteur mpv. Les tests de la version 0.4 vérifient aussi les tentatives de reconnexion et leur annulation, la reprise après interruption, les fiches et leur cache après échec, le passage entre saisons, le marquage des contenus terminés et un enchaînement réel de deux fichiers locaux via mpv. La version 0.4.1 ajoute la vérification du cache borné et expirant, de sa séparation par révision, de la réutilisation des comptages, des pages préparées sans accès SQLite, de la mémoire de navigation, de la priorité du défilement manuel et des mises à jour ciblées des favoris. La version 0.4.2 vérifie les destinations du retour, l’arrêt réel de mpv après lecture d’un épisode, la conservation de la position finale du film, l’annulation des actions en attente et la persistance de la largeur des catégories. La version 0.4.5 vérifie aussi le refus d’un identifiant parent absent ou invalide, l’absence de création de lecteur quand la surface GTK manque, et les options X11 sur le vrai moteur mpv, même avec un environnement déclaré Wayland. La version 0.5 vérifie les catégories dans le lecteur, la pagination bornée et centrée sur le média en cours, les cibles Précédent / Suivant isolées par source et catégorie, le passage entre saisons, les résultats dépassés annulés et l’ouverture d’une série sans interruption du flux. Le passage manuel entre épisodes réutilise le vrai moteur mpv dans les tests. La version 0.6 vérifie le repli adaptatif et la mémorisation de largeur, les limites de taille natives, les choix de reprise / redémarrage / annulation, l’absence de dialogue pendant un réessai ou l’enchaînement, les états simplifiés, le diagnostic à la demande et les priorités clavier. Cinq tests supplémentaires couvrent le paquet Debian reproductible, son installation / suppression isolées et les garde-fous de publication (tag, téléchargement et brouillon). Les interactions GitHub de ces tests de publication sont simulées ; elles ne prouvent pas une mise en ligne réelle. Les services Xtream et les réponses HTTP d’images restent simulés dans les tests ; le décodage des images et la lecture vidéo utilisent leurs vrais moteurs. La feuille de style GTK est aussi chargée sans erreur de parsing.

Mesure locale sur un catalogue synthétique de **20 000 entrées** : import 0,75 s, lecture de la dernière page SQLite de 60 lignes 4,2 ms, comptage d’une recherche 5,7 ms, actualisation des 20 000 URL avec conservation des identités 1,10 s. Ce sont des mesures du stockage sur cette machine, sans réseau ni rendu graphique. Pour reproduire :

```bash
python3 scripts/benchmark_library.py --channels 20000
```

Le bac à sable de développement interdit la connexion à l’écran X11 : la fenêtre et son intégration vidéo n’ont donc **pas pu être validées visuellement ici**. Le test graphique fourni doit être exécuté depuis votre terminal de bureau :

```bash
python3 scripts/smoke_ui.py /tmp/tunplayer-captures
```

Il utilise un profil temporaire avec 125 chaînes, six films, une série et deux épisodes locaux. Les visuels fictifs sont générés puis préchargés dans le cache : ce parcours ne nécessite pas de fournisseur ni de réseau. Il vérifie Découvrir sans catégories, les filtres, le menu vertical, la navigation repliée, les affiches, la liste, les fiches détaillées et les épisodes. Il lit le média local, vérifie l’identifiant de la zone GTK et la présence d’une fenêtre enfant mpv dans cette zone via XQueryTree, vérifie le titre et le badge de série, les états Lecture / Pause et le masquage de l’en-tête, applique un format d’image, attend le masquage des commandes puis les réaffiche, vérifie la proposition d’épisode suivant et son annulation, lit le second épisode et produit dix-huit captures, dont le choix de reprise, le lecteur en petite fenêtre, le panneau des séries et épisodes et le diagnostic du lecteur. Il vérifie aussi l’agrandissement de la vidéo au masquage des commandes, le rétablissement de ses dimensions au réveil et leur conservation pendant un message d’épisode suivant. Il vérifie également le retour à une page de catalogue avec sa position de défilement et son cache, le réglage du panneau des catégories et le bouton de retour vers les épisodes. Pendant ce parcours, laissez la souris immobile pendant l’étape d’inactivité pour ne pas réveiller le lecteur. Il ne touche pas votre bibliothèque habituelle. Une capture simple est également possible :

```bash
./start.sh --data-dir /tmp/tunplayer-preview --screenshot /tmp/tunplayer.png
```

## Organisation

- `tunplayer/core.py` : formats, téléchargement borné, catalogues, épisodes et stockage SQLite.
- `tunplayer/catalog.py` : normalisation des métadonnées, types et tris autorisés.
- `tunplayer/artwork.py` : chargement asynchrone, décodage et caches disque / mémoire des logos / affiches.
- `tunplayer/jobs.py` : lecture de catalogue annulable, caches des résultats et comptages, file d’écriture sérialisée.
- `tunplayer/navigation.py` : mémoire bornée des pages et positions dans la session.
- `tunplayer/player_catalog.py` : requêtes bornées du panneau de lecture, catégories et voisins du média en cours.
- `tunplayer/player.py` : liaison typée à l’API C de libmpv via `ctypes`, formats d’image et curseur.
- `tunplayer/playback_ui.py` : formats autorisés et politique d’inactivité testable sans écran.
- `tunplayer/playback_flow.py` : tentatives de reconnexion et compte à rebours des épisodes.
- `tunplayer/app.py` : interface GTK, tâches d’import asynchrones et contrôles de lecture.
- `assets/style.css`, `assets/tunplayer.svg` : thème et icône originaux.
- `tunplayer/visuals.py` : panorama, vignettes Cairo et jeu d’icônes SVG.
- `assets/demo.mp4` : extrait de test local créé avec FFmpeg ; aucune ressource UHF n’est copiée.
- `tests/` : tests métier, contrôleur asynchrone et intégration libmpv.
- `scripts/smoke_ui.py` : parcours graphique et captures.
- `scripts/build_deb.py`, `scripts/verify_deb.py` : construction depuis un tag et verification du paquet installable.
- `scripts/publish_release.py` : publication verifiee du paquet avec GitHub CLI.
- `packaging/debian/`, `packaging/releases/` : metadonnees du paquet et notes de release.
- `scripts/benchmark_library.py` : mesures reproductibles sur une bibliothèque temporaire.
- `scripts/benchmark_responsiveness.py` : mesure de la boucle GLib pendant les requêtes d’un catalogue synthétique.

## Windows et étapes suivantes

Le stockage, les parseurs et la liaison mpv sont séparés de l’interface pour permettre le portage. GTK 3 existe sous Windows via MSYS2 ; il faudra fournir Python / PyGObject, le runtime GTK, `mpv-2.dll` et FFmpeg. L’intégration vidéo actuelle utilise un identifiant X11 sous Linux. Sous Windows, l’intégration native, l’installateur et les tests restent à réaliser. Cette version refuse la lecture graphique sur un système sans intégration native disponible, au lieu d’ouvrir une fenêtre vidéo séparée. Aucun exécutable Windows n’est livré dans cette version.

Travail restant pour couvrir les usages avancés de la référence :

- validation graphique sur une session Linux et sur des fournisseurs réels ;
- affichage virtualisé en défilement continu et indexation avancée pour les très gros catalogues ;
- regroupement automatique des épisodes M3U et catch-up selon fournisseur ;
- mosaïque multi-flux et mode fenêtre flottante ;
- enregistrements planifiés avec reprise après redémarrage ;
- contrôle parental, cast, intégrations Jellyfin / Plex / Emby et Trakt ;
- synchronisation optionnelle, gestion sécurisée des secrets et VPN ;
- paquet Linux distribuable puis portage et installateur Windows.

Aucune promesse de Dolby, HDR, DRM ou performance supérieure à UHF n’est faite sans validation sur le matériel et les flux concernés.

## Références de l’intégration

Les champs et actions de catalogue sont vérifiés contre les [docs de l’implémentation Xtream Codes](https://github.com/worldofiptvcom/xtream-codes-api/blob/master/docs/player-api/overview.md) et la [référence d’intégration BUI](https://github.com/bluchip-studio-official/BUI/blob/main/docs/en/api/xtreamcodes_api.md). Les variations d’un fournisseur réel restent à tester avec son compte.

Pour mesurer la réactivité de la boucle GLib sur un volume proche de 143 500 éléments, sans compte fournisseur ni écran :

```bash
python3 scripts/benchmark_responsiveness.py --channels 143500
```

Cette mesure vérifie l’exécution du catalogue en arrière-plan ; elle ne remplace pas la validation du défilement et de la vidéo sur un bureau Linux. Le fournisseur configuré n’a pas pu être joint depuis le bac à sable de développement.

Mesure locale de la version 0.4.1 sur 143 500 éléments synthétiques : requête initiale de 120 lignes avec compteurs et filtres en 662,17 ms ; récupération d’une page en cache en 2,20 ms (médiane de 20 lectures). La préparation de la page suivante prend 210,04 ms en arrière-plan, puis sa récupération en cache 2,23 ms. Pendant la requête initiale, 120 passages du temporisateur GLib et un intervalle maximal de 5,91 ms ont été observés. Ces valeurs dépendent de la machine et de la sélection ; aucun rendu de fenêtre ni défilement n’est inclus dans cette mesure.

Les réglages de format et de curseur utilisent les propriétés documentées dans le [manuel officiel mpv](https://mpv.io/manual/stable/) ; leur application est vérifiée sur le moteur installé.

Les priorités de construction suivent le [fonctionnement de la boucle GLib](https://docs.gtk.org/glib/main-loop.html). La recherche s’appuie sur le [signal natif Gtk.SearchEntry::search-changed](https://docs.gtk.org/gtk3/signal.SearchEntry.search-changed.html), qui regroupe les changements pendant 150 ms.

Le panneau redimensionnable utilise le composant natif [Gtk.Paned](https://docs.gtk.org/gtk3/class.Paned.html).

Les réglages du lecteur utilisent les composants natifs [Gtk.MenuButton](https://docs.gtk.org/gtk3/class.MenuButton.html) et [Gtk.Popover](https://docs.gtk.org/gtk3/class.Popover.html).

La configuration d’intégration suit les options `wid`, `vo`, `gpu-context` et `gpu-api` du [manuel officiel mpv](https://mpv.io/manual/stable/). Les options ont été vérifiées sur le mpv 0.37 installé ; la hiérarchie réelle des fenêtres doit être vérifiée par le parcours graphique dans la session Linux.

La console masquée ne réserve aucun espace sous la vidéo. Les messages de reconnexion et d’épisode suivant partagent un emplacement [Gtk.Stack à taille homogène](https://docs.gtk.org/gtk3/class.Stack.html) dans la console visible. Le panneau utilise [Gtk.Paned](https://docs.gtk.org/gtk3/class.Paned.html) et respecte ses limites natives. La session graphique étant inaccessible au bac à sable, les assertions de dimensions et les captures du parcours graphique restent à exécuter depuis le bureau Linux.

L’empaquetage utilise [dpkg-deb](https://manpages.debian.org/bookworm/dpkg/dpkg-deb.1.en.html). La publication suit les commandes officielles [gh release create](https://cli.github.com/manual/gh_release_create) et [gh release upload](https://cli.github.com/manual/gh_release_upload).
