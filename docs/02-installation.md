# 02 — Procédure d'installation

Cette procédure part d'un serveur Linux vierge et va jusqu'au premier écran fonctionnel. Compter environ
1 h, dont une grande partie d'attente pendant la première construction de l'image firmware.

## 1. Prérequis

### 1.1 Serveur

| Élément | Minimum | Remarque |
|---|---|---|
| OS | Linux 64 bits (Debian 12, Ubuntu 22.04+…) | une VM convient |
| CPU / RAM | 1 vCPU, 1 Go | 2 Go recommandés pendant la compilation du firmware |
| Disque | 5 Go | l'image `firmware` (toolchain ESP32) fait environ 2 Go |
| Docker | Docker Engine 24+ avec le plugin `compose` v2 | `docker compose version` |
| Réseau | joignable depuis le VLAN des écrans (port 8000) et depuis les postes d'administration (443) | |
| Internet | uniquement pour construire les images | ensuite, fonctionnement hors ligne |

Installation de Docker sur Debian/Ubuntu :
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER    # puis se reconnecter
docker compose version
```

### 1.2 Réseau des écrans

À préparer avec l'équipe réseau **avant** le déploiement :

- [ ] **SSID dédié aux écrans**, en **2,4 GHz** (l'ESP32-S3 ne capte pas le 5 GHz), en **WPA2-PSK** (pas de
      portail captif ni de WPA2-Enterprise).
- [ ] **VLAN dédié**, isolé, avec pour seul flux autorisé : écrans → serveur, TCP/8000.
- [ ] **Plage d'IP statiques** réservée aux écrans, hors plage DHCP. Exemple : `10.20.0.31` à `10.20.0.250`.
- [ ] Passerelle, masque et DNS du VLAN.
- [ ] **Couverture 2,4 GHz vérifiée devant chaque porte** (couloirs) : viser un RSSI supérieur à −75 dBm.
- [ ] Désactiver si possible le *client isolation* entre écrans et serveur, et le *band steering* forcé.

### 1.3 Postes d'administration

- **Chrome, Edge ou Opera** sur ordinateur. Le flash depuis le navigateur utilise Web Serial, que Firefox
  et Safari ne gèrent pas.
- Un câble **USB-C data** (pas un câble de charge seule).
- Sous Windows, un pilote CH34x/CP210x peut être nécessaire si l'écran n'apparaît pas comme port COM.

## 2. Récupération et configuration

```bash
sudo mkdir -p /opt/hibou && sudo chown $USER /opt/hibou
git clone https://github.com/0xK0105/Hibou.git /opt/hibou      # ou décompresser l'archive
cd /opt/hibou
cp .env.example .env
nano .env
```

### Variables du fichier `.env`

| Variable | Exemple | Description |
|---|---|---|
| `TZ` | `Europe/Paris` | fuseau horaire du serveur et des emplois du temps |
| `EPAPER_PORT` | `8000` | port HTTP exposé, utilisé par les écrans |
| `EPAPER_BIND` | `0.0.0.0` | interface d'écoute ; mettre l'IP du serveur sur le VLAN écrans pour restreindre |
| `EPAPER_DEFAULT_SITE_NAME` | `Lycée Jean Moulin` | pied de page des écrans (premier démarrage uniquement) |
| `EPAPER_DEFAULT_DAY_START` / `_DAY_END` | `07:30` / `19:00` | horaires de la journée (premier démarrage) |
| `EPAPER_DEFAULT_PROV_IP_FIRST` / `_LAST` | `10.20.0.31` / `10.20.0.250` | plage d'IP proposée lors de la mise en service |
| `EPAPER_HOSTNAME` | `ecrans.lycee.lan` | nom DNS ou IP pour l'accès HTTPS à l'administration |
| `HTTPS_PORT` / `HTTP_PORT` | `443` / `80` | ports du reverse proxy Caddy |
| `FW_VERSION` | `0.1.0` | version du firmware à compiler |
| `WIFI_SSID` / `WIFI_PASSWORD` | | Wi-Fi des écrans, compilé dans le firmware |
| `SERVER_URL` | `http://10.20.0.10:8000` | **URL du serveur telle que les écrans la voient** (IP sur le VLAN écrans) |
| `NET_GW` / `NET_MASK` / `NET_DNS` | `10.20.0.1` / `255.255.255.0` / `10.20.0.1` | paramètres IP communs à tous les écrans |
| `ACTIVATE` | `0` | `1` = activer immédiatement chaque firmware compilé (OTA sur toute la flotte) |

> Les variables `EPAPER_DEFAULT_*` ne servent qu'à **initialiser** les réglages. Ensuite, on les modifie
> dans l'interface (onglet **Réglages**).

> `.env` contient le mot de passe Wi-Fi : `chmod 600 .env`, et ne jamais le committer (il est dans `.gitignore`).

## 3. Démarrage du serveur

