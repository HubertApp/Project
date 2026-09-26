"""
Requêtes GraphQL des fronts, lues dans leur code source à chaque run : l'e2e
n'en rédige aucune, il rejoue celles des fronts avec les mêmes en-têtes.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib import E2E_DIR, Ctx, StepFailed

REPO_ROOT = E2E_DIR.parent


@dataclass(frozen=True)
class FrontOp:
    front: str
    screen: str
    file: str
    operation: str
    # "bearer" : envoyée par le serveur Front-admin avec GATEWAY_KEY ; "none" : depuis le navigateur
    auth: str = "none"


ADMIN_SERVICE = "front/Front-admin/app/services/transit_network_service.py"
USER_STOPS_API = "front/Front-user-app/src/api/stops.js"

FRONT_OPS = {
    "admin.catalogue": FrontOp("admin", "page d'ajout · catalogue data.gouv",
                               "front/Front-admin/app/static/scripts/researchTransitNetworks.js",
                               "ObtenirLesAOM"),
    "admin.create": FrontOp("admin", "page d'ajout · validation du formulaire", ADMIN_SERVICE, "CreateTN", "bearer"),
    "admin.list": FrontOp("admin", "accueil et fiche réseau · liste du registre", ADMIN_SERVICE,
                          "GetTransitNetworks", "bearer"),
    "admin.retrigger": FrontOp("admin", "fiche réseau · bouton relancer", ADMIN_SERVICE,
                               "RetriggerAggregation", "bearer"),
    "user.search_stops": FrontOp("user", "recherche · barre de recherche", USER_STOPS_API, "SearchStops"),
    "user.stop_detail": FrontOp("user", "fiche arrêt", USER_STOPS_API, "StopDetail"),
    "user.stops_nearby": FrontOp("user", "trafic · carte autour d'un point", USER_STOPS_API, "StopsNearby"),
}


def extract(op: FrontOp) -> str:
    path = REPO_ROOT / op.file
    if not path.exists():
        raise StepFailed(f"fichier introuvable : {op.file} (submodule non cloné ou fichier déplacé ?)")
    source = path.read_text(encoding="utf-8")

    match = re.search(rf"\b(query|mutation)\s+{re.escape(op.operation)}\b", source)
    if not match:
        raise StepFailed(f"opération {op.operation} introuvable dans {op.file} (renommée ?)")

    start = match.start()
    open_at = source.index("{", match.end())
    depth = 0
    for i in range(open_at, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise StepFailed(f"accolades non équilibrées pour {op.operation} dans {op.file}")


def call(ctx: Ctx, key: str, variables: dict[str, Any] | None = None, *,
         allow_errors: bool = False, anonymous: bool = False) -> dict[str, Any]:
    """anonymous=True retire l'en-tête d'auth : appel hors interface."""
    op = FRONT_OPS[key]
    headers = {}
    if op.auth == "bearer" and not anonymous:
        headers["Authorization"] = f"Bearer {ctx.config.gateway_key}"
    source = f"{op.file.split('/')[1]} · {op.screen}" + ("  [sans jeton]" if anonymous else "")
    return ctx.gql(extract(op), variables, headers=headers, allow_errors=allow_errors, source=source)
