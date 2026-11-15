# 01 — Architecture

## 1. Vue d'ensemble

Le système comporte trois parties :

1. **Les écrans** (reTerminal E1001) : un firmware minimal qui ne fait aucune logique métier. À chaque
   réveil, l'écran envoie sa télémétrie, reçoit une image toute faite, l'affiche, puis se rendort pour la
   durée que le serveur lui indique.
2. **Le serveur** (conteneur `server`) : importe les emplois du temps, calcule l'état de chaque salle,
   génère les images, décide de l'heure du prochain réveil de chaque écran, distribue les mises à jour
   OTA et sert l'interface d'administration.
3. **Les outils** :
   - conteneur `firmware` : compilation, publication, flash USB, simulation ;
   - page web `/flash` : premier flash et configuration d'un écran depuis le navigateur ;
   - conteneur `caddy` : HTTPS pour l'administration.

Comme toute l'intelligence est côté serveur, on peut changer la mise en page, les règles de réveil ou le
format d'import **sans toucher aux écrans**.

## 2. Composants

### 2.1 Écran — reTerminal E1001

| Élément | Détail |
|---|---|
| SoC | ESP32-S3, 8 Mo PSRAM, Wi-Fi 2,4 GHz uniquement |
| Écran | 7,5" e-paper, 800×480, noir et blanc, rafraîchissement complet en 2 à 5 s |
| Énergie | batterie LiPo 2000 mAh, recharge USB-C |
| Bouton blanc droit (GPIO4) | réveil immédiat + rafraîchissement forcé |
| Firmware | `firmware/src/main.cpp` (Arduino ESP32, GxEPD2) |

Le firmware conserve en mémoire RTC, qui survit au deep sleep :
- l'ETag de l'image affichée ;
- le canal et le BSSID du point d'accès, pour une reconnexion rapide ;
- les compteurs de démarrages et d'échecs.

La configuration réseau (SSID, mot de passe, URL du serveur, IP statique, passerelle, masque, DNS) est
d'abord compilée dans le firmware comme valeurs par défaut, puis peut être surchargée écran par écran en
NVS (mémoire flash non volatile) lors de la mise en service.

### 2.2 Serveur — conteneur `server`

| Module | Rôle |
|---|---|
| `app/main.py` | routes HTTP : protocole des écrans, API d'administration, pages web |
| `app/scheduling.py` | état d'une salle à un instant donné et calcul du prochain réveil |
| `app/render.py` | rendu Pillow 800×480 et conversion en bitmap 1 bit par pixel |
| `app/importers.py` | import ICS (avec dépliage des récurrences) et CSV |
| `app/db.py` | SQLite (stdlib), schéma, migrations, réglages |
| `app/cli.py` | commandes d'exploitation : sauvegarde, import, purge |
| `app/static/` | interface d'administration (HTML/JS sans framework) et flasheur web (ESP Web Tools embarqué) |

Le serveur tourne avec un seul processus uvicorn : SQLite est protégé par un verrou applicatif. C'est
largement suffisant, puisqu'un écran fait au plus une requête toutes les 30 minutes.

### 2.3 Outils

- **`firmware` (profil `tools`)** : image PlatformIO avec la toolchain ESP32 et les bibliothèques
  pré-installées. La compilation fonctionne donc hors ligne. Sous-commandes : `build`, `flash`,
  `provision`, `simulate`, `shell`.
- **`caddy` (profil `https`)** : reverse proxy TLS vers `server:8000`. Il fournit le contexte sécurisé
  qu'exige l'API Web Serial pour le flash depuis le navigateur.

## 3. Flux principaux

### 3.1 Cycle de réveil d'un écran

```
réveil (timer | bouton | mise sous tension)
  │
  ├─ [mise sous tension uniquement] fenêtre de configuration série de 3 s
  ├─ mesure de la tension batterie
  ├─ connexion Wi-Fi : IP statique, canal et BSSID mémorisés (moins de 1 s ; sinon scan complet)
  ├─ GET /api/v1/display + télémétrie dans les en-têtes + If-None-Match
  │     ├─ 200 → lecture de 48 000 octets → Wi-Fi coupé → rafraîchissement de l'écran (≈3 s)
  │     └─ 304 → rien à afficher
  ├─ [si X-FW-URL] téléchargement OTA → redémarrage
  └─ deep sleep pendant X-Sleep-Seconds
```

En cas d'échec (Wi-Fi, serveur, image incomplète), l'écran garde l'affichage précédent et réessaie après
2 min, puis 5, 10, 30 et 60 min. À la mise sous tension, il affiche aussi un écran de diagnostic.

### 3.2 Import d'un emploi du temps

```
fichier ICS/CSV ──▶ parseur ──▶ découpage des salles ("A101, A102") ──▶ correspondance avec les salles
   (interface, CLI ou API)                                               (création auto. si activée)
                                         │
                                         ▼
                    suppression des cours existants sur la période couverte (mode par défaut)
                                         │
                                         ▼
                    insertion + marquage « rafraîchissement forcé » des écrans concernés
```

### 3.3 Chaîne firmware

