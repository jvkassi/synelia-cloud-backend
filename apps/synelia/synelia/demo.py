"""Jeu de données de démonstration minimal (extensible par module via `PEUPLEURS`).

Chaque module peut enregistrer une coroutine `(session, org, admin)` qui crée ses ressources de démo."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from synelia_db.modeles import Organisation, Utilisateur
from synelia_kernel.journal import journal

log = journal("demo")

PEUPLEURS: list[Callable[[AsyncSession, Organisation, Utilisateur], Awaitable[Any]]] = []


def peupleur(f: Callable[[AsyncSession, Organisation, Utilisateur], Awaitable[Any]]):
    PEUPLEURS.append(f)
    return f


async def peupler(session: AsyncSession, org: Organisation, admin: Utilisateur) -> None:
    from synelia.app import routeurs_modules  # charge les modules → enregistre les peupleurs

    routeurs_modules()
    for f in PEUPLEURS:
        try:
            await f(session, org, admin)
        except Exception as exc:  # noqa: BLE001
            log.warning("demo.peupleur_echoue", peupleur=f.__module__, erreur=str(exc))
