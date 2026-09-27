"""Parcours utilisateur (Front-user-app) : consultation du réseau ajouté par l'admin."""

from datetime import datetime

import front_ops
from front_ops import REPO_ROOT
from lib import Ctx, StepFailed, step


def _stop(ctx: Ctx) -> dict:
    stop = ctx.state.get("stop")
    if not stop:
        raise StepFailed("aucun arrêt dans l'état : rejouer depuis US1")
    return stop


def _lines(routes: list[dict]) -> str:
    return ", ".join(r["shortName"] or r["longName"] or r["id"] for r in routes[:8]) or "—"


@step("US1", "Utilisateur · recherche d'un arrêt du nouveau réseau")
def search(ctx: Ctx):
    network_name = ctx.state.get("network_name")
    if not network_name:
        raise StepFailed("aucun réseau dans l'état : rejouer depuis AD1")

    # useStopSearch : first = 20, pas de filtre de réseau
    found, results = None, []
    for query in ctx.config.stop_queries:
        results = front_ops.call(ctx, "user.search_stops", {"query": query, "first": 20})["searchStops"]
        ours = [s for s in results if (s.get("network") or {}).get("name") == network_name]
        if ours:
            found = ours[0]
            break

    ctx.check("chaque résultat affiche son réseau (jointure fédérée MS-Admin)",
              all(s.get("network") and s["network"].get("name") for s in results),
              f"{len(results)} résultats")
    ctx.require(f"un arrêt du réseau « {network_name} » remonte dans la recherche", found,
                "régler E2E_STOP_QUERIES" if not found else "")

    ctx.table(["arrêt", "réseau", "ville", "lignes"],
              [[s["name"], (s.get("network") or {}).get("name"), (s.get("network") or {}).get("cityOrRegion"),
                _lines(s["routes"])] for s in results[:8]])
    location = found.get("location") or {}
    ctx.check("l'arrêt est géolocalisé", location.get("latitude") is not None)
    ctx.state["stop"] = {"id": found["id"], "name": found["name"],
                         "lat": location.get("latitude"), "lon": location.get("longitude")}


@step("US2", "Utilisateur · fiche de l'arrêt")
def detail(ctx: Ctx):
    stop = _stop(ctx)
    # useStop : first = DEPARTURES_SHOWN, after = nowAsGtfsTime()
    after = datetime.now().strftime("%H:%M:%S")
    data = front_ops.call(ctx, "user.stop_detail", {"id": stop["id"], "first": 10, "after": after})
    detail = data["stop"]
    ctx.require("la fiche s'affiche", detail)
    ctx.check("c'est le bon arrêt", detail["name"] == stop["name"], detail["name"])
    ctx.check("le réseau est affiché", (detail.get("network") or {}).get("name") == ctx.state.get("network_name"))
    ctx.check("les lignes desservies sont affichées", detail["routes"], _lines(detail["routes"]))

    departures = detail["departures"]
    ctx.check("des prochains passages sont affichés", departures,
              f"{len(departures)} après {after}" if departures
              else f"aucun après {after} — normal la nuit ou si le GTFS ne couvre pas aujourd'hui")
    ctx.table(["heure", "ligne", "direction"],
              [[d["departureTime"], (d.get("route") or {}).get("shortName"), d["headsign"]] for d in departures])


@step("US3", "Utilisateur · carte trafic autour de l'arrêt")
def nearby(ctx: Ctx):
    stop = _stop(ctx)
    if stop["lat"] is None:
        raise StepFailed("arrêt sans coordonnées")
    # TrafficPage : rayon par défaut 500 m, first = 50
    stops = front_ops.call(ctx, "user.stops_nearby", {
        "lat": stop["lat"], "lon": stop["lon"], "radiusMeters": 500, "first": 50,
    })["stopsNearby"]
    ctx.check("des arrêts sont affichés sur la carte", stops, f"{len(stops)} dans un rayon de 500 m")
    ctx.check("l'arrêt recherché en fait partie", any(s["id"] == stop["id"] for s in stops))
    ctx.check("les arrêts affichent leurs lignes", all(s["routes"] is not None for s in stops))
    ctx.table(["arrêt", "distance", "lignes"],
              [[s["name"], f"{s['distanceMeters']:.0f} m", _lines(s["routes"])] for s in stops[:8]])


@step("US4", "Utilisateur · planification d'un trajet",
      known_failure="SearchPage affiche un itinéraire factice (data/mock), aucune requête au back")
def itinerary(ctx: Ctx):
    # Pas de requête à rejouer : le front n'appelle pas le back. Une fois branché, remplacer
    # cette étape par la vraie requête d'itinéraire.
    search_page = REPO_ROOT / "front/Front-user-app/src/pages/SearchPage.jsx"
    source = search_page.read_text(encoding="utf-8")
    uses_mock = "itinerarySteps" in source and "data/mock" in source
    ctx.check("SearchPage calcule l'itinéraire via le back", not uses_mock,
              "importe itinerarySteps depuis data/mock" if uses_mock else "")
