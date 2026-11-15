# 🦉 Hibou

**Affichage e-paper de l'occupation des salles de cours.**

Des écrans e-paper **Seeed reTerminal E1001** (ESP32-S3, 7,5", 800×480 noir et blanc, sur batterie) sont
fixés à l'entrée des salles de cours. Chacun affiche l'occupation de sa salle sur la journée. Un serveur web
importe l'emploi du temps, génère l'image de chaque salle et supervise la flotte : batterie, signal Wi-Fi,
version de firmware, dernier contact.

**Tout se déploie avec Docker** : le serveur, le reverse proxy HTTPS, la compilation du firmware, et même le
premier flash des écrans, qui se fait depuis le navigateur. Le poste d'administration n'a besoin que de
Docker et de Chrome.

```
 Écrans (Wi-Fi dédié, IP fixes)          Serveur Docker                         Postes d'administration
┌─────────────────────┐   HTTP :8000   ┌──────────────────────────────┐  HTTPS  ┌──────────────────────┐
│ reTerminal E1001 ×N │ ─────────────▶ │ server  (FastAPI + SQLite)   │ ◀────── │ Chrome / Edge        │
│ deep sleep, réveil  │ ◀───────────── │ caddy   (HTTPS admin, opt.)  │         │ admin + flash USB    │
│ aux changements de  │  image 1 bpp   │ firmware (outil de build,    │         │ (Web Serial)         │
│ créneau             │  + OTA         │           à la demande)      │         └──────────────────────┘
└─────────────────────┘                └──────────────────────────────┘
```

## Démarrage rapide

```bash
git clone https://github.com/0xK0105/Hibou.git hibou && cd hibou
cp .env.example .env              # Wi-Fi des écrans, IP du serveur, plage d'IP…
docker compose up -d              # serveur sur http://<serveur>:8000
docker compose run --rm firmware  # compile le firmware et le publie sur le serveur
```
Ouvrir ensuite `http://<serveur>:8000` pour l'administration, et `https://<serveur>/flash` pour mettre en
service un écran (profil HTTPS : `docker compose --profile https up -d`).

Procédure complète : **[docs/02-installation.md](docs/02-installation.md)**.

## Documentation

| Document | Pour qui | Contenu |
|---|---|---|
| [01 — Architecture](docs/01-architecture.md) | tous | composants, flux, protocole écran ↔ serveur, politique de réveil, modèle de données |
| [02 — Installation](docs/02-installation.md) | admin système | prérequis réseau, déploiement Docker, `.env`, HTTPS, premier démarrage, mise à jour |
| [03 — Firmware et flash](docs/03-firmware-et-flash.md) | admin / dev | compilation en conteneur, versions, OTA, flash navigateur ou USB, provisioning |
| [04 — Mise en service des écrans](docs/04-mise-en-service.md) | technicien | procédure terrain pas à pas, plan d'adressage, fiche de recette |
| [05 — Guide utilisateur](docs/05-guide-utilisateur.md) | gestionnaire planning | import EDT, salles, cours ponctuels, bandeaux, écrans, réglages |
| [06 — Exploitation](docs/06-exploitation.md) | admin système | supervision, sauvegarde et restauration, batteries, dépannage |
| [07 — API](docs/07-api.md) | dev / intégration | référence des endpoints, exemples d'automatisation |
| [08 — Sécurité](docs/08-securite.md) | RSSI / admin | état actuel, risques, feuille de route de durcissement |
| [CHANGELOG](CHANGELOG.md) | tous | historique des versions |

## Arborescence

```
.
├── docker-compose.yml      # server + caddy (profil https) + firmware (profil tools)
├── .env.example            # toute la configuration du déploiement
├── Makefile                # raccourcis (make up, make fw, make backup…)
├── deploy/Caddyfile        # reverse proxy HTTPS
├── server/                 # API + interface web (FastAPI, SQLite, Pillow) + tests
├── firmware/               # firmware PlatformIO + Dockerfile de la chaîne de compilation
├── tools/                  # provision.py, simulate_device.py, make_sample_data.py
├── imports/                # dépôt de fichiers EDT (monté en lecture seule dans le serveur)
├── builds/                 # artefacts firmware compilés (firmware.bin, factory.bin)
└── docs/                   # documentation
```

## Commandes utiles

```bash
make help                 # liste des raccourcis
make up HTTPS=1           # serveur + HTTPS
make fw FW_VERSION=0.3.0  # compiler et publier un firmware
make backup               # sauvegarde de la base dans ./backups
make logs                 # journaux du serveur
docker compose run --rm firmware simulate --count 3   # simuler 3 écrans sans matériel
```

## Migration depuis « affichage-salles »

Les premières versions s'appelaient `affichage-salles`. Le nom du projet Compose a changé : il faut arrêter
l'ancienne stack, puis copier la base vers le nouveau volume.
```bash
cd ~/affichage-salles && docker compose --profile https down          # libère les ports
docker volume create hibou_epaper-data
docker run --rm -v affichage-salles_epaper-data:/from -v hibou_epaper-data:/to alpine sh -c "cp -a /from/. /to/"
cd ~/hibou && cp ~/affichage-salles/.env . && docker compose up -d --build
```

## Licence

[MIT](LICENSE). Composants tiers : voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
