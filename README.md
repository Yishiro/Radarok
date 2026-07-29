# RadarokBot

Bot Discord communautaire de Radarok's World. La commande administrateur
`/setup` a été retirée après la configuration initiale du serveur.

## Installation

1. Installe Python 3.11 ou une version plus récente.
2. Crée un environnement virtuel puis installe les dépendances :

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Copie `.env.example` en `.env`, puis remplace les valeurs :

   ```powershell
   Copy-Item .env.example .env
   ```

   - `DISCORD_TOKEN` : token disponible dans le portail développeur Discord.
   - `DISCORD_GUILD_ID` : identifiant du serveur de test. Cela fait apparaître la
     commande slash presque immédiatement.

4. Dans le portail développeur, active **Server Members Intent** et
   **Message Content Intent** dans l'onglet `Bot`, puis invite le bot avec les
   scopes `bot` et `applications.commands`.
   Accorde-lui **Gérer les salons**, **Gérer les rôles**, **Déplacer des membres**,
   **Gérer les messages**, **Exclure temporairement des membres**, **Gérer le
   serveur**, **Envoyer des messages** et **Intégrer des liens**. Place son rôle
   au-dessus des rôles communautaires.
5. Lance le bot :

   ```powershell
   python bot.py
   ```

## Structure du serveur

- L'ancien outil interne de configuration a créé la structure initiale. Il n'est
  plus exposé comme commande Discord afin d'éviter une réinitialisation accidentelle.
- Le salon Discord `1531432945888526376` est explicitement protégé et n'est
  jamais supprimé par `/setup`.
- Les permissions d'écriture sont appliquées salon par salon. Le règlement,
  l'accueil, les annonces, réseaux, panneaux, sondages, niveaux, giveaways,
  valeurs, stocks et mises à jour sont en lecture seule pour les membres.
- Les discussions, médias, créations, suggestions, commandes et salons
  d'entraide Blox Fruits restent ouverts aux membres vérifiés.
- Toutes les catégories utilisent le décor `○─────Nom─────➤`, sauf les Vocaux
  Staff qui reprennent le décor spécial `『◉』 ╰⁺°✧・⚙(Vocales Staff)⚙・✧°⁺╮`.
- Les catégories Vocaux Staff et Serveur Stat sont créées en premier. Les
  membres voient les bureaux Radarok, Alex, Staff 1 à 5 et Test Vocal, mais ne
  peuvent rejoindre que la salle d'attente ; le staff accède à tous les bureaux.
- Les compteurs Membres, Humains, Bots et Boosts sont affichés dans des salons
  vocaux verrouillés et actualisés automatiquement.
- Les espaces Événement, Partage et Partenariat sont inclus. Seul le rôle
  `🤝・Partenaire` peut écrire dans le chat partenaire.
- Elle crée les rôles d'équipe, communautaires, de notifications, d'activités,
  de races Blox Fruits et de progression qui n'existent pas encore.
- Elle attribue le rôle `👑・Radarok` au propriétaire du serveur.
- Elle publie trois menus de rôles persistants dans `🎭・choix-des-rôles`.
- La catégorie `🔒・ÉQUIPE` est visible uniquement par les rôles du staff.
- Elle applique les limites visibles aux salons vocaux.
- Le bot attribue `🔒・Non vérifié` à l'arrivée et publie un message de bienvenue.
- Le nouveau membre ne voit que la catégorie `🔐・VÉRIFICATION`. Après validation
  du règlement avec le bouton persistant, il reçoit `✅・Membre` et accède au serveur.
- Le règlement complet est publié dans `📜・règlement`.
- Les bots reçoivent automatiquement le rôle `🤖・Bots`.
- Rejoindre `➕・Créer un vocal` crée un vocal `Équipage de …`, y déplace le
  membre et supprime automatiquement le salon lorsqu'il devient vide.
- Le propriétaire contrôle son vocal avec `/vocal-limite`, `/vocal-prive`,
  `/vocal-inviter` et `/vocal-expulser`.
- Lors de la création, le bot publie automatiquement l'aide de gestion dans le
  chat textuel intégré au vocal temporaire, en mentionnant son propriétaire.

## Expérience et niveaux

- Un message peut rapporter entre 15 et 25 XP, avec un délai anti-spam de
  60 secondes par membre.
- Une minute en vocal rapporte 5 XP lorsqu'au moins deux membres humains sont
  présents. Le salon AFK, le déclencheur de vocal et les membres en sourdine
  complète sont exclus.
