"""
Parcours e2e : rejoue les requêtes des fronts contre la gateway, étape par étape.

    uv run --project e2e python e2e/run.py              # interactif, pause après chaque étape
    uv run --project e2e python e2e/run.py --from US1   # reprend à US1 avec l'état du run précédent
    uv run --project e2e python e2e/run.py --auto       # sans pause, s'arrête au premier échec
    uv run --project e2e python e2e/run.py --list       # liste les étapes
"""

import argparse
import importlib
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv

from lib import (FAILED, STEPS, Config, Ctx, E2E_DIR, console, load_state, print_summary,
                 prompt_next, run_step, save_state, write_report)
from scenarios import SCENARIOS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="start", help="identifiant de l'étape de départ (ex. US1)")
    parser.add_argument("--auto", action="store_true", help="enchaîne sans pause (CI)")
    parser.add_argument("--list", action="store_true", help="liste les étapes et quitte")
    args = parser.parse_args()

    load_dotenv(E2E_DIR / ".env")
    for module in SCENARIOS:
        importlib.import_module(module)

    if args.list:
        for s in STEPS:
            console.print(f"[bold]{s.id:>4}[/]  {s.title}" + ("  [yellow](échec connu)[/]" if s.known_failure else ""))
        return 0

    ids = [s.id for s in STEPS]
    start = 0
    if args.start:
        if args.start.upper() not in ids:
            console.print(f"[red]étape inconnue : {args.start}[/] (disponibles : {', '.join(ids)})")
            return 2
        start = ids.index(args.start.upper())

    # Un run complet repart de zéro ; une reprise réutilise l'état du run précédent.
    state = load_state() if start > 0 else {}
    config = Config.from_env()
    steps = STEPS[start:]

    results = []
    started_at = datetime.now()
    with httpx.Client(timeout=60) as http:
        ctx = Ctx(config=config, state=state, http=http)
        try:
            i = 0
            while i < len(steps):
                result = run_step(steps[i], ctx, f"{start + i + 1}/{len(STEPS)}")
                save_state(ctx.state)

                if args.auto:
                    results.append(result)
                    if result.status == FAILED:
                        break
                    i += 1
                    continue

                choice = prompt_next(result, ctx)
                if choice == "retry":
                    continue
                results.append(result)
                if choice == "quit":
                    break
                i += 1
        finally:
            # aussi sur Ctrl+C
            print_summary(results)
            write_report(results, ctx, started_at)

    return 1 if any(r.status == FAILED for r in results) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # ✔/✘ sous Windows
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        console.print("\n[dim]interrompu[/]")
        sys.exit(130)
