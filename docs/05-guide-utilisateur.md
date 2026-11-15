# 05 — Guide utilisateur (interface d'administration)

L'interface s'ouvre à l'adresse `https://<serveur>` (ou `http://<serveur>:8000`). Elle comporte quatre
onglets et la page **Mise en service**. Le bandeau du haut résume l'état de la flotte : écrans en ligne,
hors ligne, batterie faible, non affectés.

## 1. Ce qu'affichent les écrans

```
┌──────────────────────────────────────────────────────────────┐
│ A101   Salle de TP réseaux                 Lundi 16 novembre │  ← code, nom, date
├──────────────────────────────────────────────────────────────┤
│ [OCCUPÉE] jusqu'à 12h15                                      │  ← état actuel
│ Cybersécurité — Pentest   Mme Leroy · TP A                   │
│──────────────────────────────────────────────────────────────│
│ 8h00 – 10h00   Réseaux IP avancés — M. Martin · TD1   (barré)│  ← cours du jour
│ ███ 10h15 – 12h15 Cybersécurité — Pentest ██████████████████ │     (en cours = inversé)
│ 13h30 – 15h30  Anglais technique — Mme Brown · TD2           │
│  ▒▒▒▒▒▒ ███▼██      ████   ███                               │  ← frise de la journée
│ 7h  8h  9h  10h  11h  12h  13h  14h  …                       │     (passé hachuré)
└──────────────────────────────────────────────────────────────┘
```
- **LIBRE jusqu'à 13h30 / Ensuite : …** quand la salle est libre ;
- **LIBRE toute la journée** quand il n'y a aucun cours ;
- un **bandeau** encadré en haut si un message est défini pour la salle ;
- « Batterie faible — à recharger » en bas à droite sous le seuil configuré.

L'écran se met à jour **à chaque début et fin de cours**, et au plus tard toutes les 30 min en journée pour
prendre en compte les changements. Une modification peut donc mettre jusqu'à 30 min pour apparaître. Pour
un affichage immédiat, appuyer sur le **bouton blanc de droite** de l'écran.

## 2. Onglet Planning

### 2.1 Importer un emploi du temps
1. Glisser le fichier `.ics` ou `.csv` dans la zone d'import, ou cliquer pour le choisir.
2. Choisir le mode :

   | Mode | Effet | Quand l'utiliser |
   |---|---|---|
   | **Remplacer la période couverte par le fichier** (défaut) | supprime les cours des salles concernées entre la première et la dernière date du fichier, puis importe | import hebdomadaire ou mensuel : les cours annulés disparaissent |
   | Ajouter aux cours existants | importe sans rien supprimer | ajout d'un planning complémentaire (examens, réservations) |
   | Tout remplacer | vide toute la base de cours, puis importe | changement de semestre |

3. **Importer**. Le compte rendu indique le nombre de cours, les salles créées et les lignes ignorées
   (avec la raison).

**Formats acceptés**
- **ICS** : export iCalendar des logiciels d'emploi du temps (ADE, Hyperplanning, EDT…). La salle est lue
  dans le champ *Lieu* (`LOCATION`).
- **CSV** (séparateur `;` ou `,`), première ligne = en-têtes :
  ```
  date;debut;fin;salle;matiere;enseignant;groupe
  16/11/2026;08:00;10:00;A101;Réseaux IP;M. Martin;TD1
  ```
  Colonnes obligatoires : `debut`, `fin`, `salle`. Les noms de colonnes sont tolérants (`salle`, `room`,
  `lieu`…). Plusieurs salles séparées par une virgule = le cours est dupliqué dans chacune.

> Les salles sont reconnues par leur **code exact**, sans tenir compte des majuscules. « A101 » et « A 101 »
> sont deux salles différentes : harmoniser l'export ou renommer.

