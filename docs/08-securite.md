# 08 — Sécurité

> **État actuel : prototype fonctionnel, non durci.** Ne pas exposer en dehors d'un réseau interne
> cloisonné avant d'avoir traité au moins les points P1 de la feuille de route.

## 1. Surface d'attaque actuelle

| Élément | État | Risque |
|---|---|---|
| Interface et API d'administration | **sans authentification**, joignables sur :8000 (HTTP) et :443 (HTTPS via Caddy) | toute personne qui accède au port peut modifier les plannings, réaffecter ou oublier des écrans, **pousser un firmware** |
| Protocole des écrans | HTTP en clair, identification par simple adresse MAC | usurpation d'un écran (fausse télémétrie), interception ou modification de l'image affichée |
| OTA | firmware non signé, téléchargé en HTTP ; seule la taille et l'en-tête sont contrôlés | un attaquant capable d'activer une version ou d'intercepter le flux prend le contrôle de toute la flotte |
| `factory.bin` / `firmware.bin` | téléchargeables sans authentification, **contiennent le PSK Wi-Fi** en clair | fuite de la clé du SSID des écrans |
| Écrans physiques | flash non chiffrée, port USB accessible | un écran volé livre le PSK Wi-Fi et l'URL du serveur |
| Provisioning série | ouvert 3 s à chaque démarrage à froid, sans authentification | reconfiguration (SSID, serveur) par quiconque a un accès physique |
| `.env` | contient le PSK Wi-Fi | à protéger (`chmod 600`, hors dépôt git) |

## 2. Mesures déjà en place

- Conteneur serveur exécuté **sans privilèges** (utilisateur `epaper`, UID 10001).
- HTTPS disponible pour l'administration (profil `https`, Caddy).
- Pas de secret dans le dépôt : `.env` et `config_local.h` sont dans `.gitignore`.
- Les entrées sont validées : taille et signature des firmwares, formats d'IP et de version, clés de réglages
  autorisées, échappement HTML dans l'interface.
- Les requêtes SQL sont paramétrées (les noms de colonnes dynamiques viennent d'une liste blanche).
- L'écran ne fait que des requêtes sortantes et n'expose aucun service réseau.

## 3. Mesures réseau immédiates (sans modification de code)

Elles réduisent fortement le risque en attendant les évolutions applicatives :

1. **VLAN écrans isolé** : seul flux autorisé, écrans → `IP_serveur:8000/TCP`. Pas de flux entre écrans,
   aucun accès Internet.
2. **Filtrage sur le serveur** : n'accepter le port 8000 **que depuis le VLAN écrans**, et le port 443 que
   depuis le VLAN d'administration. Exemple avec nftables :
   ```
   tcp dport 8000 ip saddr 10.20.0.0/24 accept
   tcp dport 443  ip saddr 10.10.0.0/24 accept
   tcp dport { 8000, 443 } drop
   ```
   Avec Docker, ces règles se placent dans la chaîne `DOCKER-USER`, car Docker contourne les règles INPUT
   classiques.
3. `EPAPER_BIND=<IP du serveur sur le VLAN écrans>` dans `.env` pour ne publier le port 8000 que sur cette interface.
4. **PSK Wi-Fi dédié** au SSID des écrans, différent de tout autre réseau, et changé si un écran est perdu
   (nouveau build avec le nouveau PSK, OTA, puis bascule).
5. Fixation **antivol** des écrans.

## 4. Feuille de route de durcissement

| Priorité | Mesure | Détail |
|---|---|---|
| **P1** | Authentification de l'administration | login applicatif (sessions) ou délégation à un reverse proxy avec SSO / LDAP (ex. Caddy + `forward_auth` vers Authelia ou Keycloak). Séparer les rôles : planning, exploitation, administration |
| **P1** | Séparer les surfaces écran / admin | n'exposer que `/api/v1/display` et `/api/v1/firmware/*` sur le port des écrans ; l'API d'admin seulement derrière le proxy authentifié |
| **P1** | Token par écran | secret aléatoire généré à la mise en service, stocké en NVS et côté serveur (haché), envoyé en en-tête, révocable depuis l'interface ; refus des MAC inconnues ou révoquées |
| **P1** | Protéger les images firmware | téléchargement réservé aux écrans authentifiés (OTA) et aux administrateurs (factory) |
| **P2** | HTTPS écrans ↔ serveur | certificat de l'AC interne compilé dans le firmware (`WiFiClientSecure` + CA épinglée) ; coût énergétique de la poignée TLS à mesurer |
| **P2** | OTA signée | Secure Boot v2 (signature RSA-PSS du bootloader et de l'app) ; à défaut, vérification par le firmware d'une signature applicative avant de valider la partition |
| **P2** | Chiffrement de la flash | Flash Encryption (mode *release*) : empêche l'extraction du PSK et des tokens d'un écran volé. ⚠ irréversible : à valider sur un écran pilote |
| **P2** | Provisioning série protégé | n'accepter `SET` que si la NVS est vide, ou avec un code présent sur l'étiquette de l'écran |
| **P3** | Journal d'audit | qui a importé, modifié, activé quel firmware, et quand |
| **P3** | Sécurité des conteneurs | `read_only: true` + `tmpfs`, `cap_drop: [ALL]`, `no-new-privileges`, images épinglées par digest, scan (Trivy) en CI |
| **P3** | Sauvegardes chiffrées | chiffrement des sauvegardes externalisées |

## 5. Données personnelles

Le système manipule des **noms d'enseignants** et des **noms de groupes** (données issues de l'EDT),
affichés publiquement dans les couloirs, et des adresses MAC d'équipements (pas de données personnelles).
- Vérifier avec le DPO que l'affichage nominatif des enseignants est acceptable ; sinon, ne pas importer
  la colonne enseignant (CSV) ou retirer l'organisateur de l'export ICS.
- Durée de conservation : les cours passés peuvent être purgés à chaque début d'année (import en mode
  « Tout remplacer »).
- Aucune donnée n'est transmise hors du serveur.
