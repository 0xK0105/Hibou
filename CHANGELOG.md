# Historique des versions

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Le serveur et le firmware sont versionnés
séparément ; la version firmware est celle annoncée par les écrans (`FW_VERSION`).

## [Serveur 0.2.1] — 2026-11-15
### Modifié
- Projet renommé **Hibou** : nom du projet Docker Compose `hibou`, images `hibou/server` et `hibou/firmware`,
  interface et documentation. ⚠ Le volume de données devient `hibou_epaper-data` (voir README, « Migration
  depuis affichage-salles »).
### Ajouté
- Licence MIT, `THIRD_PARTY_NOTICES.md`.

## [Firmware 0.1.1] — 2026-11-15
### Ajouté
- Diagnostic Wi-Fi : en cas d'échec, scan des réseaux visibles. L'écran de diagnostic indique si le SSID est vu
  (canal, RSSI, sécurité) ou introuvable, avec la liste des réseaux captés. Le code d'échec est en clair dans le journal série.
### Modifié
- Pays Wi-Fi fixé à FR (canaux 1 à 13 en scan actif), scan de tous les canaux, connexion au point d'accès le plus fort,
  sécurité minimale WPA.

## [Serveur 0.2.0] — 2026-11-14
### Ajouté
- Déploiement entièrement conteneurisé :
  - `server` : utilisateur non privilégié, healthcheck, volume `epaper-data` ;
  - `caddy` (profil `https`) : reverse proxy TLS ;
  - `firmware` (profil `tools`) : compilation PlatformIO hors ligne, fusion `factory.bin`, publication et
    activation OTA, flash USB, provisioning et simulation.
- Configuration centralisée dans `.env`. Réglages initiaux via `EPAPER_DEFAULT_*`.
- Page **Mise en service** (`/flash`) : premier flash depuis le navigateur (ESP Web Tools embarqué) et
  configuration de l'écran par Web Serial (IP, salle, nom), avec suggestion automatique de la prochaine IP libre.
- Endpoints `/api/v1/firmware/{v}/factory.bin`, `/manifest.json`, `/api/provision/*` et `/healthz`.
- CLI d'exploitation `python -m app.cli` : `backup`, `import`, `info`, `purge-telemetry`.
- `Makefile` de raccourcis d'exploitation.
- Documentation complète (`docs/01` à `docs/08`).

### Modifié
- `FW_VERSION` n'est plus dans `platformio.ini` : elle est générée depuis `.env`.

## [Serveur 0.1.0] — 2026-11-14
### Ajouté
- API des écrans (bitmap 1 bpp, ETag/304, calcul du prochain réveil, OTA).
- Import ICS/CSV, rendu des écrans, interface d'administration (Planning, Écrans, Firmware, Réglages).

## [Firmware 0.1.0] — 2026-11-14
### Ajouté
- Cycle réveil → télémétrie → image → deep sleep ; reconnexion Wi-Fi rapide (IP statique + BSSID mémorisé).
- Provisioning série (`INFO`/`GET`/`SET`/`CLEAR`/`DONE`) ; écran de diagnostic à la mise sous tension.
- OTA HTTP avec garde-fou batterie ; réveil et rafraîchissement forcé par le bouton blanc de droite.
