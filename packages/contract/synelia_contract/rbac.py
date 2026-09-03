"""Matrice RBAC : 38 actions × 10 rôles, copiée du frontend (`rbac.json`), vérifiée identique en CI."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

Permission = Literal["full", "read", "none"]

ROLES_ORDRE: tuple[str, ...] = (
    "super_admin",
    "platform_operator",
    "org_admin",
    "espace_admin",
    "project_owner",
    "operator",
    "service_admin",
    "billing_manager",
    "compliance",
    "read_only",
)
ROLES_EQUIPE: frozenset[str] = frozenset({"super_admin", "platform_operator"})
ROLES_CLIENT: tuple[str, ...] = tuple(r for r in ROLES_ORDRE if r not in ROLES_EQUIPE)

ROLE_LABEL: dict[str, str] = {
    "super_admin": "Super Admin",
    "platform_operator": "Opérateur plateforme",
    "org_admin": "Org Admin",
    "espace_admin": "Espace Cloud Admin",
    "project_owner": "Propriétaire de projet",
    "operator": "Opérateur",
    "service_admin": "Admin de service",
    "billing_manager": "Gestionnaire facturation",
    "compliance": "Conformité",
    "read_only": "Lecture seule",
}


@lru_cache
def matrice() -> list[dict]:
    return json.loads((Path(__file__).parent / "rbac.json").read_text())["actions"]


@lru_cache
def _index() -> dict[str, dict]:
    return {a["id"]: a for a in matrice()}


def permission(role: str, action: str) -> Permission:
    """Permission d'un rôle sur une action. Action inconnue → autorisée (comme le frontend)."""
    a = _index().get(action)
    if a is None:
        return "full"
    return a["perms"].get(role, "none")


def autorise(role: str, action: str, lecture: bool = False) -> bool:
    p = permission(role, action)
    return p == "full" or (lecture and p == "read")


def roles_requis(action: str) -> list[str]:
    a = _index().get(action)
    if a is None:
        return []
    return [r for r in ROLES_ORDRE if a["perms"].get(r) == "full"]


def libelle(action: str) -> str:
    a = _index().get(action)
    return a["libelle"] if a else action


def message_refus(action: str) -> str:
    roles = [r for r in roles_requis(action) if r not in ROLES_EQUIPE] or roles_requis(action)
    if not roles:
        return "Action réservée à Synelia."
    noms = [ROLE_LABEL[r] for r in roles[:2]]
    return f"Cette action demande le rôle {' ou '.join(noms)}."


def permissions_effectives(role: str) -> dict[str, Permission]:
    return {a["id"]: a["perms"].get(role, "none") for a in matrice()}
