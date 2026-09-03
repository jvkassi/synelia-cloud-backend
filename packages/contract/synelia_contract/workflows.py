"""Catalogue des 41 travaux de provisioning (copie de `src/lib/mock/workflows.ts`)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache
def catalogue() -> dict[str, dict[str, Any]]:
    data = json.loads((Path(__file__).parent / "workflows.json").read_text())
    return {w["id"]: w for w in data}


def definition(type_travail: str) -> dict[str, Any] | None:
    return catalogue().get(type_travail)


def etapes(type_travail: str) -> list[dict[str, Any]]:
    d = definition(type_travail)
    return list(d["etapes"]) if d else []


def libelle(type_travail: str, cible: str) -> str:
    d = definition(type_travail)
    if not d:
        return f"{type_travail} — {cible}"
    return d["libelle"].replace("{cible}", cible)


@lru_cache
def marketplace() -> dict[str, Any]:
    return json.loads((Path(__file__).parent / "marketplace.json").read_text())
