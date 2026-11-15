# 03 — Firmware, flash et mises à jour

## 1. Principe

**Le même binaire sert à toute la flotte.** Les paramètres communs (Wi-Fi, URL du serveur, passerelle,
masque, DNS) sont compilés dedans à partir du fichier `.env`. Ce qui est propre à chaque écran, l'IP
statique principalement, est écrit dans sa mémoire non volatile (NVS) lors de la mise en service et survit
aux mises à jour.

| Fichier produit | Usage |
|---|---|
| `firmware.bin` | image applicative seule, pour les **mises à jour OTA** |
| `factory.bin` | image complète (bootloader + table de partitions + `boot_app0` + application) à l'offset `0x0`, pour le **premier flash** d'un écran neuf |

Partitions : `default_8MB.csv`, avec deux emplacements applicatifs pour l'OTA (`app0`/`app1`). Si une
mise à jour échoue en cours de téléchargement, l'écran reste sur la version précédente.

## 2. Compiler

```bash
docker compose run --rm firmware                       # utilise FW_VERSION du .env
docker compose run --rm -e FW_VERSION=0.3.0 firmware   # version passée explicitement
make fw FW_VERSION=0.3.0                               # équivalent
```

Étapes réalisées par le conteneur (`firmware/toolbox.sh build`) :
1. Vérification que la version n'existe pas déjà sur le serveur (sinon : erreur, ou `FORCE=1`).
2. Copie des sources dans le conteneur et génération de `include/config_local.h` depuis `.env`.
3. `pio run`.
4. Fusion de `factory.bin` avec esptool `merge_bin`.
5. Écriture dans `./builds/<version>/` avec les sommes SHA-256 et `build-info.json`.
6. Publication sur le serveur. Activation seulement si `ACTIVATE=1`.

