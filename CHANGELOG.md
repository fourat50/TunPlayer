# Historique

## 1.5.2

- Correction de l’icône « search » manquante : elle provoquait une exception pendant la création de la fenêtre de résultats, juste après la fermeture du dialogue audio.
- Recherche lancée automatiquement à l’ouverture de la fenêtre, avec le titre, la saison / épisode et la langue déjà sélectionnés ; filtres toujours modifiables.
- Décodage réel des icônes dans les tests des dialogues, contrôle des références du code et vérification des ressources SVG dans le paquet autonome.
- Tests du parcours film et épisode depuis le dialogue audio jusqu’à la sélection, au téléchargement d’une archive et à l’activation du sous-titre dans le vrai moteur mpv.

## 1.5.1

- Source SubDL activée immédiatement lorsqu’une clé est ajoutée depuis une fenêtre de recherche déjà ouverte.
- Résultats affichés au fur et à mesure de la réponse des sources, sans attendre un autre fournisseur lent ; progression explicite et bouton Annuler.
- Test de connexion SubDL sur l’endpoint authentifié du compte, avec affichage des quotas de recherche et de téléchargement lorsqu’ils sont renseignés.
- Après un test réussi, configuration enregistrée ; une clé modifiée pendant le test invalide l’ancien résultat.
- Erreurs DNS, délai de réponse, TLS et authentification distinguées ; aucune erreur réseau ne valide une connexion.
- Tests des boutons et parcours de dialogue avec widgets simulés, des réponses du compte, du rendu progressif et de l’annulation des mises à jour dépassées.

## 1.5.0

- Source SubDL ajoutée à la recherche de sous-titres de films et d’épisodes, avec clé API personnelle indépendante d’OpenSubtitles.com.
- Configuration des sources défilante, lien vers le panneau API SubDL et conservation privée de la clé avec les paramètres existants.
- Prise en charge des fichiers individuels de packs de saisons lorsque leur saison et leur épisode correspondent à la recherche.
- Correspondance des variantes portugais brésilien / portugais et chinois simplifié / traditionnel avec les codes SubDL.
- Liens de téléchargement SubDL limités à son serveur de fichiers HTTPS ; clés API absentes des requêtes de téléchargement et erreurs expurgées.

## 1.4.0

- Recherche de sous-titres depuis le lecteur, avec titre modifiable, année, saison, épisode et langue préférée mémorisée ; 189 langues et variantes proposées, avec saisie de code ISO.
- Sources OpenSubtitles.com et Podnapisi intégrées sans dépendance Python supplémentaire ; recherches en parallèle hors du thread GTK et erreurs de source indépendantes.
- Configuration de la clé API OpenSubtitles et connexion facultative au compte ; mot de passe non enregistré, jeton et paramètres privés.
- Résultats triés selon une correspondance estimée, indication des versions, sous-titres malentendants et traductions automatiques.
- Téléchargement, validation des fichiers / archives, activation sans relancer la vidéo, sélection locale et décalage mémorisés par contenu.
- Protection contre l’application d’un résultat ancien après un changement de lecture ou un verrouillage par PIN.
- Adaptateur facultatif Subliminal 2.8 pour des sources supplémentaires ; option de construction pour embarquer ses dépendances lorsqu’elles sont disponibles.

## 1.3.1

- Démarrage vidéo différé jusqu’à l’affichage du lecteur et à la stabilisation de sa taille ; une fenêtre masquée ou un retour au catalogue ne déclenchent plus le chargement dans une surface invisible.
- Zone vidéo dédiée au dessin externe de mpv, sans double tampon GTK ; création et géométrie natives synchronisées avant l’intégration X11.
- Tests de non-régression supplémentaires pour fenêtre masquée, navigation pendant le démarrage et redimensionnement initial.

## 1.3.0

- Verrouillage des catégories Télévision, Films, Séries et Radio par PIN de 4 à 8 chiffres ; accès contrôlé depuis la recherche, les favoris, le lecteur et les téléchargements.
- PIN stocké sous forme d’empreinte scrypt salée, délai après cinq erreurs, modification et désactivation avec vérification du PIN actuel.
- Déverrouillage temporaire pour la session et action « Reverrouiller maintenant » dans les préférences.
- Bouton explicite pour fermer le contenu ; choix entre arrêter la lecture et quitter l’application lors de la fermeture de la fenêtre pendant une lecture.
- Curseur de volume visible, pourcentage, Muet avec conservation du niveau, molette et touches ↑ / ↓ par pas de 5 %.
- Double-clic dans la vidéo pour basculer entre plein écran et mode normal, y compris lorsque mpv reçoit les événements de la zone vidéo native.

