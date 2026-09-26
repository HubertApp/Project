# E2E — parcours utilisateurs rejoués contre la gateway

L'e2e se met à la place des fronts : il envoie à la gateway (`localhost:4000`) **exactement
les requêtes que Front-admin et Front-user-app envoient**, avec les mêmes en-têtes, dans
l'ordre d'un vrai parcours. Il ne touche jamais au back directement : l'ingestion GTFS et les
changements de statut sont orchestrés par le back seul, et on les constate comme un
utilisateur, en rafraîchissant un écran.

```bash
make up            # la stack doit tourner
make e2e           # interactif, pause après chaque étape
make e2e FROM=US1  # reprend à US1 avec l'état du run précédent
make e2e AUTO=1    # sans pause, s'arrête au premier échec (code de sortie 1)
make e2e-list      # liste les étapes
```

Prérequis : [uv](https://docs.astral.sh/uv/). Configuration optionnelle : copier `.env.example`
en `.env` (notamment `E2E_GATEWAY_KEY`, le jeton de Front-admin).

Entre deux étapes : `Entrée` continuer · `r` rejouer · `d` voir le JSON échangé (avec les
en-têtes) · `q` quitter. Après un échec : `c` pour continuer quand même.

## Rapports

Chaque run, même interrompu (`q` ou Ctrl+C), écrit un dossier dans `e2e/reports/` (gitignoré),
dont le chemin est affiché à la fin :

```
e2e/reports/2026-09-25_14-32-07/
  run.html        copie du terminal (couleurs, tableaux) : à ouvrir dans un navigateur ou à partager
  exchanges.json  verdict de chaque étape + toutes les requêtes/réponses (étape, écran, variables,
                  en-têtes, HTTP, durée, horodatage) : pour déboguer et recouper avec Jaeger/Loki
```

Le jeton est masqué (`Bearer ***`). Pour les sondages de AD5, seul le dernier est gardé.

## Les parcours

| | Écran | Requête du front |
|---|---|---|
| **P0** | — | gateway joignable + chaque requête retrouvée dans le code des fronts |
| **AD1** | Admin · page d'ajout, recherche dans le catalogue | `ObtenirLesAOM` (navigateur, sans jeton) |
| **AD2** | Admin · validation du formulaire (ou « Relancer » si déjà enregistré) | `CreateTN` / `RetriggerAggregation` (Bearer) |
| **AD3** | Sécurité · même formulaire sans jeton | `CreateTN` sans en-tête — **échec connu** |
| **AD4** | Admin · page d'accueil | `GetTransitNetworks(0, 25)` |
| **AD5** | Admin · fiche réseau rafraîchie jusqu'à `DATA_AVAILABLE` | `GetTransitNetworks(0, 1000)` |
| **US1** | Utilisateur · barre de recherche | `SearchStops` (vérifie la jointure fédérée `network`) |
| **US2** | Utilisateur · fiche arrêt | `StopDetail` (lignes, prochains passages) |
| **US3** | Utilisateur · carte trafic | `StopsNearby` |
| **US4** | Utilisateur · planifier un trajet | aucune : le front utilise `data/mock` — **échec connu** |

Le script est rejouable : aucun front ne supprime de réseau, donc au second run AD2 fait ce
que ferait l'admin, relancer l'agrégation depuis la fiche.

**Échecs connus** (`⚠ CONNU`, ne font pas échouer le run) : quand l'un passe en `★ CORRIGÉ`,
retirer `known_failure` de l'étape (et pour US4, brancher la vraie requête d'itinéraire).

## Les requêtes ne sont pas recopiées

`front_ops.py` lit chaque requête **dans le code source du front** au lancement, par le nom
de son opération GraphQL. Si un front modifie une requête, l'e2e teste la nouvelle version
sans rien toucher. Si un fichier bouge ou qu'une opération est renommée, P0 le signale.

## Faire évoluer

| Changement | Où |
|---|---|
| Un front ajoute un écran / une requête | une entrée dans `FRONT_OPS` (`front_ops.py`) |
| Le parcours change | les étapes `@step` dans `scenarios/` |
| Nouveau parcours | un module dans `scenarios/`, ajouté à `scenarios/__init__.py` |
| Les variables d'une requête changent | l'étape qui l'appelle (elles reproduisent celles du front) |

```python
@step("US5", "Utilisateur · mon nouvel écran")
def my_screen(ctx):
    data = front_ops.call(ctx, "user.my_op", {"id": ctx.state["stop"]["id"]})  # requête du front
    ctx.check("l'écran affiche X", data["x"], "détail")    # ✔/✘, continue
    ctx.require("condition bloquante", ...)                # ✘ et arrête l'étape
    ctx.info(cle="valeur")  /  ctx.table(colonnes, lignes)
    ctx.state["y"] = ...                                   # transmis aux étapes suivantes
```

Règle : une étape n'envoie que des requêtes présentes dans `FRONT_OPS`. Si une vérification
demande une requête qu'aucun front n'envoie, c'est un manque du front, pas de l'e2e.
