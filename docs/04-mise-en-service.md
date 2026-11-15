# 04 — Mise en service des écrans (procédure terrain)

Cette procédure s'adresse au technicien qui prépare puis pose les écrans. Elle se fait en deux temps : la
préparation à l'atelier (flash, configuration, test), puis la pose sur site.

## 1. Avant de commencer

- [ ] Le serveur est installé et accessible en HTTPS ([02 — Installation](02-installation.md)).
- [ ] Un firmware est publié (onglet **Firmware**, colonne « Flash web : oui ») et **activé**.
- [ ] L'emploi du temps est importé et les salles existent (onglet **Planning**).
- [ ] La plage d'IP des écrans est renseignée (onglet **Réglages**).
- [ ] Le **plan d'adressage** est prêt (modèle ci-dessous).
- [ ] Les écrans sont chargés : au moins 2 h en USB-C pour une première charge.

### Modèle de plan d'adressage

À tenir à jour, par exemple dans un tableur partagé. L'onglet **Écrans** sert de référence en exploitation.

| Salle | Nom de l'écran | IP | MAC | Bâtiment / étage | Fixation | Date de pose |
|---|---|---|---|---|---|---|
| A101 | Porte A101 | 10.20.0.31 | D8:3B:DA:…:01 | A / RDC | vis + antivol | |
| A102 | Porte A102 | 10.20.0.32 | | A / RDC | | |

## 2. Préparation à l'atelier (par écran, environ 3 min)

1. **Brancher** l'écran en USB-C sur le poste d'administration, interrupteur sur **ON**.
2. Ouvrir `https://<serveur>/flash` dans Chrome ou Edge.
3. **Flasher** (section 1) : choisir le port, accepter l'effacement, attendre la fin (30 à 60 s).
4. **Configurer** (section 2) :
   - **Adresse IP** : celle proposée est la prochaine libre de la plage, à corriger selon le plan d'adressage ;
   - **Salle** : la salle de destination ;
   - **Nom** : `Porte <salle>`, ou un nom qui décrit l'emplacement ;
   - cliquer sur **Connecter l'écran et appliquer** et choisir le même port.
5. L'écran redémarre et, en moins de 10 s :
   - ✅ affiche le planning de la salle : c'est terminé ;
   - ⚠️ affiche « **Connexion impossible** » avec SSID, IP et serveur : voir § 5 ;
   - ⚠️ affiche « **Écran non affecté** » : il joint le serveur mais n'a pas de salle ; l'affecter dans
     l'onglet **Écrans**.
6. Noter la **MAC** (affichée par la page de configuration) dans le plan d'adressage, et coller une
   étiquette « salle / IP » au dos de l'écran.
7. Débrancher. L'écran fonctionne sur batterie.

> Pour préparer une série, enchaîner flash et configuration écran par écran. L'IP proposée s'incrémente
> automatiquement.

## 3. Pose sur site

1. **Vérifier le signal à l'emplacement exact** avant de fixer. Appuyer sur le **bouton blanc de droite**
   pour forcer un réveil, puis regarder le RSSI dans l'onglet **Écrans** (depuis un téléphone ou un portable) :

   | RSSI | Verdict |
   |---|---|
   | > −65 dBm | ✅ très bon |
   | −65 à −75 dBm | ✅ correct |
   | −75 à −80 dBm | ⚠️ limite : connexions plus longues, autonomie réduite |
   | < −80 dBm | ❌ déplacer l'écran ou faire ajouter une borne |

2. **Hauteur conseillée** : centre de l'écran à environ 1,50 m, à côté de la porte côté poignée, à l'abri
   du soleil direct (l'e-paper est lisible au soleil, mais la chaleur au-delà de 40 °C est hors spécification).
3. **Fixation** : platine murale vissée, avec vis de sécurité ou antivol si le couloir est accessible au
   public. Laisser l'accès au port USB-C et à l'interrupteur pour la recharge.
4. Appuyer une dernière fois sur le bouton blanc de droite : l'écran doit afficher la bonne salle et la bonne date.

## 4. Fiche de recette (par écran)

| Contrôle | OK |
|---|---|
| L'écran affiche le bon code de salle et la date du jour | ☐ |
| Le statut (OCCUPÉE / LIBRE) correspond au planning | ☐ |
| Onglet **Écrans** : statut « en ligne », bonne salle, bonne IP | ☐ |
| RSSI à l'emplacement supérieur à −75 dBm | ☐ |
| Batterie supérieure à 80 % à la pose | ☐ |
| Version firmware égale à la version active | ☐ |
| Étiquette salle / IP au dos | ☐ |
| Plan d'adressage à jour (MAC, IP, date de pose) | ☐ |

Le lendemain, vérifier dans l'onglet **Écrans** que l'écran s'est réveillé à l'heure prévue : « Dernier
contact » récent, aucun « en retard » sur le prochain réveil.

## 5. Problèmes courants à la mise en service

| Symptôme | Cause probable | Action |
|---|---|---|
| Le port de l'écran n'apparaît pas dans le navigateur | câble de charge seule, pilote absent, page en HTTP | autre câble ; pilote CH34x/CP210x ; ouvrir la page en HTTPS |
| « Pas de réponse » lors de la configuration | la carte n'a pas redémarré automatiquement | appuyer sur reset quand la page le demande (30 s) |
| Écran « Connexion impossible — Wi-Fi injoignable » | SSID ou mot de passe erroné, 5 GHz uniquement, hors couverture | vérifier SSID et mot de passe (`.env`, puis recompiler) ; tester près d'une borne |
| Écran « Connexion impossible — Erreur serveur » | `SERVER_URL` erroné, filtrage, serveur arrêté | depuis le VLAN : `curl http://<IP>:8000/healthz` ; vérifier le pare-feu |
| L'écran se connecte mais l'IP affichée n'est pas la bonne | conflit d'IP, ou IP hors du sous-réseau | corriger l'IP (page de configuration) ; vérifier masque et passerelle |
| « Écran non affecté » | pas de salle choisie à la configuration | onglet **Écrans** → choisir la salle → bouton blanc |
| Image figée ou fantôme après un choc thermique | rémanence e-paper | appuyer sur le bouton blanc (rafraîchissement complet) |

## 6. Remplacer un écran

1. Mettre en service l'écran de remplacement avec **la même IP et la même salle**.
2. Onglet **Écrans** → ancien écran → **Oublier cet écran**.
3. Mettre à jour le plan d'adressage (nouvelle MAC).
