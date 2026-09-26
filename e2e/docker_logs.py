"""Lecture des logs Docker, pour constater les effets du back qu'aucun front n'affiche."""

import re
import subprocess
from dataclasses import dataclass

from lib import StepFailed

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def read(container: str, since: str) -> list[str]:
    try:
        proc = subprocess.run(
            ["docker", "logs", "--since", since, container],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
    except FileNotFoundError:
        raise StepFailed("commande docker introuvable")
    if proc.returncode != 0:
        raise StepFailed(f"docker logs {container} : {proc.stderr.strip()[:200]}")
    return [ANSI.sub("", line) for line in (proc.stdout + proc.stderr).splitlines()]


@dataclass
class Link:
    label: str
    container: str
    expected: str
    # ligne qui prouve que ce maillon a échoué : inutile d'attendre davantage
    failure: str | None = None
    hint: str = ""


def first_match(lines: list[str], pattern: str | None) -> str | None:
    if pattern is None:
        return None
    return next((line for line in lines if re.search(pattern, line)), None)