## 1.2.0

- Téléchargement d’un film depuis sa fiche, d’un épisode depuis sa liste, ou d’une saison complète après sélection.
- Rubrique Téléchargements : choix du dossier, file séquentielle, progression, pause / reprise, annulation et lecture locale intégrée.
- Reprise HTTP avec validation des plages et des ETag forts, fichiers partiels séparés, absence d’écrasement des fichiers existants et historique privé.
- HLS / DASH enregistrés en Matroska avec FFmpeg, sans réencodage vidéo ; ces flux recommencent depuis le début après une pause.
- Catalogue, vidéo et écran Radio placés dans des vues exclusives sans animation ; attente de la zone vidéo avant démarrage et annulation des lancements dépassés.
- Navigation latérale défilante lorsque l’écran est trop petit pour afficher tous les menus.

## 1.1.1

- Retrait des totaux mondiaux de genres dans le lecteur radio : ils ne representaient pas les stations disponibles pour le pays et les filtres selectionnes.
- Pays, genre, recherche et filtre Mes radios affiches explicitement dans l’annuaire et dans le lecteur.
- Nombre de stations indique comme celui de la page courante ; messages de liste vide adaptes a la pagination.
- Possibilite d’elargir une recherche vide a tous les pays ou a tous les genres sans effacer les autres filtres.

## 1.1.0

- Nouvelle rubrique Radio dans Votre espace, alimentée par Radio Browser, l’API publique utilisée par OpenRadio.
- Pays et catégories combinables, recherche de station, tri par popularité / nom / pays et pagination de 40 résultats.
- Logos, débit et codec, favoris locaux « Mes radios », cache des recherches et des pays / genres avec consultation hors ligne des résultats déjà visités.
- Requêtes en arrière-plan, réponses dépassées ignorées, miroirs HTTPS et réessai sans bloquer GTK.
- Écran audio intégré, commandes toujours visibles, stations précédente / suivante, liste des stations pendant l’écoute, arrêt et retour vers Radio.
- Les radios sont séparées des playlists et de l’historique IPTV. Aucun compte ni clé API supplémentaire.

## 1.0.0

- Distribution Linux : paquet `.deb` construit depuis le tag fige, lanceur et icone standards, dependances APT et SHA256.
- Outils de construction reproductible, verification isolee et publication de release avec controle des telechargements. Le tag applicatif 1.0.0 reste inchange.
- Première version 1.0.0 de TunPlayer pour Linux : sources M3U / Xtream, direct, films, séries, guide XMLTV, favoris, historique et reprise.
- Lecteur mpv intégré avec formats d’image, audio / sous-titres, enregistrement manuel et reconnexion automatique.
- Navigation par catégories dans le lecteur, épisodes et saisons, commandes Précédent / Suivant nommées, choix de reprise et raccourcis clavier.
- Interface compacte, panneaux ajustables, chargements asynchrones et caches bornés ; la vidéo s’agrandit quand les commandes se masquent.
- Bouton Épisodes pendant la lecture d’un épisode, avec infobulle et nom accessible adaptés.
- 153 tests automatisés ; le parcours graphique de vérification est fourni. Le portage et l’installateur Windows restent à réaliser.

## 0.6.1

- Suppression de l’espace réservé à la console masquée : la vidéo récupère toute sa hauteur après cinq secondes d’inactivité.
- Réapparition normale des commandes à la souris ou au clavier ; intégration vidéo et autres fonctions conservées.
- Parcours graphique corrigé pour vérifier l’agrandissement puis le retour aux dimensions initiales. 153 tests réussis ; rendu réel à vérifier depuis la session Linux.

## 0.6.0

