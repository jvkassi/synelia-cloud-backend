"""Row-Level Security : `SET LOCAL app.org_id` posé à l'ouverture de chaque transaction Postgres.

Le filtre applicatif par `org_id` existe aussi ; la RLS est la ceinture en plus des bretelles —
mais seulement si le rôle Postgres qui exécute les requêtes n'est ni superutilisateur ni
BYPASSRLS, et que `FORCE ROW LEVEL SECURITY` est posé (sinon le propriétaire de la table
contourne aussi sa propre politique). Voir `docker-compose.dev01.yml` : le conteneur `api` se
connecte avec un rôle applicatif dédié (`synelia_app`, NOSUPERUSER NOBYPASSRLS), jamais avec le
superutilisateur `synelia` réservé à l'accès hors-ligne.
Sur SQLite (dev, Vercel sans Postgres) seule la couche applicative s'applique."""

from __future__ import annotations

from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

org_id_transaction: ContextVar[str | None] = ContextVar("org_id_transaction", default=None)

TABLES_TENANT = (
    "ressources",
    "travaux",
    "audit",
    "memberships",
    "invitations",
    "cles_api",
    "sessions_auth",
)


def brancher(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "begin")
    def _poser_org(conn) -> None:  # type: ignore[no-untyped-def]
        org = org_id_transaction.get()
        conn.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": org or ""})


def _sql_politique(table: str) -> str:
    return (
        f"CREATE POLICY {table}_org ON {table} USING ("
        f"  org_id IS NULL OR current_setting('app.org_id', true) = '' "
        f"  OR org_id = current_setting('app.org_id', true))"
    )


def sql_politiques() -> list[str]:
    """DDL complet des politiques RLS (Postgres), inconditionnel — conservé pour compatibilité ;
    préférer `politiques_manquantes(conn)` qui ne rejoue que ce qui manque réellement. **Changer
    le texte d'une politique existante** ne passe pas par ce module (un `CREATE POLICY` échoue
    si la politique existe déjà) : il faut la supprimer à la main, en tant que superutilisateur
    (`DROP POLICY <table>_org ON <table>`), puis redémarrer un processus pour qu'il la recrée."""
    ddl: list[str] = []
    for table in TABLES_TENANT:
        ddl += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            # Sans FORCE, le propriétaire de la table (le rôle applicatif lui-même) contourne
            # la RLS comme le ferait un superutilisateur — FORCE l'applique aussi à ce rôle,
            # seul un filet de sécurité contre un bug applicatif, pas contre le rôle admin
            # hors-ligne (superutilisateur `synelia`, jamais utilisé par l'appli en marche).
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {table}_org ON {table}",
            _sql_politique(table),
        ]
    return ddl


async def politiques_manquantes(conn: AsyncConnection) -> list[str]:
    """Comme `sql_politiques()`, mais lit l'état réel (`pg_class`, `pg_policies`) et ne renvoie
    que les ordres nécessaires — plus de `DROP POLICY` systématique. Sûr à rejouer à chaque boot
    de chaque processus (API, worker, relais SMTP) sous le verrou consultatif de
    `session.py::initialiser_schema`."""
    lignes = (
        await conn.execute(
            text(
                "SELECT c.relname AS table, c.relrowsecurity, c.relforcerowsecurity,"
                "       EXISTS(SELECT 1 FROM pg_policies p"
                "              WHERE p.tablename = c.relname AND p.policyname = c.relname || '_org')"
                "         AS a_politique"
                "  FROM pg_class c"
                " WHERE c.relname = ANY(:tables)"
            ),
            {"tables": list(TABLES_TENANT)},
        )
    ).mappings().all()
    ddl: list[str] = []
    for ligne in lignes:
        table = ligne["table"]
        if not ligne["relrowsecurity"]:
            ddl.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        if not ligne["relforcerowsecurity"]:
            ddl.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        if not ligne["a_politique"]:
            ddl.append(_sql_politique(table))
    return ddl
