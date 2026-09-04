from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_openstack import fournisseur
from synelia_openstack.trove import TroveOpenStack, TroveSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot("base_managee", m.BaseManagee)

PORTS = {"postgresql": 5432, "mysql": 3306, "mariadb": 3306, "mongodb": 27017, "redis": 6379}


def amont() -> TroveSimule:
    return fournisseur(TroveSimule, TroveOpenStack)


@executeur("base.create")
class ExecuteurBaseCreate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "running")


@executeur("base.replica")
class ExecuteurBaseReplica(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        base = await depot.obtenir(ctx, travail.cible_id or "")
        await depot.remplacer(
            ctx,
            travail.cible_id or "",
            base.model_copy(
                update={"replicas": travail.contexte.get("replicas", base.replicas + 1)}
            ),
        )


@executeur("base.restore")
class ExecuteurBaseRestore(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "running")


@executeur("base.delete")
class ExecuteurBaseDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.supprimer(ctx, travail.cible_id or "", logique=True)
