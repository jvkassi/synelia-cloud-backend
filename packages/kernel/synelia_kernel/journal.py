"""Journalisation structurée (structlog, JSON) avec correlation_id, org_id, user_id."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

correlation_id_courant: ContextVar[str] = ContextVar("correlation_id", default="-")
org_id_courant: ContextVar[str | None] = ContextVar("org_id", default=None)
utilisateur_id_courant: ContextVar[str | None] = ContextVar("utilisateur_id", default=None)

_SECRETS = ("motDePasse", "mot_de_passe", "password", "secret", "token", "jeton", "accessToken", "refreshToken", "cle", "apiKey")


def _contexte(_logger: Any, _methode: str, event: dict[str, Any]) -> dict[str, Any]:
    event.setdefault("correlation_id", correlation_id_courant.get())
    org = org_id_courant.get()
    if org:
        event.setdefault("org_id", org)
    uid = utilisateur_id_courant.get()
    if uid:
        event.setdefault("user_id", uid)
    return event


def _masquer(_logger: Any, _methode: str, event: dict[str, Any]) -> dict[str, Any]:
    for cle in list(event):
        if any(s.lower() in cle.lower() for s in _SECRETS):
            event[cle] = "***"
    return event


_configure = False


def configurer(json: bool = True, niveau: int = logging.INFO) -> None:
    global _configure
    if _configure:
        return
    processeurs: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _contexte,
        _masquer,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    processeurs.append(structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processeurs,
        wrapper_class=structlog.make_filtering_bound_logger(niveau),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    _configure = True


def journal(nom: str) -> Any:
    configurer()
    return structlog.get_logger(nom)
