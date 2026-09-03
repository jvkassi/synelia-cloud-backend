"""Configurations des 13 services managés (copie JSON de `src/lib/configurations/*.ts`)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache
def configurations() -> list[dict[str, Any]]:
    return json.loads((Path(__file__).parent / "configurations.json").read_text())


def configuration(slug: str) -> dict[str, Any] | None:
    return next((c for c in configurations() if c.get("slug") == slug), None)


def slugs() -> list[str]:
    return [c["slug"] for c in configurations() if "slug" in c]
