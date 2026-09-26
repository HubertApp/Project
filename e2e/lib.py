"""Moteur du parcours : étapes, client GraphQL, vérifications, affichage, rapports."""

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
from rich.console import Console
from rich.json import JSON
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

# record=True : l'affichage est rejoué dans run.html en fin de run.
console = Console(record=True)

E2E_DIR = Path(__file__).parent
STATE_FILE = E2E_DIR / ".e2e-state.json"
REPORTS_DIR = E2E_DIR / "reports"


@dataclass
class Config:
    gateway_url: str
    gateway_key: str
    fournisseur_id: str
    dataset_search: str
    ingestion_timeout: int
    stop_queries: list[str]

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            gateway_url=os.getenv("GATEWAY_URL", "http://localhost:4000/"),
            # défaut identique à Front-admin (app/core/config.py)
            gateway_key=os.getenv("E2E_GATEWAY_KEY") or "<TOKEN>",
            fournisseur_id=os.getenv("E2E_FOURNISSEUR_ID", "FR_TRANSPORT_GOUV"),
            dataset_search=os.getenv("E2E_DATASET_SEARCH", "metz"),
            ingestion_timeout=int(os.getenv("E2E_INGESTION_TIMEOUT", "180")),
            stop_queries=[
                q.strip()
                for q in os.getenv(
                    "E2E_STOP_QUERIES", "gare,place,mairie,eglise,centre,ecole,rue"
                ).split(",")
                if q.strip()
            ],
        )


@dataclass
class Step:
    id: str
    title: str
    fn: Callable[["Ctx"], None]
    # bug connu : affiché en jaune, ne fait pas échouer le run
    known_failure: str | None = None


STEPS: list[Step] = []


def step(id: str, title: str, known_failure: str | None = None):
    """Les étapes s'exécutent dans l'ordre de leur déclaration."""

    def register(fn: Callable[["Ctx"], None]):
        STEPS.append(Step(id, title, fn, known_failure))
        return fn

    return register


class StepFailed(Exception):
    """Arrête l'étape en cours."""


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class Ctx:
    config: Config
    state: dict[str, Any]
    http: httpx.Client
    checks: list[Check] = field(default_factory=list)
    exchanges: list[dict[str, Any]] = field(default_factory=list)
    echo: bool = True
    current_step: str = ""
    # exchanges : étape en cours (touche d) ; run_log : tout le run (exchanges.json)
    run_log: list[dict[str, Any]] = field(default_factory=list)

    @contextmanager
    def silent(self):
        """N'affiche pas les appels GraphQL du bloc (sondages répétés)."""
        self.echo = False
        try:
            yield
        finally:
            self.echo = True


    def gql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        allow_errors: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Une erreur GraphQL arrête l'étape, sauf avec allow_errors=True qui renvoie {"data", "errors"}."""
        name = _operation_name(query)
        if self.echo:
            if source:
                console.print(f"  [magenta]{escape(source)}[/]")
            console.print(f"[cyan]→[/] {name}  [dim]{_short(variables)}[/]")

        started = time.perf_counter()
        try:
            response = self.http.post(
                self.config.gateway_url,
                json={"query": query, "variables": variables or {}},
                headers=headers or {},
            )
        except httpx.HTTPError as exc:
            raise StepFailed(f"gateway injoignable ({self.config.gateway_url}) : {exc}")
        elapsed_ms = (time.perf_counter() - started) * 1000

        try:
            body = response.json()
        except ValueError:
            body = {"errors": [{"message": response.text[:500]}]}

        exchange = {
            "step": self.current_step,
            "at": datetime.now().isoformat(timespec="milliseconds"),
            "operation": name,
            "source": source,
            "headers": _mask(headers or {}),
            "variables": variables,
            "status": response.status_code,
            "duration_ms": round(elapsed_ms),
            "response": body,
        }
        if not self.echo:
            exchange["polled"] = True
        for log in (self.exchanges, self.run_log):
            # sondages répétés : seul le dernier est gardé
            if exchange.get("polled") and log and log[-1].get("polled") and log[-1]["step"] == self.current_step:
                log[-1] = exchange
            else:
                log.append(exchange)

        errors = body.get("errors") or []
        colour = "red" if errors else "green"
        if self.echo:
            console.print(f"[{colour}]←[/] HTTP {response.status_code} en {elapsed_ms:.0f} ms"
                      + (f"  [red]{len(errors)} erreur(s)[/]" if errors else ""))

        if allow_errors:
            return body
        if errors:
            messages = "; ".join(e.get("message", "?") for e in errors)
            raise StepFailed(f"{name} a renvoyé une erreur : {messages}")
        return body.get("data") or {}


    def check(self, label: str, ok: bool, detail: Any = "") -> bool:
        ok = bool(ok)
        self.checks.append(Check(label, ok, str(detail) if detail != "" else ""))
        mark = "[green]✔[/]" if ok else "[red]✘[/]"
        suffix = f"  [dim]{detail}[/]" if detail != "" else ""
        console.print(f"  {mark} {label}{suffix}")
        return ok

    def require(self, label: str, ok: bool, detail: Any = "") -> None:
        """Comme `check`, mais arrête l'étape si la condition est fausse."""
        if not self.check(label, ok, detail):
            raise StepFailed(label)


    def info(self, **values: Any) -> None:
        width = max(len(k) for k in values)
        for key, value in values.items():
            console.print(f"  [dim]{key.ljust(width)}[/] : {value}")

    def table(self, columns: list[str], rows: list[list[Any]], title: str | None = None) -> None:
        table = Table(*columns, title=title, title_justify="left", show_edge=False, pad_edge=False)
        for row in rows:
            table.add_row(*("" if v is None else str(v) for v in row))
        console.print(table)


    def wait_until(
        self,
        label: str,
        probe: Callable[[], tuple[bool, str]],
        timeout_s: int,
        interval_s: float = 3.0,
    ) -> str:
        """Rappelle probe() -> (terminé, texte du spinner) jusqu'à terminé ou délai dépassé."""
        started = time.monotonic()
        last = ""
        with console.status(f"{label}…") as status:
            while True:
                done, last = probe()
                elapsed = time.monotonic() - started
                status.update(f"{label}… {elapsed:.0f}s — {last}")
                if done:
                    console.print(f"  [dim]terminé après {elapsed:.0f}s — {last}[/]")
                    return last
                if elapsed >= timeout_s:
                    raise StepFailed(f"{label} : délai de {timeout_s}s dépassé (dernier état : {last})")
                time.sleep(interval_s)