```bash
docker compose up -d --build
docker compose ps        # STATUS doit afficher « healthy » au bout de quelques secondes
curl http://localhost:8000/healthz
```
L'interface est disponible sur `http://<IP-serveur>:8000`.

### 3.1 Activer HTTPS (recommandé, et nécessaire pour le flash depuis le navigateur)

```bash
docker compose --profile https up -d
```
Caddy obtient un certificat auprès de sa propre autorité locale (`tls internal`). Pour que les navigateurs
lui fassent confiance, installer le certificat racine sur les postes d'administration :

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```
- Windows : double-clic sur le fichier, « Installer le certificat », magasin « Autorités de certification
  racines de confiance ». Le déployer par GPO pour un parc.
- Linux : copier dans `/usr/local/share/ca-certificates/` puis `sudo update-ca-certificates`.
- macOS : Trousseau d'accès, importer, puis « Toujours approuver ».

Si l'établissement dispose d'une PKI ou d'un certificat, remplacer `tls internal` dans `deploy/Caddyfile` par
`tls /certs/fullchain.pem /certs/privkey.pem`, et monter le dossier des certificats dans le service `caddy`.

L'administration est alors accessible sur `https://<EPAPER_HOSTNAME>`. Les écrans continuent d'utiliser
`http://<IP>:8000`.

> Pour un test rapide sans HTTPS : le navigateur considère aussi `http://localhost` comme sécurisé. Un tunnel
> `ssh -L 8000:localhost:8000 serveur` puis `http://localhost:8000/flash` suffit.

## 4. Compilation et publication du premier firmware

```bash
docker compose run --rm firmware            # ou : make fw
```
- La première exécution construit l'image `firmware` : 5 à 10 min, téléchargement de la toolchain ESP32.
- La compilation elle-même prend environ 1 min.
- Les artefacts sont écrits dans `./builds/<version>/` : `firmware.bin`, `factory.bin`, `SHA256SUMS`,
  `build-info.json`.
- Le firmware est automatiquement **publié** sur le serveur, sans être activé. Il apparaît dans l'onglet
  **Firmware** et sur la page **Mise en service**.

Détails, versions et OTA : [03 — Firmware et flash](03-firmware-et-flash.md).

## 5. Données initiales

1. Ouvrir l'interface, onglet **Planning**.
2. Importer l'emploi du temps (ICS ou CSV). Les salles sont créées automatiquement.
3. Compléter le nom affiché de chaque salle si besoin.
4. Onglet **Réglages** : vérifier les horaires, les jours ouvrés, le nom du site et la plage d'IP.

Pour tester sans vrai emploi du temps :
```bash
python3 tools/make_sample_data.py          # génère tools/sample_data/edt_exemple.{ics,csv}
```

## 6. Premier écran

Suivre [04 — Mise en service des écrans](04-mise-en-service.md). En résumé :
1. `https://<serveur>/flash` → **Flasher**.
2. Saisir l'IP proposée, la salle et le nom → **Connecter l'écran et appliquer**.
3. L'écran redémarre et affiche sa salle. Il apparaît « en ligne » dans l'onglet **Écrans**.

Pour tester la chaîne sans matériel :
```bash
docker compose run --rm firmware simulate --count 3
```

## 7. Démarrage automatique

Avec `restart: unless-stopped`, les conteneurs redémarrent avec Docker. Vérifier que le service Docker est
activé au démarrage :
```bash
sudo systemctl enable docker
```

## 8. Mise à jour de l'application

```bash
cd /opt/hibou
make backup                       # toujours sauvegarder avant
git pull                          # ou remplacer les fichiers par la nouvelle archive
docker compose --profile https up -d --build
docker compose ps                 # vérifier « healthy »
```
Le schéma de la base est migré automatiquement au démarrage. Si la mise à jour concerne le firmware, voir
[03 — Firmware et flash, § OTA](03-firmware-et-flash.md#5-mettre-à-jour-la-flotte-ota).

## 9. Désinstallation

```bash
docker compose --profile https --profile tools down          # arrête et supprime les conteneurs
docker volume rm hibou_epaper-data                 # ⚠ supprime la base et les firmwares
docker volume rm hibou_caddy-data hibou_caddy-config
docker image rm hibou/server hibou/firmware
```

## 10. Vérification finale (recette d'installation)

- [ ] `docker compose ps` : `server` en *healthy*, `caddy` en *running* si HTTPS.
- [ ] `https://<EPAPER_HOSTNAME>` s'ouvre sans alerte de certificat sur un poste d'administration.
- [ ] Depuis le VLAN écrans : `curl http://<IP-serveur>:8000/healthz` renvoie `{"status":"ok"}`.
- [ ] Un firmware apparaît dans l'onglet **Firmware**, avec « Flash web : oui ».
- [ ] L'emploi du temps est importé et l'aperçu d'une salle est correct (Planning → clic sur une salle).
- [ ] Un écran de test a été mis en service et apparaît « en ligne ».
- [ ] La sauvegarde est planifiée ([06 — Exploitation](06-exploitation.md#2-sauvegardes)).
