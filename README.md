# Bot Discord communautaire pour studio Roblox

Bot Discord destiné à la communauté d'un studio de création Roblox. La commande administrateur `/setup`
reconstruit automatiquement la structure complète de chaque serveur où il est
utilisé, sans nom, identifiant ou marque imposés.

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
   - `DISCORD_GUILD_ID` : facultatif. Indique un serveur pendant le développement
     pour synchroniser les commandes presque immédiatement. Laisse vide pour un
     fonctionnement universel sur tous les serveurs où le bot est invité.
   - `PRESERVED_SETUP_CHANNEL_IDS` : facultatif. Liste d'identifiants séparés par
     des virgules pour protéger certains salons lors de `/setup`.

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

- `/setup` est strictement réservé aux administrateurs. Il supprime les salons
  et catégories non protégés, ferme les données dynamiques devenues invalides,
  puis recrée les rôles, permissions, salons, panneaux et messages automatiques.
- Les salons renseignés dans `PRESERVED_SETUP_CHANNEL_IDS` ne sont jamais
  supprimés par `/setup`.
- Les permissions d'écriture sont appliquées salon par salon. Le règlement,
  les annonces, l'avancement, les mises à jour, l'admin abuse, la roadmap et
  les informations sur les jeux sont en lecture seule pour les membres.
- Les discussions, médias, clips, suggestions, signalements de bugs et espaces
  de création Roblox restent ouverts aux membres vérifiés.
- Toutes les catégories utilisent le décor `○─────Nom─────➤`.
- Les espaces Jeux, Tests, Événements, Création Roblox et Partenariat sont inclus. Seul le rôle
  `🤝・Partenaire` peut écrire dans le chat partenaire.
- Elle crée les rôles du studio, communautaires, de notifications, de plateformes
  Roblox et de progression qui n'existent pas encore.
- Elle attribue le rôle `👑・Fondateur` au propriétaire du serveur.
- Elle publie trois menus de rôles persistants dans `🎭・choix-des-rôles`.
- La catégorie `🔒・ÉQUIPE` est visible uniquement par les rôles du staff.
- Elle applique les limites visibles aux salons vocaux.
- Le bot attribue `🔒・Non vérifié` à l'arrivée et publie un message de bienvenue.
- Le nouveau membre ne voit que la catégorie `🔐・VÉRIFICATION`. Après validation
  du règlement avec le bouton persistant, il reçoit `✅・Membre` et accède au serveur.
- Le règlement complet est publié dans `📜・règlement`.
- Les bots reçoivent automatiquement le rôle `🤖・Bots`.
- Rejoindre `➕・Créer un vocal` crée un vocal `Vocal de …`, y déplace le
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

- `/setup` publie un centre unique permettant d'ouvrir un ticket Assistance,
  Partenariat, Signalement, Bug, Problème d'achat ou Appel de sanction.
- Chaque formulaire crée un salon privé visible par son auteur et le staff.
- Un membre ne peut ouvrir qu'un ticket de chaque type à la fois.
- Les helpers accèdent uniquement aux tickets Assistance et Signalement.
- Le rôle `🆘・Helper` est créé ou migré automatiquement au démarrage, sans
  permission sensible.
- Lorsqu'un helper claim un ticket, les autres helpers n'y ont plus accès. Le
  staff supérieur conserve toujours l'accès.
- Chaque claim est envoyé dans `📨・tickets-staff` avec le ticket, son auteur,
  le membre du staff assigné, ainsi que la date et l'heure exactes.
- Un ticket résolu peut toujours rapporter un point au helper assigné, sans
  créer de salon de classement public ou privé.
- `/helper-ajouter`, `/helper-retirer` et `/helper-points-definir` permettent au
  staff de gérer les Helpers.
- Un Helper peut uniquement consulter `/warns` et `/infos-joueur` parmi les
  commandes réservées à l'équipe.
- L'auteur ou le staff peut demander sa fermeture, avec confirmation.
- Une transcription texte est envoyée dans `📁・transcripts-tickets` et conservée
  localement dans le dossier `transcripts`.

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

## Studio Roblox

- Les salons Avancement, Mises à jour, Admin Abuse, Nouveaux jeux et Roadmap
  permettent à l'équipe de communiquer sans que les annonces soient noyées.
- La catégorie Nos jeux regroupe le jeu principal, les projets en développement,
  les anciens jeux, les liens officiels et le statut des serveurs.
- Les bêta-testeurs disposent de salons réservés pour leurs retours et rapports.
- Les espaces Développement, Building, UI, modélisation, son et ressources
  facilitent les échanges autour de la création Roblox.
- Les anciennes commandes d'équipages Blox Fruits, de CV joueur et de trades
  ne sont plus synchronisées sur Discord.

## Modération et journaux

- `/warn`, `/warns` et `/warn-retirer` gèrent les avertissements persistants.
- `/timeout` et `/timeout-retirer` gèrent les exclusions temporaires Discord.
- `/clear nombre [membre]` supprime entre 1 et 500 messages récents, avec un
  filtre facultatif par membre. Le nombre est toujours obligatoire, les messages
  épinglés sont conservés et l'action est envoyée dans `🧾・logs-discord`.
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
