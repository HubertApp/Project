"""Parcours admin (Front-admin) : ajout d'un réseau, puis attente de l'ingestion faite par le back."""

import re
from datetime import datetime, timezone

from rich.markup import escape

import docker_logs
import front_ops
from lib import Ctx, StepFailed, WaitTimeout, step


def registry(ctx: Ctx, offset: int, limit: int) -> list[dict]:
    data = front_ops.call(ctx, "admin.list", {"offset": offset, "limit": limit})
    return data["getRegistredTransitNetworks"]["items"] or []


def _network_id(ctx: Ctx) -> str:
    network_id = ctx.state.get("network_id")
    if not network_id:
        raise StepFailed("aucun réseau dans l'état : rejouer depuis AD1")
    return network_id


def _gtfs(dataset: dict) -> list[dict]:
    return [r for r in dataset["resources"] if r["format"].strip().upper() == "GTFS"]


@step("AD1", "Admin · page d'ajout : recherche d'un réseau dans le catalogue")
def catalogue(ctx: Ctx):
    data = front_ops.call(ctx, "admin.catalogue", {"fournisseurId": ctx.config.fournisseur_id})
    datasets = data["searchTransitNetworksDatasets"]
    ctx.require("le catalogue s'affiche", datasets, f"{len(datasets)} réseaux")

    # filtrage local du navigateur (fillingTransitNetworkFields.js)
    search = ctx.config.dataset_search.lower()
    matches = [d for d in datasets
               if search in d["name"].lower() or search in d["cityOrRegion"].lower()]
    ctx.info(saisie=ctx.config.dataset_search, resultats=len(matches))
    with_gtfs = [d for d in matches if _gtfs(d)]
    ctx.require(f"un résultat pour « {ctx.config.dataset_search} » a une ressource GTFS", with_gtfs,
                "régler E2E_DATASET_SEARCH" if not with_gtfs else f"{len(with_gtfs)} candidats")

    chosen = with_gtfs[0]
    ctx.table(["", "réseau", "ville", "externalId"],
              [["→" if d is chosen else "", d["name"], d["cityOrRegion"], d["externalId"]] for d in with_gtfs[:8]])
    ctx.state["dataset"] = chosen
    ctx.state["network_id"] = chosen["externalId"]
    ctx.state["network_name"] = chosen["name"]


