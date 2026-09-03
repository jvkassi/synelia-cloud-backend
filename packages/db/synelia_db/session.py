from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from synelia_kernel.config import reglages

from synelia_db import rls
from synelia_db.base import Base

_engine: AsyncEngine | None = None
_fabrique: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine, _fabrique
    if _engine is None:
        r = reglages()
        options: dict = {"echo": r.echo_sql}
        if r.est_sqlite:
            options["connect_args"] = {"timeout": 30}
        else:
            options["pool_pre_ping"] = True
            options["pool_size"] = 5
        _engine = create_async_engine(r.database_url, **options)
        if r.est_postgres and r.rls_active:
            rls.brancher(_engine)
        _fabrique = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def fabrique() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _fabrique is not None
    return _fabrique


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    async with fabrique()() as s:
        yield s


async def initialiser_schema() -> None:
    """Crée les tables manquantes (dev, tests, Vercel/SQLite). En production Postgres, Alembic fait foi."""
    import synelia_db.modeles  # noqa: F401  — enregistre les tables

    r = reglages()
    eng = engine()
    async with eng.begin() as conn:
        if r.est_sqlite:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
        if r.est_postgres and r.rls_active:
            for ddl in rls.sql_politiques():
                await conn.execute(text(ddl))


async def fermer() -> None:
    global _engine, _fabrique
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _fabrique = None
