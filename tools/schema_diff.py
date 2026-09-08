#!/usr/bin/env python3
"""Compare le schéma Postgres vivant à `Base.metadata` (les modèles SQLAlchemy) — lecture
seule, aucune écriture. `create_all` fait foi (voir `synelia_db.session.initialiser_schema` et
`docs/ADR/0003-schema-create-all-sans-migrations.md`) : cet outil est la preuve vérifiable
qu'aucun `ALTER TABLE` fait à la main n'a dérivé du modèle vivant.

    uv run python tools/schema_diff.py
    docker exec synelia-backend-dev01-api-1 python tools/schema_diff.py

Se connecte avec l'engine de l'appli (`SYNELIA_DATABASE_URL`, rôle `synelia_app` sur dev01) —
mêmes droits que l'API, donc un simple `SELECT` de catalogue, rien de plus. Sortie 0 si
identique, 1 sinon. Une table présente en base mais absente des modèles est signalée mais ne
compte pas comme un écart bloquant (ex. une future `alembic_version` qui n'existe pas ici)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

import synelia_db.modeles  # noqa: E402,F401 — enregistre les tables sur Base.metadata
from sqlalchemy import inspect  # noqa: E402
from synelia_db.base import Base  # noqa: E402
from synelia_db.session import engine  # noqa: E402


def _type_normalise(texte: str) -> str:
    """Tolérant à la casse et aux longueurs (`VARCHAR(36)` == `varchar`)."""
    texte = texte.strip().upper()
    return texte.split("(", 1)[0] if "(" in texte else texte


def _comparer(conn: Any) -> list[str]:
    insp = inspect(conn)
    ecarts: list[str] = []
    tables_db = set(insp.get_table_names())

    for table in Base.metadata.sorted_tables:
        nom = table.name
        if nom not in tables_db:
            ecarts.append(f"{nom} : table absente en base")
            continue

        colonnes_db = {c["name"]: c for c in insp.get_columns(nom)}
        for col in table.columns:
            if col.name not in colonnes_db:
                ecarts.append(f"{nom}.{col.name} : colonne absente en base")
                continue
            col_db = colonnes_db[col.name]
            if bool(col_db["nullable"]) != bool(col.nullable):
                ecarts.append(
                    f"{nom}.{col.name} : nullable={col_db['nullable']} en base, "
                    f"{bool(col.nullable)} dans le modèle"
                )
            type_modele = _type_normalise(str(col.type.compile(dialect=conn.dialect)))
            type_db = _type_normalise(str(col_db["type"]))
            if type_modele != type_db:
                ecarts.append(f"{nom}.{col.name} : type={type_db} en base, {type_modele} dans le modèle")

        colonnes_en_trop = set(colonnes_db) - {c.name for c in table.columns}
        for c in sorted(colonnes_en_trop):
            ecarts.append(f"{nom}.{c} : colonne en base absente du modèle")

        index_db = {ix["name"] for ix in insp.get_indexes(nom) if not ix["name"].endswith("_pkey")}
        index_modele = {ix.name for ix in table.indexes}
        for manquant in sorted(index_modele - index_db):
            ecarts.append(f"{nom} : index déclaré absent en base : {manquant}")
        for en_trop in sorted(index_db - index_modele):
            ecarts.append(f"{nom} : index en base absent du modèle : {en_trop}")

    tables_modele = {t.name for t in Base.metadata.sorted_tables}
    for t in sorted(tables_db - tables_modele):
        ecarts.append(f"{t} : table en base absente des modèles (non bloquant)")

    return ecarts


async def diff() -> list[str]:
    eng = engine()
    async with eng.connect() as conn:
        return await conn.run_sync(_comparer)


async def _principal() -> int:
    ecarts = await diff()
    bloquants = [e for e in ecarts if "non bloquant" not in e]
    for e in ecarts:
        print(e)
    if not bloquants:
        print("identique")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_principal()))
