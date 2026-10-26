<p align="center"><img src="assets/tunplayer.svg" width="112" alt="Logo TunPlayer"></p>

<h1 align="center">TunPlayer pour Linux</h1>
<p align="center">Télévision en direct · Films · Séries · Radios</p>
<p align="center"><a href="https://github.com/fourat50/TunPlayer/releases/latest">Télécharger pour Linux</a> · <a href="DOCUMENTATION-LINUX.md">Documentation</a> · <a href="CHANGELOG.md">Historique</a> · <a href="https://github.com/fourat50/TunPlayer-for-Windows">Version Windows</a></p>

TunPlayer est un lecteur de bureau en français pour réunir vos sources M3U et Xtream dans une bibliothèque locale. Son interface sombre propose des affiches, des catégories, une recherche et un lecteur vidéo intégré.

**Version Linux : 1.6.1.** Ce dépôt contient les sources Linux, les paquets `.deb` et les archives autonomes. Les installateurs Windows sont maintenus dans [TunPlayer-for-Windows](https://github.com/fourat50/TunPlayer-for-Windows/releases).

## Installer

Téléchargez **`tunplayer_1.6.1+standalone1_amd64.deb`** depuis la [release Linux 1.6.1](https://github.com/fourat50/TunPlayer/releases/tag/v1.6.1). Fermez TunPlayer puis, dans le dossier de téléchargement :

```bash
sudo apt install ./tunplayer_1.6.1+standalone1_amd64.deb
```

Lancez **TunPlayer** depuis le menu des applications. Python, GTK, mpv et FFmpeg sont inclus ; les mises à jour conservent votre profil, vos favoris et vos paramètres.

| Distribution et matériel | Prise en charge du paquet autonome |
| --- | --- |
| Ubuntu 24.04 / Linux Mint 22, x86_64 | Cible du paquet |
| Affichage | X11 ou XWayland |
| Bibliothèque système | glibc 2.39 ou ultérieure |
| Autres distributions ou architectures | Non validées |

**Sans installation :** téléchargez `TunPlayer-1.6.1-linux-x86_64-standalone.tar.gz`, extrayez l’archive et lancez `./AppRun`. Pour vérifier les téléchargements, placez `Standalone-SHA256SUMS` dans le même dossier et exécutez `sha256sum --check Standalone-SHA256SUMS`.

## Fonctionnalités

- **Direct, films et séries :** catégories, affiches, filtres, saisons et épisodes.
- **Lecteur intégré :** plein écran, format d’image, volume, pistes audio et sous-titres, navigation précédent / suivant et reprise de lecture.
- **Radios :** recherche et classement par pays ou catégorie avec Radio Browser.
- **Sous-titres :** import local et recherche en ligne via SubDL, OpenSubtitles et Podnapisi, selon la configuration et la disponibilité des services.
- **Bibliothèque personnelle :** favoris, historique, téléchargements de films ou d’épisodes et enregistrement manuel.
- **Sources et accès :** actualisation, informations d’abonnement et catégories protégées par PIN.

Aucune playlist IPTV, aucun abonnement et aucune clé API ne sont fournis. Ajoutez vos sources dans **Mes sources**.

## Nouveautés de la version 1.6.1

Le lecteur suit les événements mpv pour éviter les interrogations synchrones répétées. Le démarrage du direct est optimisé, la vérification des abonnements s’effectue indépendamment du chargement du catalogue et les infobulles de catégories ont été corrigées. Les délais de lecture restent dépendants du réseau et du fournisseur.

Consultez les [notes de version](packaging/releases/v1.6.1.md) pour les détails et les vérifications effectuées.

## Données personnelles

Votre bibliothèque reste dans `~/.local/share/tunplayer` (ou sous `$XDG_DATA_HOME`). Aucun compte TunPlayer ni service de synchronisation n’est nécessaire. Les sources, stations et fournisseurs de sous-titres sont contactés lorsque vous utilisez leurs fonctions.

La désinstallation avec `sudo apt remove tunplayer` conserve le profil.

## Documentation et développement

- [Guide détaillé](DOCUMENTATION-LINUX.md) : sources, navigation, téléchargements, sous-titres et diagnostic.
- [Historique des versions](CHANGELOG.md).
- [Signaler un problème Linux](https://github.com/fourat50/TunPlayer/issues) : indiquez la distribution, la version et les étapes pour reproduire, sans identifiants ni clés API.

Pour lancer le code source sur une session Linux :

```bash
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 libmpv2 ffmpeg
git clone https://github.com/fourat50/TunPlayer.git
cd TunPlayer
./start.sh
```

Le lancement depuis les sources utilise les bibliothèques du système. Les instructions de construction du paquet autonome sont dans la [documentation technique](DOCUMENTATION-LINUX.md#construire-le-paquet-autonome-161).