- La base SQLite conserve uniquement les compteurs d'XP, le nombre de messages
  et la durée vocale. Le contenu des messages n'est jamais enregistré.
- `/niveau` génère une carte PNG personnalisée sans photo de profil, avec le
  pseudo, l'emblème du rang, le niveau, la barre d'XP, les messages, le temps
  vocal et la position au classement.
- Cinq emblèmes originaux sont fournis dans `assets/ranks` pour Nouveau,
  Habitué, Actif, Vétéran et Légende.
- `/classement` affiche les dix membres les plus actifs.
- `/niveau-donner` permet à un administrateur d'accorder autant de niveaux que
  souhaité, sans limite applicative.
- `/niveau-reinitialiser` remet l'XP et le niveau d'un membre à zéro tout en conservant
  ses compteurs historiques de messages et de temps vocal.
  L'XP offert est enregistré comme bonus, sans modifier les statistiques de
  messages ou de vocal.
- Les rôles Nouveau, Habitué, Actif, Vétéran et Légende sont attribués
  automatiquement aux niveaux 1, 5, 10, 20 et 35.

## Tickets

- `/setup` publie un panel Assistance, Partenariat et Signalement, ainsi qu'un
  espace de recrutement séparé.
- Chaque formulaire crée un salon privé visible par son auteur et le staff.
- Un membre ne peut ouvrir qu'un ticket de chaque type à la fois.
- Les helpers accèdent uniquement aux tickets Assistance et Signalement.
- Le rôle `🆘・Helper` est créé ou migré automatiquement au démarrage, sans
  permission sensible.
- Lorsqu'un helper claim un ticket, les autres helpers n'y ont plus accès. Le
  staff supérieur conserve toujours l'accès.
- Chaque claim est envoyé dans `📨・tickets-staff` avec le ticket, son auteur,
  le membre du staff assigné, ainsi que la date et l'heure exactes.
- Le helper peut clôturer le ticket ou le faire remonter au staff supérieur.
- Le rôle `🔱・Staff supérieur` et la catégorie privée
  `⬆️・TICKETS REMONTÉS` sont créés automatiquement au démarrage.
- Les membres possédant les rôles Radarok, Responsable ou Administrateur
  reçoivent automatiquement le rôle Staff supérieur.
- Lors d'une remontée, le ticket est déplacé dans cette catégorie et ses
  permissions sont reconstruites : seuls son auteur, le Staff supérieur et le
  bot conservent l'accès. La remontée est aussi datée dans `📨・tickets-staff`.
- Un ticket résolu rapporte un point au helper assigné et actualise le
  classement des helpers.
- `/helper-ajouter`, `/helper-retirer`, `/helper-points-definir` et
  `/helper-classement` permettent au staff de gérer le système.
- Un Helper peut uniquement consulter `/warns` et `/infos-joueur` parmi les
  commandes réservées à l'équipe.
- L'auteur ou le staff peut demander sa fermeture, avec confirmation.
- Une transcription texte est envoyée dans `📁・transcripts-tickets` et conservée
  localement dans le dossier `transcripts`.
- Les trois salons `événement` utilisent le type « salon de conférence » (Stage).
  Si Discord refuse ce type (notamment lorsque le mode Communauté est désactivé),
  `/setup` les crée en salons vocaux et continue la configuration.

## Protection automatique

- Six messages en huit secondes déclenchent un timeout de cinq minutes.
- Cinq mentions ou plus, ainsi que `@everyone` et `@here`, sont supprimés et
  sanctionnés automatiquement.
- Les domaines d'hameçonnage courants, domaines en punycode, adresses IP et
  raccourcisseurs de liens sont bloqués.
- Les comptes récents restent autorisés et aucun filtre de mots n'est activé.
- La permission de mentionner `@everyone` est retirée au rôle par défaut.

## Invitations et giveaways

- `/invites` affiche le compteur, le rôle actuel et le prochain palier.
- `/invites-definir` remplace exactement le compteur d'un membre.
- Recruteur, Ambassadeur, Influenceur et Maître recruteur sont attribués
  automatiquement à 5, 10, 15 et 20 invitations.
- `/giveaway-creer` publie les boutons Participer, Participants, Durée et Mes chances.
- Les poids sont : base 1, puis +0,5 / +1 / +1,5 / +2 selon le meilleur rôle
  d'invitation uniquement. Un Booster reçoit +1 supplémentaire et cumulable.
- `/giveaway-terminer` force la fin, `/giveaway-reroll` refait le tirage et
  `/giveaway-annuler` annule sans gagnant.

## Rappels sociaux