```
.env (Wi-Fi, IP serveur, version) ──▶ conteneur firmware : génère config_local.h ──▶ pio run
      ──▶ firmware.bin (OTA) + factory.bin (fusion bootloader/partitions/app) ──▶ ./builds/<version>/
      ──▶ publication sur le serveur ──▶ [activation] ──▶ OTA de toute la flotte au réveil suivant
                                     └─▶ page /flash : premier flash d'un écran neuf
```

## 4. Protocole écran ↔ serveur

### Requête — `GET /api/v1/display`

| En-tête | Exemple | Usage |
|---|---|---|
| `X-Device-MAC` | `D8:3B:DA:12:34:56` | identifiant unique de l'écran |
| `X-FW-Version` | `0.2.0` | déclenche l'OTA si différente de la version active |
| `X-Battery-mV` | `3912` | converti en % côté serveur (courbe LiPo) |
| `X-RSSI` | `-63` | qualité du signal Wi-Fi |
| `X-IP` | `10.20.0.31` | affichage et contrôle du plan d'adressage |
| `X-Wake-Reason` | `timer` / `button` / `power_on` | `button` et `power_on` forcent le rafraîchissement |
| `X-Boot-Count`, `X-WiFi-ms`, `X-Fail-Count` | | diagnostic |
| `If-None-Match` | `3f2a9c…` | ETag de l'image actuellement affichée |

### Réponse

| Code | Corps | En-têtes |
|---|---|---|
| `200` | 48 000 octets : 800×480, 1 bit par pixel, ligne par ligne, MSB en premier, **bit à 1 = noir** | `ETag`, `X-Sleep-Seconds`, `X-Server-Time`, éventuellement `X-FW-URL`, `X-FW-SHA256` |
| `304` | vide | `X-Sleep-Seconds`, … |

Le format brut évite tout décodage d'image sur l'ESP32. L'ETag est un hash du bitmap : l'écran ne se
rafraîchit donc que si l'image change réellement.

## 5. Politique de réveil

C'est le principal facteur d'autonomie. Le serveur calcule le prochain réveil comme suit :

| Situation | Prochain réveil |
|---|---|
| Écran non affecté | dans `unassigned_sleep` secondes (5 min par défaut) |
| Avant `day_start` un jour ouvré | à `day_start` |
| En journée, avec un changement de créneau à venir | au plus tôt entre la prochaine frontière (début ou fin de cours) + 10 s et maintenant + `max_awake_interval` (30 min par défaut) |
| Plus aucun changement prévu aujourd'hui, après `day_end`, ou jour non ouvré | au prochain `day_start` d'un jour ouvré |

Trois mécanismes complètent ce calcul :
- **Lecture anticipée de 60 s** : l'état affiché est celui « dans 60 s ». Un écran qui se réveille un peu
  tôt affiche donc déjà le bon créneau.
- **Compensation de dérive** : l'horloge RTC de l'ESP32 dérive de quelques % en deep sleep. Au-delà de
  30 min, le serveur vise 3 % plus tôt. Un réveil précoce reçoit simplement un 304 et le temps restant.
- **Image stable** : l'image ne contient pas l'heure courante. Elle ne change qu'aux frontières de créneau,
  et les réveils de sécurité se terminent donc presque toujours en 304, sans rafraîchir l'écran.

Ordre de grandeur pour une salle à 4 cours par jour : environ 8 réveils avec rafraîchissement et 15 à 20
réveils en 304 par jour ouvré.

## 6. Modèle de données (SQLite)

| Table | Contenu |
|---|---|
| `rooms` | `code` (clé, tel qu'il apparaît dans l'EDT), `name`, `building`, `message` (bandeau) |
| `events` | `room_code`, `start`, `end` (heure locale, sans fuseau), `title`, `teacher`, `grp`, `source` |
| `devices` | `mac` (clé), `name`, `room_code`, dernière télémétrie, `last_seen`, `next_wake`, `last_etag`, `force_refresh`, compteurs |
| `telemetry` | historique par réveil : batterie, RSSI, durée de connexion Wi-Fi, rafraîchi ou non |
| `firmware` | versions publiées : image OTA, image complète (factory), sha256, `active` |
| `settings` | réglages clé/valeur (horaires, jours ouvrés, seuils, plage d'IP…) |

Les données sont dans le volume Docker `epaper-data` (`/data`) : `epaper.db`, `firmware/`, `backups/`.

## 7. Choix techniques

| Choix | Raison |
|---|---|
| Firmware « terminal passif » | aucune mise à jour firmware nécessaire pour faire évoluer l'affichage ; firmware simple donc robuste |
| Bitmap brut plutôt que PNG | pas de décodeur sur l'ESP32, 48 ko transférés en moins d'une seconde |
| IP statique + BSSID mémorisé | connexion en moins de 1 s au lieu de 3 à 4 s : c'est le premier poste de consommation |
| SQLite | aucune dépendance externe, sauvegarde à chaud triviale, volumétrie très faible |
| Pas de framework JS | interface maintenable sans chaîne de build front-end |
| ESP Web Tools embarqué | flash depuis le navigateur, sans outil sur le poste ni accès Internet |