- Zone vidéo stabilisée au masquage des commandes et lors des messages de lecture, grâce à des emplacements homogènes réservés. Une bande sombre remplace les commandes masquées.
- Commandes compactées en trois lignes ; contenus voisins intégrés à la ligne de transport avec noms et infobulles.
- Panneau redimensionnable, largeur mémorisée, respect des tailles natives GTK et repli automatique en petite fenêtre sans perte de préférence. Repère du contenu en cours renforcé.
- États de lecture simplifiés ; diagnostic détaillé dans Réglages, interrogé seulement à la demande et au plus toutes les deux secondes.
- Choix Reprendre / Depuis le début / Annuler pour les contenus non terminés déjà commencés ; lecture en cours préservée après annulation et absence de dialogue lors d’une reconnexion ou de l’enchaînement automatique.
- Raccourcis Page ↑ / ↓ et B ; Échap ferme successivement le menu, le panneau puis le plein écran. Navigation native préservée dans les champs, la liste et la séparation.
- 153 tests réussis, compilation et CSS GTK validés. Parcours graphique étendu à dix-huit captures avec vérification des dimensions vidéo. Validation du rendu et de la géométrie à effectuer depuis le bureau Linux, inaccessible au bac à sable.

## 0.5.0

- Panneau repliable dans le lecteur pour les chaînes, films et séries de la source en cours, avec catégories, recherche, pagination de 40 éléments et repère du média regardé.
- Navigation entre séries et épisodes sans quitter le lecteur ni interrompre le média avant la sélection d’un nouveau contenu ; récupération des épisodes manquants en arrière-plan.
- Boutons Précédent / Suivant avec le nom de la cible : ordre alphabétique dans la catégorie pour le direct et les films, ordre des saisons / épisodes pour une même série. Commandes désactivées aux limites.
- Requêtes SQLite annulables hors du fil graphique, index pour les voisins du catalogue et cache borné des compteurs de catégories.
- Visibilité du panneau mémorisée ; Ctrl+K recherche dans le lecteur ; touches de navigation conservées dans la liste.
- 141 tests réussis, dont navigation entre épisodes avec le vrai moteur mpv réutilisé. CSS et 35 icônes validés. Parcours graphique enrichi à seize captures ; rendu réel encore à vérifier dans la session Linux.

## 0.4.5

- GTK utilise explicitement X11 ; mpv reçoit la fenêtre parente GTK et une sortie restreinte à GPU X11/EGL ou X11 logiciel, sans sélection automatique de Wayland.
- Création d’un lecteur graphique refusée sans identifiant parent strictement positif ; surface GTK native vérifiée avant initialisation.
- Nettoyage du moteur si sa configuration échoue et réutilisation du lecteur intégré existant lors des changements de contenu.
- 127 tests réussis, compilation validée ; options vérifiées sur le vrai moteur mpv. Parcours graphique enrichi avec vérification du parent X11 et d’une fenêtre enfant vidéo. Validation sur l’écran réel encore nécessaire.

## 0.4.4

- Nouvelle composition cinéma : vidéo sur toute la largeur, navigation latérale masquée pendant la lecture puis restaurée au retour.
- Barre anthracite sans cadre flottant, titre hiérarchisé, progression fine et trois zones équilibrées : volume / temps, transport centré, outils.
- Bouton Lecture / Pause blanc ; commandes secondaires sans fonds permanents, survols et focus contrastés.
- Format d’image, rechargement et enregistrement regroupés dans un menu Réglages. Indication de l’enregistrement sur ce bouton.
- Le menu maintient les commandes visibles, conserve ses propres touches de navigation et se ferme avec Échap.
- 124 tests réussis, CSS GTK valide et compilation réussie. Parcours graphique étendu à quatorze captures ; validation visuelle de la fenêtre encore nécessaire dans la session Linux.

## 0.4.3

- Console vidéo graphite arrondie, titre du contenu, état de lecture et badge Direct / Film / Série.
- Commandes regroupées : déplacements de dix secondes, bouton Lecture / Pause agrandi et vectoriel, Stop, puis volume, format, pistes, réessai, enregistrement et plein écran.
- Barre de progression et poignée plus visibles, temps dans un cartouche, survols et focus contrastés.
- Icônes Lecture / Pause et plein écran adaptées à leur état, enregistrement distingué par sa couleur et son libellé, infobulles et noms accessibles actualisés.
- En-tête général et pied de page masqués dans le lecteur pour libérer de la place à la vidéo ; masquage après cinq secondes conservé.
- 123 tests réussis, CSS GTK et décodage des 32 icônes validés. Parcours graphique enrichi pour les états du lecteur ; rendu complet à vérifier dans la session Linux.

