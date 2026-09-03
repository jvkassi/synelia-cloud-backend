"""Identifiants : UUID v7, triables, sans coordination."""

from __future__ import annotations

import secrets

from uuid_utils import uuid7


def nouvel_id() -> str:
    return str(uuid7())


def jeton_opaque(octets: int = 32) -> str:
    return secrets.token_urlsafe(octets)


def prefixe_lisible(prefixe: str = "syn") -> str:
    return f"{prefixe}_{secrets.token_hex(4)}"
