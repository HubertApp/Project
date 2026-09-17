# Hubert — Project

Repo chapeau de l'application **Hubert** : une app de mobilité qui agrège les données de
transport en commun (GTFS des AOM), calcule des itinéraires multimodaux et affiche l'info
trafic.

Ce repo ne contient **pas** de code métier. Il regroupe les microservices et les fronts en
submodules Git, et porte la config commune : gateway GraphQL (Apollo Router), RabbitMQ, stack
d'observabilité, et un Makefile pour tout lancer d'un coup.

```
Front user (5173) ──► Apollo Router (4000) ──┬─► MS-Auth · MS-User · MS-Admin_user
                                             ├─► MS-Admin · MS-notifications
                                             ├─► MS-graph-manager   (itinéraires, trafic)
                                             └─► MS-aom-agregator ──RabbitMQ──► worker GTFS
```

Chaque microservice expose un subgraph GraphQL fédéré. Le Router les fusionne en un seul schéma
sur le port 4000. Le front ne parle qu'à la gateway.

> Branche de travail : **`develop`**. `main` est la branche stable et a du retard (voir
> [Branches](#branches)). Ce README décrit `develop`.

## Les services

| Submodule | Rôle |
|---|---|
| `MS-Auth` | login Google + admin, émission des JWT, JWKS |
| `MS-User` | profil utilisateur, préférences de notification |
| `MS-Admin_user` | comptes admin (back-office) |
| `MS-Admin` | réseaux de transport : recherche des datasets AOM, enregistrement |
| `MS-aom-agregator` | ingestion GTFS (worker RabbitMQ), arrêts, lignes, horaires |
| `MS-graph-manager` | graphe de routage : `computeRoute`, `getItineraireFromTo`, `infoTrafic` |
| `MS-notifications` | notifications utilisateur multi-canaux |
| `MS-itinerary-creator` | moteur A*, sur son propre réseau `astar-net` (derrière Envoy, pas un subgraph) |
| `Front-user-app` | app utilisateur (Vite, port 5173) |

Présents en submodule mais **hors** `make up` : `MS-itinerary-optimization`, `Front-admin`, et
`Api-Gateway` — l'ancienne gateway, remplacée par l'Apollo Router.

## Prérequis

- Docker + Compose v2, `make`
- une clé SSH sur GitHub (la plupart des submodules sont en SSH)
- [Rover](https://www.apollographql.com/docs/rover/getting-started), seulement si tu modifies un schéma GraphQL

## Installation

```bash
git clone --recurse-submodules -b develop git@github.com:HubertApp/Project.git
cd Project
```

Déjà cloné sans les submodules : `git submodule update --init --recursive`

Crée un `.env` à la racine (gitignoré) :

```env
APOLLO_KEY=service:ton-graph:xxxxxxxx
APOLLO_GRAPH_REF=ton-graph@current
```

Sans compte Apollo Studio, laisse les valeurs vides : le Router démarre quand même sur le
`supergraph.graphql` local.

Chaque microservice a **aussi son propre `.env`** (voir le README du submodule). Sans ça,
certains conteneurs redémarrent en boucle.

## Lancer

```bash
make up      # infra + microservices + front
make seed    # ingestion GTFS, sinon la carte est vide (~1 min)
make down    # tout arrêter
```

`make seed` publie un message RabbitMQ qui déclenche l'import GTFS.
Suivre : `make logs SERVICE=ms-aom-agregator-worker`

| Commande | |
|---|---|
| `make up` / `make down` | lance / arrête tout |
| `make down-all` | + supprime les réseaux Docker (`hubert-network`, `astar-net`) |
| `make build` | rebuild les images sans lancer |
| `make seed` | ingestion GTFS |
| `make supergraph` | recompose le supergraph et redémarre la gateway |
| `make restart-gateway` | redémarre la gateway seule |
| `make ps` / `make logs SERVICE=x` | conteneurs / logs |
| `make urls` | rappel des points d'entrée |
| `make infra-up` / `infra-down` | infra racine seule |

## Points d'entrée

| | URL | Subgraph |
|---|---|---|
| Front user | http://localhost:5173 | |
| **Gateway** | http://localhost:4000 | GraphQL à la **racine**, pas `/graphql` |
| MS-User | http://localhost:3001/graphql | `service-user` |
| MS-Admin_user | http://localhost:3003/graphql | `service-adminuser` |
| MS-Auth | http://localhost:3004/graphql | `service-auth` (JWKS sur `/auth/jwks`) |
| MS-notifications | http://localhost:3008/graphql | `service-notifications` |
| MS-graph-manager | http://localhost:3011/graphql | `graph-service` |
| MS-Admin | http://localhost:8001/graphql | `service-admin` |
| MS-aom-agregator | http://localhost:8002/graphql | `service-aom-agregator` |
| RabbitMQ | http://localhost:15672 | guest / guest |
| Grafana | http://localhost:3000 | login anonyme |
| Jaeger | http://localhost:16686 | |
| Prometheus | http://localhost:9090 | |
| Alloy | http://localhost:12345 | UI de collecte des logs |

## Supergraph

Le Router lit un fichier statique `gateway/supergraph.graphql` (federation `2.12.1`). Si tu
modifies le schéma d'un microservice, il faut le recomposer :

```bash
make supergraph   # tous les services doivent tourner : rover les introspecte via localhost
```

⚠️ **Un service éteint pendant `make supergraph` disparaît silencieusement du schéma fédéré.**
C'est l'état actuel sur `develop` : `service-admin` et `service-aom-agregator` sont absents du
`supergraph.graphql` commité, donc les arrêts, lignes et réseaux de transport ne remontent plus
par la gateway. Relancer `make up` puis `make supergraph` avec tout allumé pour le corriger.

Dans `super-graph.yml`, chaque subgraph a deux URLs à ne pas confondre :

```yaml
service-admin:
  routing_url:  http://service_admin:80/graphql   # gateway -> service : DNS docker + port interne
  schema:
    subgraph_url: http://localhost:8001/graphql   # rover -> service   : localhost + port publié
```

Inversées, le supergraph compose sans erreur mais aucune requête ne résout
(`SUBREQUEST_HTTP_ERROR` dès le premier appel).

## Gateway (`gateway/router.yaml`)

- **CORS** : `localhost:5173`, `localhost:8080` (minikube), Apollo Studio, + regex pour les IP
  privées et Tailscale (test depuis un téléphone sur le même réseau)
- **`dns_resolution_strategy: ipv4_only`** : sans ça le Router échoue sur la résolution AAAA que
  `hubert-network` (IPv4 only) ne sait pas satisfaire
- **`include_subgraph_errors: all`** : erreurs des subgraphs visibles côté client — à couper en prod
- sandbox GraphQL activée sur http://localhost:4000

## Auth

Le Router **vérifie la signature du JWT** (`authentication.router.jwt`) contre le JWKS de
MS-Auth (`http://service-auth:3004/auth/jwks`, RS256). Le token est lu depuis le cookie `jwt` ou
le header `Authorization: Bearer …`. `on_error: Continue` : une requête sans token (ou avec un
token invalide) n'est pas rejetée, elle passe en anonyme — c'est aux subgraphs de trancher.

`gateway/scripts/main.rhai` ne fait ensuite que relire les claims déjà validés et les injecter en
headers vers les subgraphs :

`x-auth-state` (`VALID` / `ANONYMOUS`), `x-user-id`, `x-user-role`, `x-user-email`,
`x-user-pseudo`, `x-user-age`.

Un subgraph ne doit donc jamais refaire la validation, mais il doit toujours vérifier
`x-auth-state` avant de faire confiance aux autres headers.

## Observabilité

Les services envoient traces, métriques et logs en **OTLP** vers l'**otel-collector**
(gRPC `:4317`, HTTP `:4318`), qui redistribue vers **Jaeger** (traces), **Prometheus**
(métriques) et **Loki** (logs). **Grafana** lit les trois, en datasources préprovisionnées.

Les logs des conteneurs Docker sont ramassés par **Grafana Alloy** (`alloy/docker.alloy`), qui
découvre les conteneurs via le **label `logging=enabled`** — un service sans ce label n'apparaît
pas dans Loki.

Prometheus scrape en plus RabbitMQ (`:15692`) et l'Envoy du moteur A*
(`astar_envoy:9901`).

Config à la racine : `otel-collector.yaml`, `prometheus.yaml`, `loki.yaml`,
`alloy/docker.alloy`, `grafana/provisioning/`.

## Branches

- **`develop`** — branche d'intégration, c'est là qu'on travaille et qu'on merge.
- **`main`** — stable, actuellement **4 commits en retard** sur `develop`.

Ce que `main` n'a pas encore : la vérification JWT côté Router (sur `main` la signature n'est
**pas** vérifiée, un token forgé passe), Alloy (elle utilise encore Promtail), le receiver OTLP
HTTP, les scrapes RabbitMQ / Envoy A*, l'export des traces du Router, federation `2.12.1`,
`MS-itinerary-creator` dans `make up`, et 11 pointeurs de submodules plus récents.

## Submodules

Le repo ne stocke qu'un **pointeur** vers un commit de chaque submodule. Tous sont déclarés sur
`branch = develop` dans `.gitmodules`.

```bash
cd microservices/MS-User
git checkout develop       # sinon on est en detached HEAD
# commit, push normalement

cd ../..
git add microservices/MS-User
git commit -m "chore: maj pointeur MS-User"
```

Sans la dernière étape, personne ne voit ton travail en clonant le Project.

Tout mettre à jour depuis les `develop` distants : `git submodule update --remote --merge`

## En cas de galère

| Symptôme | Cause / fix |
|---|---|
| `network hubert-network not found` | `make network` |
| Carte vide, aucun arrêt sur `/trafic` | GTFS pas importé → `make seed` |
| Arrêts / lignes / réseaux absents de la gateway | subgraph manquant dans `supergraph.graphql` → `make supergraph` avec **tout** allumé |
| `SUBREQUEST_HTTP_ERROR` / connection refused | service pas lancé (`make ps`) ou `routing_url` faux |
| Nouveau champ GraphQL invisible | `make supergraph` |
| Erreur CORS | ajouter l'origine dans `router.yaml` puis `make restart-gateway` |
| Conteneur en crash-loop | `.env` manquant dans le submodule → `make logs SERVICE=x` |
| Un service n'a pas de logs dans Grafana | label `logging=enabled` absent de son `docker-compose` |
| 401 / `x-auth-state: ANONYMOUS` inattendu | MS-Auth pas joignable : le Router n'a pas pu charger le JWKS |
| Clone des submodules KO | clé SSH → tester avec `ssh -T git@github.com` |
| `make up` saute MS-Admin_user (Linux) | le Makefile pointe `MS-Admin_User`, le dossier est `MS-Admin_user` — corrigé sur `feat/k8s-runtime-fixes`, pas encore mergé |