## 0.4.2

- Le bouton Stop utilise le même retour contextuel que le bouton Retour.
- Bouton Retour dans le lecteur : arrêt du flux, annulation de la reconnexion et du compte à rebours, puis retour aux chaînes en direct, aux saisons / épisodes de la série ou à la fiche du film.
- Position finale de reprise conservée et fiche actualisée après son enregistrement ; navigation et sélection de saison préservées lorsque disponibles.
- Panneau des catégories redimensionnable par une séparation native GTK, avec largeur mémorisée de 150 à 480 pixels et écritures regroupées pendant le réglage.
- 123 tests réussis, dont arrêt du vrai moteur mpv et persistance du réglage. CSS GTK et compilation vérifiés. Parcours graphique étendu à treize captures ; rendu complet à valider dans la session Linux.

## 0.4.1

- Cache mémoire LRU borné à 12 pages, expirant après 15 secondes et séparé par révision des données ; comptages réutilisés entre pages d’une même sélection.
- Préparation d’une seule page suivante dans le travailleur SQLite existant, annulée dès une nouvelle action ; aucun nouveau flux ni téléchargement d’affiche anticipé.
- Retour aux rubriques avec leur page, recherche, filtres et défilement ; mémoire de session bornée à 32 positions et priorité au défilement manuel.
- Construction progressive avec au plus quatre cartes par passage, budget visé de quatre millisecondes et priorité inférieure aux événements et au rendu GTK.
- Recherche fondée sur la temporisation native GTK, sans délai supplémentaire après le signal de recherche.
- Favoris actualisés sur les cartes concernées, y compris les doublons de Découvrir, sans reconstruire une liste non filtrée.
- 116 tests réussis. Sur 143 500 contenus synthétiques : requête initiale avec filtres en 662 ms et récupération d’une page en cache en 2,2 ms, sans mesure de rendu graphique. Parcours graphique étendu au retour de navigation, avec douze captures ; validation dans une session graphique encore nécessaire.

## 0.4.0

- Reconnexion des flux distants avec quatre tentatives espacées de 1, 2, 4 et 8 secondes, annulation et réglage persistant. Récupération après délai de chargement ou blocage prolongé du tampon ; position VOD conservée.
- Distinction entre interruption et fin normale ; aucune reconnexion des fichiers locaux. Budget rétabli après dix secondes de lecture continue.
- Fiches films et séries : affiche, synopsis, genre, année, note, durée, distribution, réalisation, favoris et progression selon les informations disponibles.
- Chargement asynchrone des détails Xtream, cache de 24 heures pour les films et d’une heure pour les séries, actualisation manuelle et conservation des informations après échec ou actualisation du catalogue.
- Contenus terminés identifiés, reprise de série et passage à l’épisode suivant entre saisons.
- Enchaînement automatique après cinq secondes, avec lecture immédiate et annulation ; désactivable dans les préférences et annulé en quittant le lecteur, en arrêtant, en déplaçant la lecture ou en mettant en pause.
- Migration additive de la bibliothèque, préservant favoris, historique et positions existantes.
- 105 tests réussis : reconnexion et annulation simulées, cache et progression, lecture et enchaînement avec le vrai moteur mpv. Parcours graphique étendu à onze captures ; rendu de la fenêtre et fournisseur réel encore à valider dans une session Linux accessible.

## 0.3.2

- Accueil Découvrir sans catégories ni filtres, avec trois rangées horizontales : derniers films, dernières séries et Tendances.
- Tendances fondées sur les notes des sources, avec repli sur les ajouts récents ; aucun classement mondial simulé.
- Date de première importation conservée et index dédiés aux nouveautés.
- Sélecteur de format Auto, 16:9, 4:3, 21:9, Carré, Remplir et Étirer, préférence persistante et raccourci A.
- Curseur et commandes masqués après cinq secondes d’inactivité ; réveil souris/clavier, maintien pendant les manipulations et restauration hors lecture.
- Suivi du pointeur natif mpv et contrôle coordonné du curseur GTK / mpv.
- 82 tests réussis, dont formats d’image appliqués au vrai moteur mpv et politique d’inactivité vérifiée aux limites du délai. La validation graphique complète reste à réaliser dans une session accessible.

## 0.3.1

