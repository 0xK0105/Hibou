# 07 — Référence de l'API

URL de base : `http://<serveur>:8000` (ou `https://<EPAPER_HOSTNAME>` via Caddy).
Le schéma OpenAPI complet est disponible sur `/openapi.json`. La documentation interactive `/docs`
nécessite un accès Internet depuis le navigateur, car elle charge Swagger UI depuis un CDN.

> ⚠ Aucune authentification pour l'instant ([08 — Sécurité](08-securite.md)).

Toutes les dates et heures sont en heure locale du site (réglage `timezone`), au format ISO 8601 sans fuseau :
`2026-11-16T08:00:00`.

## 1. Protocole des écrans

| Méthode | Chemin | Description |
|---|---|---|
| `GET` | `/api/v1/display` | réveil d'un écran : télémétrie en en-têtes → bitmap ou 304 ([01 § 4](01-architecture.md#4-protocole-écran--serveur)) |
| `GET` | `/api/v1/firmware/{version}.bin` | image OTA |
| `GET` | `/api/v1/firmware/{version}/factory.bin` | image complète (flash navigateur) |
| `GET` | `/api/v1/firmware/{version}/manifest.json` | manifeste ESP Web Tools |

## 2. Salles et planning

| Méthode | Chemin | Corps / paramètres | Description |
|---|---|---|---|
| `GET` | `/api/rooms` | | salles, avec état actuel, nombre de cours du jour et écrans affectés |
| `POST` | `/api/rooms` | `{"code","name","building","message"}` | créer une salle |
| `PATCH` | `/api/rooms/{code}` | `{"name"?, "building"?, "message"?}` | modifier (force le rafraîchissement des écrans de la salle) |
| `DELETE` | `/api/rooms/{code}` | | supprimer la salle et ses cours |
| `GET` | `/api/rooms/{code}/events` | `?day=AAAA-MM-JJ&days=N` | cours d'une salle (N jours, 60 maximum) |
| `POST` | `/api/rooms/{code}/events` | `{"start","end","title","teacher","grp"}` | ajouter un cours ponctuel |
| `DELETE` | `/api/events/{id}` | | supprimer un cours |
| `DELETE` | `/api/events` | | ⚠ supprimer **tous** les cours |
| `GET` | `/api/rooms/{code}/preview.png` | `?at=AAAA-MM-JJTHH:MM` | aperçu de l'écran à un instant donné |
| `POST` | `/api/import` | multipart : `file`, `mode` (`replace_range`, `append`, `replace_all`), `create_rooms` (`true`/`false`) | importer un EDT ; renvoie le compte rendu |

## 3. Écrans

| Méthode | Chemin | Corps / paramètres | Description |
|---|---|---|---|
| `GET` | `/api/devices` | | liste avec télémétrie et `status` (`en ligne`, `hors ligne`, `jamais vu`) |
| `GET` | `/api/devices/{mac}` | | détail |
| `PATCH` | `/api/devices/{mac}` | `{"name"?, "room_code"?, "notes"?}` | modifier ou pré-enregistrer un écran ; `room_code: ""` = désaffecter |
| `DELETE` | `/api/devices/{mac}` | | oublier l'écran |
| `POST` | `/api/devices/{mac}/refresh` | | forcer le rafraîchissement au prochain réveil |
| `GET` | `/api/devices/{mac}/telemetry` | `?days=14` | historique batterie, RSSI et connexion |
| `GET` | `/api/devices/{mac}/preview.png` | | ce que l'écran affiche (ou affichera) |

## 4. Firmware et mise en service

| Méthode | Chemin | Corps | Description |
|---|---|---|---|
| `GET` | `/api/firmware` | | versions publiées |
| `POST` | `/api/firmware` | multipart : `version`, `file` (firmware.bin), `factory`? (factory.bin), `notes`? | publier |
| `POST` | `/api/firmware/{version}/activate` | | activer (OTA de la flotte) |
| `POST` | `/api/firmware/deactivate` | | suspendre l'OTA |
| `DELETE` | `/api/firmware/{version}` | | supprimer |
| `GET` | `/api/provision/next-ip` | | prochaine IP libre de la plage configurée |
| `POST` | `/api/provision/{mac}` | `?ip=…` + `{"name"?, "room_code"?}` | enregistrer un écran après configuration USB |

## 5. Réglages et état

| Méthode | Chemin | Description |
|---|---|---|
| `GET` | `/api/settings` | réglages |
| `PUT` | `/api/settings` | `{"clé": "valeur", …}` ; clés : `timezone`, `day_start`, `day_end`, `active_days`, `max_awake_interval`, `unassigned_sleep`, `low_battery_pct`, `offline_after_min`, `site_name`, `prov_ip_first`, `prov_ip_last` |
| `GET` | `/api/overview` | synthèse de la flotte (supervision) |
| `GET` | `/healthz` | sonde de disponibilité |

## 6. Exemples d'automatisation

**Synchroniser chaque nuit l'EDT depuis l'URL iCal du logiciel de planning** (ADE, Hyperplanning…, qui
fournissent souvent une URL d'export) :
```bash
# /etc/cron.d/hibou-edt — tous les jours à 5h30
30 5 * * * root curl -fsS "https://planning.exemple.fr/export.ics?projet=…" -o /tmp/edt.ics \
  && curl -fsS -F file=@/tmp/edt.ics -F mode=replace_range http://localhost:8000/api/import
```

**Mettre un bandeau sur toutes les salles d'un bâtiment** :
```bash
for code in $(curl -s localhost:8000/api/rooms | jq -r '.[] | select(.building=="B") | .code'); do
  curl -s -X PATCH -H 'Content-Type: application/json' \
       -d '{"message":"Exercice incendie à 10h"}' "localhost:8000/api/rooms/$code"
done
```

**Lister les écrans à recharger** :
```bash
curl -s localhost:8000/api/devices | jq -r '.[] | select(.battery_pct != null and .battery_pct < 30)
  | "\(.room_code)\t\(.name)\t\(.battery_pct)%"'
```

**Simuler un écran** (tests, sans matériel) :
```bash
curl -s -o image.bin -D - http://localhost:8000/api/v1/display \
  -H 'X-Device-MAC: AA:BB:CC:00:00:01' -H 'X-Battery-mV: 3900' -H 'X-FW-Version: 0.2.0' -H 'X-Wake-Reason: timer'
```