def _mask(headers: dict[str, str]) -> dict[str, str]:
    return {k: ("Bearer ***" if k.lower() == "authorization" else v) for k, v in headers.items()}


def _operation_name(query: str) -> str:
    words = query.strip().split()
    if len(words) >= 2 and words[0] in ("query", "mutation"):
        return f"{words[0]} {words[1].split('(')[0]}"
    return "query"


def _short(variables: dict[str, Any] | None, limit: int = 90) -> str:
    if not variables:
        return ""
    text = json.dumps(variables, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


PASSED, FAILED, KNOWN, FIXED = "passed", "failed", "known", "fixed"

BADGES = {
    PASSED: "[green]✔ OK[/]",
    FAILED: "[red]✘ ÉCHEC[/]",
    KNOWN: "[yellow]⚠ CONNU[/]",
    FIXED: "[magenta]★ CORRIGÉ[/]",
}


@dataclass
class Result:
    step: Step
    status: str
    duration_s: float
    error: str = ""


def run_step(s: Step, ctx: Ctx, position: str) -> Result:
    console.rule(f"[bold]{s.id}[/] · {s.title}  [dim]{position}[/]", align="left")
    if s.known_failure:
        console.print(f"  [yellow]échec connu attendu :[/] {s.known_failure}")

    ctx.checks.clear()
    ctx.exchanges.clear()
    ctx.current_step = s.id
    started = time.perf_counter()
    error = ""
    try:
        s.fn(ctx)
    except StepFailed as exc:
        error = str(exc)
    except Exception as exc:  # une étape boguée ne doit pas arrêter le runner
        error = f"{type(exc).__name__}: {exc}"
    duration = time.perf_counter() - started

    failed = bool(error) or any(not c.ok for c in ctx.checks)
    if s.known_failure:
        status = KNOWN if failed else FIXED
    else:
        status = FAILED if failed else PASSED

    if error:
        console.print(f"  [red]arrêt de l'étape :[/] {error}")
    if status == FIXED:
        console.print("  [magenta]l'échec connu ne se produit plus : retirer `known_failure` de cette étape.[/]")
    console.print(f"\n  {BADGES[status]}  [dim]{duration:.1f}s[/]")
    return Result(s, status, duration, error)


def prompt_next(result: Result, ctx: Ctx) -> str:
    blocking = result.status == FAILED
    options = (
        "[bold]\\[r][/] rejouer   [bold]\\[c][/] continuer malgré l'échec   [bold]\\[d][/] détail JSON   [bold]\\[q][/] quitter"
        if blocking
        else "[bold]\\[Entrée][/] continuer   [bold]\\[r][/] rejouer   [bold]\\[d][/] détail JSON   [bold]\\[q][/] quitter"
    )
    while True:
        answer = console.input(f"\n{options}\n> ").strip().lower()
        if answer == "d":
            show_exchanges(ctx)
            continue
        if answer == "r":
            return "retry"
        if answer == "q":
            return "quit"
        if answer == "c" or (answer == "" and not blocking):
            return "next"


def show_exchanges(ctx: Ctx) -> None:
    if not ctx.exchanges:
        console.print("  [dim]aucun appel GraphQL dans cette étape[/]")
    for exchange in ctx.exchanges:
        console.print(Panel(JSON.from_data(exchange, default=str), title=exchange["operation"], title_align="left"))


def print_summary(results: list[Result]) -> None:
    console.rule("[bold]Récapitulatif[/]", align="left")
    table = Table("Étape", "Titre", "Statut", "Durée", "Détail", show_edge=False)
    for r in results:
        table.add_row(r.step.id, r.step.title, BADGES[r.status], f"{r.duration_s:.1f}s", r.error)
    console.print(table)


def write_report(results: list[Result], ctx: Ctx, started_at: datetime) -> Path:
    folder = REPORTS_DIR / started_at.strftime("%Y-%m-%d_%H-%M-%S")
    folder.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "gateway": ctx.config.gateway_url,
        "results": [
            {"step": r.step.id, "title": r.step.title, "status": r.status,
             "duration_s": round(r.duration_s, 2), "error": r.error}
            for r in results
        ],
        "exchanges": ctx.run_log,
    }
    (folder / "exchanges.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    console.print(f"\n[dim]rapport :[/] {folder}")
    console.save_html(str(folder / "run.html"))
    return folder