- Récupération automatique et ciblée des séries pour les anciennes sources Xtream, avec actualisation manuelle et message d’échec explicite.
- Compatibilité avec des catalogues enveloppés / indexés et des épisodes en listes plates ou imbriquées ; conservation des contenus existants après une réponse vide ou échouée.
- Menu vertical de catégories avec recherche locale, compteurs et modèle GTK ; navigation « Votre espace » réductible en icônes avec préférence persistante.
- Recherches indépendantes par rubrique pour éviter de masquer les séries avec une recherche de film.
- Lecture du catalogue en arrière-plan, résultats dépassés annulés, filtres détaillés calculés à la demande, création progressive des cartes.
- Écritures de réglages, favoris et reprise sérialisées en arrière-plan ; connexions de travail sans répétition des migrations.
- Réutilisation des icônes et des images décodées, vignettes plus légères et nettoyage disque du cache moins fréquent.
- 72 tests réussis, dont réactivité de GLib et verrouillage SQLite. Vérification sur le fournisseur et l’écran réels encore nécessaire.

## 0.3.0

- Logos des chaînes et affiches des films/séries lus depuis les sources, avec cadrage adapté, cache local borné et chargement asynchrone.
- Rubrique Séries, import Xtream des couvertures et métadonnées, chargement des saisons/épisodes à la demande et reprise par épisode.
- Reconnaissance des URL et titres d’épisodes M3U, présentés comme fichiers directement lisibles dans Séries.
- Filtres combinés par type, source, catégorie, genre, année, langue, qualité déclarée, note et statut ; recherche à plusieurs mots dans titres, catégories et genres.
- Tris, vues grille/liste, densité compacte et pagination 30/60/120 mémorisée.
- Conservation des favoris, métadonnées et épisodes lors des actualisations ; migration additive des bases existantes.
- 58 tests réussis. Parcours graphique étendu avec visuels locaux fictifs ; écran et fournisseurs réels non accessibles depuis l’environnement de développement.

## 0.2.1

- Nouvelle direction visuelle graphite et citron vert, typographie hiérarchisée, contrastes et espacements affinés.
- Accueil panoramique avec illustration vectorielle originale et raccourcis vers les rubriques.
- Cartes illustrées par couleur, monogrammes, badges et favoris en surimpression.
- Jeu cohérent de 25 icônes SVG locales, infobulles et indicateurs de focus clavier.
- Commandes du lecteur réparties sur deux lignes ; en-tête masqué en plein écran.
- Pages Sources, Préférences et écrans vides remaniés.

Validation : 38 tests existants réussis, syntaxe CSS GTK et décodage des 25 icônes vérifiés, illustrations Cairo inspectées. Le rendu de la fenêtre complète reste à vérifier dans une session graphique.

## 0.2.0

- Actualisation et modification des sources M3U / Xtream, avec paramètres de connexion locaux et date de dernière mise à jour.
- Conservation des identités, favoris et positions pour les contenus reconnus ; rapprochement par URL, identifiant fournisseur puis `tvg-id` non ambigu, séparément pour le direct et les films.
- Réconciliation transactionnelle : ajout des nouveautés, retrait des contenus disparus, bibliothèque préservée après une erreur ou une réponse vide.
- Migration additive des bibliothèques 0.1. Les sources anciennes peuvent être reconnectées sans supprimer la source.
- Pagination SQLite par 60 contenus dans la bibliothèque et le guide ; filtre par source et catégorie, recherche sans accents et sans distinction de casse.
- Import et écritures SQLite en arrière-plan, avec connexions distinctes et mode WAL pour les lectures concurrentes.
- Boutons de retour au lecteur, d’arrêt et de réessai manuel. L’échec d’ouverture d’un film n’efface plus sa position de reprise.
- Erreurs d’import expurgées des détails techniques pouvant contenir des identifiants.
- 38 tests automatisés, dont parcours du contrôleur avec GLib et lecture/reprise réelles via libmpv ; script de mesure sur 20 000 entrées et parcours graphique étendu.

La validation visuelle sur un bureau Linux, les essais avec un fournisseur réel et le portage Windows restent à effectuer.

## 0.1.0

- Première interface GTK française, moteur libmpv, import M3U / Xtream direct et films.
- Favoris, historique, reprise, XMLTV, sous-titres, pistes audio et enregistrement manuel FFmpeg.
- Extrait local de démonstration et 15 tests automatisés.
