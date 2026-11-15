# Raccourcis d'exploitation (facultatifs : chaque cible n'est qu'une commande docker compose).
# Usage : make help
COMPOSE ?= docker compose
PROFILE_HTTPS := $(if $(filter 1,$(HTTPS)),--profile https,)

.PHONY: help up down restart logs ps build fw fw-activate backup import update test

help:                    ## Affiche cette aide
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'
	@echo "  (HTTPS=1 pour inclure le reverse proxy Caddy, ex : make up HTTPS=1)"

up:                      ## Démarre le serveur (et Caddy si HTTPS=1)
	$(COMPOSE) $(PROFILE_HTTPS) up -d

down:                    ## Arrête la stack (les données sont conservées)
	$(COMPOSE) --profile https down

restart:                 ## Redémarre le serveur
	$(COMPOSE) restart server

logs:                    ## Suit les journaux du serveur
	$(COMPOSE) logs -f --tail=200 server

ps:                      ## État des conteneurs
	$(COMPOSE) --profile https ps

build:                   ## Reconstruit les images
	$(COMPOSE) --profile https --profile tools build

fw:                      ## Compile et publie le firmware (FW_VERSION=x.y.z)
	$(COMPOSE) run --rm $(if $(FW_VERSION),-e FW_VERSION=$(FW_VERSION),) firmware build

fw-activate:             ## Compile, publie et ACTIVE le firmware (OTA sur toute la flotte)
	$(COMPOSE) run --rm $(if $(FW_VERSION),-e FW_VERSION=$(FW_VERSION),) -e ACTIVATE=1 firmware build

backup:                  ## Sauvegarde la base (conserve les 14 dernières) et la copie dans ./backups
	$(COMPOSE) exec server python -m app.cli backup --keep 14
	mkdir -p backups && $(COMPOSE) cp server:/data/backups/. ./backups/

import:                  ## Importe un EDT déposé dans ./imports (FILE=edt.ics)
	$(COMPOSE) exec server python -m app.cli import /data/imports/$(FILE)

update:                  ## Met à jour après un git pull : reconstruit et redémarre
	$(COMPOSE) $(PROFILE_HTTPS) up -d --build

test:                    ## Lance les tests du serveur dans un conteneur
	$(COMPOSE) run --rm --no-deps --user root -v ./server/tests:/srv/tests:ro --entrypoint sh server -c "pip install -q pytest httpx 2>/dev/null && python -m pytest -q -p no:cacheprovider tests"