@step("AD2", "Admin · validation du formulaire d'ajout")
def create(ctx: Ctx):
    dataset = ctx.state.get("dataset")
    if not dataset:
        raise StepFailed("aucun dataset dans l'état : rejouer depuis AD1")

    ctx.state["aggregation_requested_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # variables construites comme create_transit_network_service
    body = front_ops.call(ctx, "admin.create", {
        "name": dataset["name"],
        "external_id": dataset["externalId"],
        "description": "",
        "country_code": dataset["countryCode"],
        "city_or_region": dataset["cityOrRegion"],
        "fournisseur_id": "FR_TRANSPORT_GOUV",
        "resources": [{"title": r["title"], "format": r["format"], "endpointUrl": r["endpointUrl"]}
                      for r in dataset["resources"]],
    }, allow_errors=True)

    errors = body.get("errors") or []
    if errors and "existe déjà" in errors[0].get("message", ""):
        # déjà enregistré (run précédent) : l'admin relancerait l'agrégation depuis la fiche
        ctx.info(constat="réseau déjà enregistré → relance de l'agrégation depuis sa fiche")
        data = front_ops.call(ctx, "admin.retrigger", {"external_id": dataset["externalId"]})
        network = data["retriggerAggregation"]
        ctx.check("la relance est acceptée", network["externalId"] == dataset["externalId"])
        ctx.check("le statut repasse à PENDING_AGGREGATION", network["status"] == "PENDING_AGGREGATION",
                  network["status"])
        return

    if errors:
        raise StepFailed(f"CreateTN a renvoyé une erreur : {errors[0].get('message')}")
    network = body["data"]["createTransitNetwork"]
    ctx.info(externalId=network["externalId"], nom=network["name"])
    ctx.check("le réseau créé porte l'externalId du dataset", network["externalId"] == dataset["externalId"])


@step("AD3", "Sécurité · même formulaire envoyé sans jeton",
      known_failure="MS-Admin ne vérifie pas x-auth-state")
def anonymous(ctx: Ctx):
    # Sur le réseau déjà enregistré : protégé, refus d'autorisation ; sinon « existe déjà ».
    # Aucun front ne supprime de réseau, la sonde ne doit donc rien créer.
    dataset = ctx.state.get("dataset")
    if not dataset:
        raise StepFailed("aucun dataset dans l'état : rejouer depuis AD1")
    body = front_ops.call(ctx, "admin.create", {
        "name": dataset["name"],
        "external_id": dataset["externalId"],
        "description": "",
        "country_code": dataset["countryCode"],
        "city_or_region": dataset["cityOrRegion"],
        "fournisseur_id": "FR_TRANSPORT_GOUV",
        "resources": [],
    }, allow_errors=True, anonymous=True)
    message = " ".join(e.get("message", "") for e in body.get("errors") or []).lower()
    ctx.info(reponse=message[:120] or "aucune erreur")
    auth_words = ("auth", "unauthor", "forbidden", "autoris", "401", "403", "token", "jeton")
    ctx.check("la requête est rejetée pour défaut d'autorisation", any(w in message for w in auth_words))


@step("AD4", "Admin · page d'accueil : le réseau apparaît dans la liste")
def listed(ctx: Ctx):
    # main.py : get_transit_network_service(0, 25)
    network_id = _network_id(ctx)
    items = registry(ctx, 0, 25)
    network = next((n for n in items if n["externalId"] == network_id), None)
    ctx.check("le réseau est visible sur la première page (25 réseaux)", network,
              f"{len(items)} réseaux affichés")
    if network:
        ctx.info(statut=f"{network['status']} ({network['statusLabel']})")


@step("AD5", "Admin · fiche réseau rafraîchie jusqu'à la fin de l'ingestion")
def ingestion(ctx: Ctx):
    # get_transit_network_by_external_id_service : (0, 1000) puis filtre
    network_id = _network_id(ctx)
    final: dict = {}

    def refresh():
        network = next((n for n in registry(ctx, 0, 1000) if n["externalId"] == network_id), {})
        final.update(network)
        status = network.get("statusLabel") or network.get("status") or "absent"
        return network.get("status") in ("DATA_AVAILABLE", "AGGREGATION_ERROR"), status

    with ctx.silent():
        ctx.wait_until("rafraîchissement de la fiche", refresh, ctx.config.ingestion_timeout)

    ok = ctx.check("le statut affiché est DATA_AVAILABLE", final.get("status") == "DATA_AVAILABLE",
                   final.get("statusLabel"))
    ctx.state["aggregation_status"] = "ok" if ok else "error"
    if not ok:
        ctx.info(indice="make logs SERVICE=ms-aom-agregator-worker")


@step("AD6", "Admin · mail de fin d'agrégation (vérifié dans les logs)")
def notification_mail(ctx: Ctx):
    network_id = re.escape(_network_id(ctx))
    since = ctx.state.get("aggregation_requested_at")
    if not since:
        raise StepFailed("heure de l'agrégation absente de l'état : rejouer depuis AD2")
    status = ctx.state.get("aggregation_status", "ok")
    subject = "Agrégation terminée" if status == "ok" else "Échec d'agrégation"
    worker, notifications = ctx.config.admin_worker_container, ctx.config.notifications_container

    # Lignes de log émises par ingestion_callback.py (MS-Admin), puis par
    # ms-notifications.controller.ts et smtp-mail.provider.ts (MS-notifications).
    # L'objet et le texte du mail sont rédigés par MS-Admin, MS-notifications
    # les livre tels quels.
    notif_type = "AGGREGATION_SUCCESS" if status == "ok" else "AGGREGATION_ERROR"
    chain = [
        docker_logs.Link(
            "MS-Admin publie la demande de notification", worker,
            rf"Notification admin publiee pour {network_id} \(status={status}\)",
            rf"Notification admin (non publiee|ignoree) pour {network_id}",
            "ADMIN_NOTIFICATION_EMAIL absent du .env de MS-Admin, ou broker indisponible"),
        docker_logs.Link(
            "MS-notifications reçoit la demande", notifications,
            rf"notification_requested reçu \(triggered_by=ms-admin, type={notif_type}",
            r"notification_requested ignoré",
            "payload incomplet envoyé par MS-Admin"),
        docker_logs.Link(
            "MS-notifications crée la notification et le job EMAIL", notifications,
            rf"job\(s\) EMAIL publié\(s\) pour user_id=\S+ \(triggered_by=ms-admin, type={notif_type}\)",
            rf"Échec du traitement de notification_requested pour user_id=\S+ \(triggered_by=ms-admin, type={notif_type}\)"),
        docker_logs.Link(
            f"le mail « {subject} » est envoyé en SMTP", notifications,
            rf'E-mail envoyé à \S+ \("{subject}',
            rf'SMTP_HOST absent : e-mail à \S+ \("{subject}|Livraison abandonnée définitivement : canal="EMAIL"',
            "SMTP_HOST absent ou relais SMTP en erreur côté MS-notifications"),
    ]
    found: dict[int, str] = {}
    failed: dict[int, str] = {}

    def scan():
        logs = {c: docker_logs.read(c, since) for c in {worker, notifications}}
        for i, link in enumerate(chain):
            if i in found or i in failed:
                continue
            lines = logs[link.container]
            if hit := docker_logs.first_match(lines, link.expected):
                found[i] = hit
            elif miss := docker_logs.first_match(lines, link.failure):
                failed[i] = miss
        done = len(found) == len(chain) or bool(failed)
        return done, f"{len(found)}/{len(chain)} maillons"

    ctx.info(depuis=since, conteneurs=f"{worker}, {notifications}")
    try:
        ctx.wait_until("lecture des logs", scan, ctx.config.notification_timeout, interval_s=2)
    except WaitTimeout:
        pass

    rows = []
    for i, link in enumerate(chain):
        line = found.get(i) or failed.get(i)
        detail = "" if i in found else (link.hint or "voir la ligne ci-dessous") if i in failed else "rien dans les logs"
        ctx.check(link.label, i in found, detail)
        rows.append([link.container, escape(line[-140:].strip()) if line else "—"])
    ctx.table(["conteneur", "ligne de log"], rows)