Options (variables d'environnement) :

| Variable | Défaut | Effet |
|---|---|---|
| `FW_VERSION` | `.env` | version annoncée par l'écran (`X-FW-Version`) |
| `PUBLISH` | `1` | `0` = compiler sans publier |
| `ACTIVATE` | `0` | `1` = activer la version : OTA de toute la flotte |
| `FORCE` | `0` | `1` = republier une version existante (déconseillé : les écrans déjà à ce numéro ne se mettront pas à jour) |

### Règles de versionnage

- Incrémenter `FW_VERSION` à **chaque** build déployé. Schéma conseillé `MAJEUR.MINEUR.CORRECTIF`.
- Toute modification de `.env` côté Wi-Fi ou serveur demande un **nouveau build** pour être prise en compte
  par les écrans, et une nouvelle version.
- Garder dans `CHANGELOG.md` une ligne par version déployée.

### Compiler hors Docker (développement)

```bash
cd firmware
cp include/config_local.h.example include/config_local.h    # éditer
pip install platformio
pio run                    # compile
pio run -t upload          # flashe par USB
pio device monitor         # journaux série, 115 200 bauds
```

## 3. Premier flash d'un écran neuf

### 3.1 Depuis le navigateur (recommandé)

Prérequis : Chrome ou Edge, et la page ouverte en HTTPS (profil `https`) ou depuis `localhost`.

1. Brancher l'écran en USB-C et mettre l'interrupteur sur **ON**.
2. Ouvrir `https://<serveur>/flash`.
3. Section **1. Flasher le firmware** : choisir la version (l'active par défaut) puis cliquer sur **Flasher**.
   Choisir le port série de l'écran (`USB Single Serial`, `CH340`, `CP210x`… selon le modèle).
4. Accepter l'effacement (*erase*), recommandé pour un premier flash. Durée : 30 à 60 s.
5. Fermer la fenêtre de fin. L'outil propose ensuite une configuration Wi-Fi « Improv » : l'ignorer,
   l'écran se configure à l'étape suivante.

La page utilise **ESP Web Tools**, embarqué dans le serveur : aucun accès Internet n'est nécessaire.

### 3.2 En ligne de commande (Linux, USB transmis au conteneur)

```bash
docker compose run --rm --device /dev/ttyUSB0 firmware flash /dev/ttyUSB0          # dernière version compilée
docker compose run --rm --device /dev/ttyUSB0 firmware flash /dev/ttyUSB0 0.2.0    # version précise
```
Sous Windows ou macOS, Docker Desktop ne transmet pas les ports USB : utiliser le navigateur, ou
`esptool.py write_flash 0x0 builds/<version>/factory.bin` installé localement.

### Si l'écran n'est pas détecté
- Changer de câble : beaucoup de câbles USB-C ne transportent que la charge.
- Mode téléchargement forcé : maintenir le bouton **BOOT** en branchant l'écran, puis relâcher.
- Windows : installer le pilote CH34x ou CP210x.
- Linux : l'utilisateur doit appartenir au groupe `dialout` (flash local).

## 4. Configuration d'un écran (provisioning)

Au démarrage à froid (mise sous tension ou reset, **pas** au réveil de deep sleep), le firmware écoute le
port série pendant 3 s et affiche `PROVISION READY mac=… fw=…`. Si une commande arrive, la fenêtre est
prolongée à 60 s.

| Commande | Réponse | Effet |
|---|---|---|
| `INFO` | `INFO mac=… fw=…` | identification |
| `GET` | `CFG ssid=… server=… ip=… gw=… mask=… dns=… pass=***` | configuration courante (mot de passe masqué) |
| `SET cle=valeur` | `OK cle` / `ERR …` | clés : `ssid pass server ip gw mask dns` ; une valeur vide rétablit la valeur compilée (pour `ip` : DHCP) |
| `CLEAR` | `OK CLEAR` | efface toute la configuration NVS |
| `DONE` | `OK DONE` | quitte la configuration et démarre normalement |

Trois façons de l'utiliser :
- **Navigateur** : `https://<serveur>/flash`, section 2. Elle redémarre l'écran, envoie les commandes et
  enregistre l'écran (nom, salle, IP) sur le serveur.
- **Conteneur** (Linux) : `docker compose run --rm --device /dev/ttyUSB0 firmware provision --port /dev/ttyUSB0 --ip 10.20.0.31 --name "Porte A101" --room A101`
- **Python local** : `python3 tools/provision.py --port COM5 --ip 10.20.0.31 --room A101`. Nécessite
  `pip install pyserial`. Ajouter `--server` si le serveur n'est pas celui compilé.

## 5. Mettre à jour la flotte (OTA)

1. Compiler une nouvelle version : `make fw FW_VERSION=0.3.0`.
2. **Tester sur un écran pilote** : le flasher par USB, ou l'affecter à une salle de test et vérifier
   l'affichage et la consommation pendant 24 h.
3. Activer la version : onglet **Firmware** → **Activer**, ou `make fw-activate` dès la compilation.
4. Chaque écran dont la version diffère télécharge la mise à jour **à son réveil suivant**, après avoir
   affiché son image. Il redémarre, puis se reconnecte avec la nouvelle version, ce qui force un
   rafraîchissement.
5. Suivre la progression dans l'onglet **Firmware** (colonne « Écrans » : nombre d'écrans à cette
   version) ou dans l'onglet **Écrans**.

Garde-fous :
- L'OTA est **reportée** si la batterie est sous 3,6 V.
- Un écran qui dort jusqu'au lendemain ne se mettra à jour que le lendemain. Pour accélérer, appuyer sur
  son bouton blanc de droite.
- **Retour arrière** : activer la version précédente. Les écrans « redescendent » à leur réveil suivant,
  puisque l'OTA se déclenche dès que la version diffère.
- **Désactiver** (bouton **Désactiver**) suspend toute OTA.

## 6. Journaux série

```bash
pio device monitor -b 115200                               # hors Docker
docker compose run --rm --device /dev/ttyUSB0 firmware shell -c "python3 -m serial.tools.miniterm /dev/ttyUSB0 115200"
```
Exemple de cycle normal :
```
reveil: timer, boot #42, fw 0.2.0
batterie: 3912 mV
wifi: ok en 412 ms, ip=10.20.0.31 rssi=-63 ch=6
http: 304, sommeil demande 1795 s
image inchangee
sommeil 1795 s
```

## 7. Brochage utilisé (reTerminal E1001)

| Fonction | GPIO |
|---|---|
| E-paper SCK / MOSI / CS / DC / RST / BUSY | 7 / 9 / 10 / 11 / 12 / 13 |
| Batterie : ADC / activation de la mesure | 1 / 21 (pont diviseur ÷2) |
| LED (active à l'état bas) | 6 |
| Bouton blanc droit (réveil) | 4 |
| UART du port USB-C (journaux, provisioning) | RX 44 / TX 43 |

Pilote d'affichage : `GxEPD2_750_GDEY075T7` (contrôleur UC8179), selon la documentation Seeed.
