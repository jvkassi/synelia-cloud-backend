"""Couverture du contrat : opérations du contrat ↔ routes de l'application (servie ⊇ contrat).

    uv run python tools/contrat_diff.py [--strict]"""

from __future__ import annotations

import sys
from collections import defaultdict


def executer(strict: bool = False) -> int:
    from fastapi.routing import APIRoute
    from synelia.app import creer_app
    from synelia_contract.operations import OPERATIONS

    app = creer_app()
    servies: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            chemin = route.path.removeprefix("/v1")
            for meth in route.methods:
                servies.add((meth, chemin))
    par_tag: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    manquantes = []
    for o in OPERATIONS:
        par_tag[o.tag][1] += 1
        if (o.methode, o.chemin) in servies:
            par_tag[o.tag][0] += 1
        else:
            manquantes.append(o)
    total = len(OPERATIONS)
    faites = total - len(manquantes)
    for tag, (f, t) in sorted(par_tag.items(), key=lambda x: -(x[1][1] - x[1][0])):
        marque = "✓" if f == t else " "
        print(f"{marque} {f:3d}/{t:<3d} {tag}")
    print(f"\nCouverture : {faites}/{total} opérations ({100 * faites // total} %)")
    if manquantes:
        print("\nManquantes :")
        for o in manquantes:
            print(f"  {o.methode:6s} {o.chemin}  ({o.operation_id})")
    return 1 if (strict and manquantes) else 0


if __name__ == "__main__":
    raise SystemExit(executer("--strict" in sys.argv))
