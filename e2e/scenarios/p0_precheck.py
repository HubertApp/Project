"""P0 · vérifie que la gateway répond et que chaque requête des fronts est retrouvée dans leur code."""

from front_ops import FRONT_OPS, extract
from lib import Ctx, StepFailed, step


@step("P0", "Pré-check : gateway et requêtes des fronts")
def precheck(ctx: Ctx):
    ctx.info(gateway=ctx.config.gateway_url)
    ctx.gql("query Ping { __typename }")
    ctx.check("la gateway répond", True)

    rows = []
    for key, op in FRONT_OPS.items():
        try:
            extract(op)
            found = "[green]✔[/]"
        except StepFailed as exc:
            found = f"[red]✘ {exc}[/]"
        rows.append([found, op.front, op.screen, op.operation, op.file.split("/", 2)[2]])
    ctx.table(["", "front", "écran", "opération", "fichier"], rows)
    missing = [r for r in rows if "✘" in r[0]]
    ctx.check("toutes les requêtes des fronts sont extraites", not missing,
              f"{len(rows) - len(missing)}/{len(rows)}")