- YouTube, Twitch, TikTok et Réseaux reçoivent un rappel automatique à 9 h,
  15 h et 21 h, heure de Paris.
- Le rappel précédent est remplacé afin d'éviter l'accumulation de messages.

## Équipages et trades

- Le niveau 10 est requis pour `/equipage-creer`. Un membre ne peut appartenir
  qu'à un seul équipage.
- Un équipage reçoit un rôle, un salon textuel et un vocal privés.
- Le créateur reçoit le rôle `👑・Capitaine d'équipage`.
- Le staff peut utiliser `/equipage-creer-pour` pour créer directement un
  équipage au nom d'un membre et le désigner capitaine.
- `/cv-creer`, utilisable dans le salon CV, ouvre un formulaire et publie ou
  actualise le CV du joueur.
- `/equipage-recrutement`, réservé au capitaine et au salon de recrutement,
  ouvre un formulaire puis publie une annonce avec un bouton Postuler.
- Un CV est obligatoire pour postuler. Le bot crée ensuite un salon privé entre
  le candidat et le capitaine, avec les boutons Accepter et Refuser.
- Une acceptation attribue automatiquement le rôle de l'équipage.
- Le propriétaire utilise `/equipage-supprimer`; les membres peuvent utiliser
  `/equipage-quitter`.
- `/trade-publier` accepte du texte et les emojis personnalisés du serveur.
- Le bouton d'intérêt crée un salon privé entre les deux participants. Aucun
  des deux ne peut commencer un autre trade avant la clôture.
- `/trade-avis` enregistre une note de 1 à 5. Les deux avis clôturent le trade.
  `/trade-fermer` permet de terminer une transaction annulée ou inachevée.
- `/trade-profil` affiche la moyenne et le nombre d'avis reçus.

## Modération et journaux

- `/warn`, `/warns` et `/warn-retirer` gèrent les avertissements persistants.
- `/timeout` et `/timeout-retirer` gèrent les exclusions temporaires Discord.
- `/sanctions` affiche l'historique enregistré d'un membre.
- Chaque sanction reçoit un numéro de dossier et les warns/timeouts peuvent être
  annulés depuis leur bouton dans le journal.
- À 3, 5 et 7 avertissements actifs, le bot applique automatiquement un timeout
  d'une heure, d'un jour puis de sept jours.
- `/note-ajouter`, `/notes-joueur` et `/note-retirer` gèrent les notes internes,
  invisibles aux membres et aux Helpers.
- `/staff-statistiques` affiche le classement mensuel ou le détail d'un membre du
  staff : sanctions, tickets claim/clôturés et temps moyen de réponse.
- Les arrivées/départs, mouvements vocaux, messages supprimés, messages
  modifiés, sanctions et transcriptions possèdent chacun leur propre salon.
- `🧾・logs-discord` est créé automatiquement au démarrage et journalise les
  actions du staff issues de l'audit Discord : déplacements et déconnexions
  vocales, surnoms, salons, rôles, permissions, sanctions et autres changements.
- Le bot doit posséder les permissions `Voir le journal d'audit` et
  `Gérer les salons` pour assurer ce suivi et recréer le salon s'il est absent.

## Gestion avancée des équipages

- Le capitaine reçoit automatiquement en MP le guide de toutes ses commandes.
- `/equipage-inviter`, `/equipage-exclure`, `/equipage-membres` et
  `/equipage-limite` assurent la gestion quotidienne.
- `/equipage-vice-capitaine` désigne un second disposant des droits de gestion.
- `/equipage-transferer` transmet définitivement la capitainerie et
  `/equipage-commandes` renvoie le guide privé.
- `/equipage-classement` compare l'XP cumulée des membres de chaque équipage.
- Chaque arrivée, départ, exclusion, nomination et changement important est
  enregistré dans le salon privé de l'équipage.

## Suggestions

- `/suggestion` ouvre un formulaire dans le salon des suggestions.
- Les boutons Pour et Contre enregistrent un vote unique et modifiable.
- `/suggestion-statut` permet au staff d'accepter, refuser, remettre en attente
  ou marquer comme réalisée une suggestion avec une réponse officielle.

## Événements

- `/evenement-creer` publie un événement avec bouton d'inscription, nombre de
  places et liste d'attente automatique.
- Les rappels sont envoyés 24 heures et 30 minutes avant le début.
- `/evenement-annuler` et `/evenement-terminer` ferment les inscriptions.
- `/evenement-resultats` publie le podium et attribue les rôles Champion,
  Finaliste et Troisième événement.
