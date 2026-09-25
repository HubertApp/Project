SHELL := /bin/bash

NETWORK := hubert-network
NETWORK_ASTAR := astar-net
MS_DIR := microservices
FRONT_DIR := front

ADMIN := $(MS_DIR)/MS-Admin
AOM := $(MS_DIR)/MS-aom-agregator
AUTH := $(MS_DIR)/MS-Auth
USER := $(MS_DIR)/MS-User
ADMIN_USER := $(MS_DIR)/MS-Admin_User
NOTIFICATIONS := $(MS_DIR)/MS-notifications
CREATOR := $(MS_DIR)/MS-itinerary-creator
GRAPH_MANAGER := $(MS_DIR)/MS-graph-manager

FRONT := $(FRONT_DIR)/Front-user-app
FRONT_ADMIN := ${FRONT_DIR}/Front-admin

COMPOSE = docker compose --project-directory $(1) -f $(1)/$(2)

.PHONY: help network infra-up infra-down up down build ps logs supergraph restart-gateway clean-network seed urls e2e e2e-list

help:
	@echo "up               lance l infra racine (rabbitmq, gateway, observabilite) et tous les microservices"
	@echo "down             arrete tout"
	@echo "down-all         arrete tout et supprime le reseau docker partage"
	@echo "build            rebuild les images de tous les services"
	@echo "seed             declenche l ingestion GTFS dans MS-aom-agregator (sinon la carte est vide)"
	@echo "e2e              parcours end-to-end etape par etape (FROM=US1 pour reprendre, AUTO=1 sans pause)"
	@echo "e2e-list         liste les etapes du parcours end-to-end"
	@echo "supergraph       recompose le supergraph depuis super-graph.yml et redemarre la gateway"
	@echo "restart-gateway  redemarre seulement la gateway (recharge supergraph.graphql et router.yaml)"
	@echo "urls             rappelle les points d entree utiles"
	@echo "ps               liste les conteneurs sur hubert-network"
	@echo "logs SERVICE=x   suit les logs d un service"
	@echo "network          cree le reseau docker partage hubert-network"
	@echo "clean-network    supprime le reseau partage"
	@echo ""
	@echo "Demarrage a froid : make up && make seed"

urls:
	@echo "front        http://localhost:5173"
	@echo "front-admin  http://localhost:8004"
	@echo "gateway      http://localhost:4000/      (Apollo Router : GraphQL a la RACINE, pas /graphql)"
	@echo "aom-agregator http://localhost:8002/graphql"
	@echo "admin        http://localhost:8001/graphql"
	@echo "rabbitmq     http://localhost:15672      (guest/guest)"
	@echo "grafana      http://localhost:3000"
	@echo "jaeger       http://localhost:16686"

network:
	@docker network inspect $(NETWORK) >/dev/null 2>&1 || docker network create $(NETWORK)
	@docker network inspect $(NETWORK_ASTAR) >/dev/null 2>&1 || docker network create $(NETWORK_ASTAR)

infra-up: network
	docker compose -f docker-compose.yml up -d --build

infra-down:
	docker compose -f docker-compose.yml down

up: network infra-up
	$(call COMPOSE,$(ADMIN),docker-compose.yaml) up -d --build
	$(call COMPOSE,$(AOM),docker-compose.yaml) up -d --build
	$(call COMPOSE,$(AUTH),docker-compose.yml) up -d --build
	$(call COMPOSE,$(USER),docker-compose.yml) up -d --build
	$(call COMPOSE,$(NOTIFICATIONS),docker-compose.yml) up -d --build
	$(call COMPOSE,$(CREATOR),docker-compose.yml) up -d --build
	$(call COMPOSE,$(GRAPH_MANAGER),docker-compose.yaml) up -d --build
	$(call COMPOSE,$(ADMIN_USER),docker-compose.yml) up -d --build
	$(call COMPOSE,$(FRONT),docker-compose.yaml) up -d --build
	$(call COMPOSE,$(FRONT_ADMIN),docker-compose.yaml) up -d --build
	@echo ""
	@echo "Tout est lance. Ensuite :"
	@echo "  make seed        pour remplir la base GTFS (sinon /trafic n affiche aucun arret)"
	@echo "  make supergraph  si un schema de subgraph a change"
	@echo "  make urls        pour la liste des points d entree"

# L ingestion est declenchee par un message RabbitMQ : le worker telecharge le
# GTFS puis remplit MongoDB. Compter ~1 min, suivre avec 'make logs SERVICE=ms-aom-agregator-worker'.
seed:
	$(call COMPOSE,$(AOM),docker-compose.yaml) exec -T aom-agregator-api python -m app.test_gtfs_publisher
	@echo "Message publie. L ingestion tourne en tache de fond cote worker."

down:
	$(call COMPOSE,$(ADMIN),docker-compose.yaml) down --remove-orphans
	$(call COMPOSE,$(AOM),docker-compose.yaml) down --remove-orphans
	$(call COMPOSE,$(AUTH),docker-compose.yml) down
	$(call COMPOSE,$(USER),docker-compose.yml) down --remove-orphans
	$(call COMPOSE,$(NOTIFICATIONS),docker-compose.yml) down
	$(call COMPOSE,$(CREATOR),docker-compose.yml) down 
	$(call COMPOSE,$(GRAPH_MANAGER),docker-compose.yaml) down
	$(call COMPOSE,$(ADMIN_USER),docker-compose.yml) down
	$(call COMPOSE,$(FRONT),docker-compose.yaml) down
	$(call COMPOSE,$(FRONT_ADMIN),docker-compose.yaml) down
	docker compose -f docker-compose.yml down

down-all: down clean-network

build:
	docker compose -f docker-compose.yml build
	$(call COMPOSE,$(ADMIN),docker-compose.yaml) build
	$(call COMPOSE,$(AOM),docker-compose.yaml) build
	$(call COMPOSE,$(AUTH),docker-compose.yml) build
	$(call COMPOSE,$(USER),docker-compose.yml) build
	$(call COMPOSE,$(NOTIFICATIONS),docker-compose.yml) build
	$(call COMPOSE,$(CREATOR),docker-compose.yml) build
	$(call COMPOSE,$(GRAPH_MANAGER),docker-compose.yaml) build
	$(call COMPOSE,$(ADMIN_USER),docker-compose.yml) build
	$(call COMPOSE,$(FRONT),docker-compose.yaml) build
	$(call COMPOSE,$(FRONT_ADMIN),docker-compose.yaml) build

ps:
	@docker ps --filter network=$(NETWORK) --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

logs:
	docker logs -f $(SERVICE)

supergraph:
	rover supergraph compose --config ./super-graph.yml --output ./gateway/supergraph.graphql
	docker compose -f docker-compose.yml restart gateway

restart-gateway:
	docker compose -f docker-compose.yml restart gateway

clean-network:
	docker network rm $(NETWORK)
	docker network rm $(NETWORK_ASTAR)

# Parcours end-to-end contre la stack lancee (make up). Voir e2e/README.md.
#   make e2e            interactif, pause apres chaque etape
#   make e2e FROM=US1   reprend a l etape US1 avec l etat du run precedent
#   make e2e AUTO=1     sans pause, s arrete au premier echec
e2e:
	uv run --project e2e python e2e/run.py $(if $(FROM),--from $(FROM)) $(if $(AUTO),--auto)

e2e-list:
	uv run --project e2e python e2e/run.py --list
