TunPlayer 1.0.0 - Linux x86_64 autonome

Python 3.12, PyGObject, Cairo, GTK 3, mpv, FFmpeg, decodeurs SVG,
certificats HTTPS et une police sont inclus dans le paquet.

Cible initiale : Ubuntu 24.04 / Linux Mint 22, x86_64, glibc 2.39.
Le serveur X11 (ou XWayland), les pilotes GPU/audio et le noyau restent
fournis par Linux. Compatibilite avec les autres distributions non validee.

Archive portable : extraire puis lancer ./AppRun, sans sudo.
Paquet .deb : sudo apt install ./tunplayer_1.0.0+standalone1_amd64.deb
Le .deb remplace le paquet TunPlayer leger. Votre bibliotheque est conservee.
Ne pas lancer le lecteur avec sudo. Aucune playlist n'est incluse.

Le programme est celui du tag v1.0.0. La recette ajoute seulement le runtime.
build-info.json inventorie les fichiers natifs et versions des paquets.
Les licences tierces sont dans licenses/ (dont les licences GPL/LGPL).
Les bibliotheques restent des fichiers partages remplacables.
Sources TunPlayer : https://github.com/fourat50/TunPlayer
Sources des paquets Ubuntu : https://archive.ubuntu.com/ubuntu/pool/
Les sources exactes peuvent etre recuperees avec apt source pour les
versions inventoriees, apres activation des depots sources correspondants.

Verification locale : ./AppRun --self-test
Ce controle importe GTK, decode le SVG, verifie les certificats HTTPS,
execute FFmpeg et lit le media de demonstration avec le vrai moteur mpv.
Il ne prouve pas la lecture graphique sur un autre poste ou fournisseur.

La mise a jour des composants embarques necessite une nouvelle construction
du paquet autonome ; APT ne met pas a jour ces copies privees separement.