### 2.2 Gérer une salle
Cliquer sur une salle dans la liste pour ouvrir sa fiche :
- **Aperçu** : l'image exacte que verra l'écran. Changer la date ou l'heure pour simuler un autre moment ;
  **Maintenant** revient à l'heure réelle.
- **Nom affiché** et **bâtiment**.
- **Bandeau d'information** : message affiché en haut de l'écran (« Salle fermée pour travaux »,
  « Cours déplacé en B204 »…). Le vider pour le retirer.
- **Cours du jour** : liste avec suppression (✕) d'un cours, par exemple un cours annulé.
- **Ajouter un cours ponctuel** : réservation, examen, réunion.

Après chaque modification, les écrans concernés se rafraîchissent à leur prochain réveil (30 min maximum).

## 3. Onglet Écrans

Tableau de la flotte :

| Colonne | Signification |
|---|---|
| ● | vert : en ligne ; rouge : hors ligne (pas venu à l'heure prévue) ; gris : jamais vu |
| Écran | nom et adresse MAC |
| Salle | salle affichée ; « non affecté » en orange |
| Batterie | niveau en % (tension au survol) ; rouge sous le seuil |
| Wi-Fi | force du signal en dBm |
| Dernier contact / Prochain réveil | « en retard » si le réveil prévu est dépassé |

Cliquer sur un écran pour ouvrir sa fiche :
- l'aperçu de ce qu'il affiche ;
- le **nom**, la **salle** (affectation ou changement) et des **notes** (emplacement, fixation…) ;
- les détails techniques et l'historique de la batterie et du signal sur 14 jours ;
- **Forcer le rafraîchissement** : l'image sera redessinée au prochain réveil ;
- **Oublier cet écran** : le supprime de la liste. S'il se reconnecte, il réapparaît « non affecté ».

La liste se rafraîchit automatiquement toutes les 30 s.

## 4. Onglet Firmware

- Liste des versions publiées, avec le nombre d'écrans à chaque version.
- **Activer** : déploie la version sur toute la flotte (au réveil suivant de chaque écran).
- **Désactiver** : suspend toute mise à jour.
- L'upload manuel d'un `firmware.bin` est possible. Normalement, c'est le conteneur de build qui publie
  ([03](03-firmware-et-flash.md)).

## 5. Onglet Réglages

| Réglage | Défaut | Effet |
|---|---|---|
| Nom du site | vide | pied de page des écrans |
| Début / fin de journée | 07:30 / 19:00 | premier réveil du matin ; au-delà de la fin, les écrans dorment jusqu'au lendemain |
| Jours ouvrés | 1,2,3,4,5 | 1 = lundi … 7 = dimanche ; ajouter 6 si cours le samedi |
| Réveil de sécurité | 30 min | délai maximal d'apparition d'une modification. Plus court = plus réactif mais plus de consommation |
| Sommeil d'un écran non affecté | 300 s | fréquence de réveil des écrans en attente d'affectation |
| Seuil batterie faible | 15 % | alerte dans l'interface et sur l'écran |
| Hors ligne après | 90 min | retard toléré avant de marquer un écran hors ligne |
| Fuseau horaire | Europe/Paris | |
| Plage IP des écrans | | IP proposées lors de la mise en service |

## 6. Questions fréquentes

**J'ai modifié un cours mais l'écran affiche encore l'ancien.**
Il se mettra à jour dans 30 min au plus. Pour un affichage immédiat : bouton blanc de droite sur l'écran.

**Un écran affiche « Écran non affecté ».**
Onglet **Écrans** → cliquer dessus → choisir la salle → **Enregistrer**.

**Comment préparer la semaine suivante ?**
Importer le fichier de la semaine suivante en mode « Remplacer la période couverte » : la semaine en cours
n'est pas modifiée.

**Le week-end, les écrans affichent-ils quelque chose ?**
Ils gardent l'affichage du vendredi soir (l'e-paper ne consomme rien à l'arrêt), puis se mettent à jour
le lundi à l'heure de début de journée.
