from __future__ import annotations

from typing import Any

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel import erreurs
from synelia_openstack import fournisseur
from synelia_openstack.identite import IdentiteOpenStack, IdentiteSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot(
    "espace",
    m.EspaceCloud,
    libelle="Espace Cloud",
    champ_nom="code",
    champs_recherche=("code", "offreNom", "site"),
)


def amont() -> IdentiteSimule:
    return fournisseur(IdentiteSimule, IdentiteOpenStack)


async def usage(ctx: Contexte, espace_id: str) -> dict[str, float]:
    vms = await Depot("vm", m.Vm).tous(
        ctx, filtre=lambda v: v.espaceId == espace_id and v.statut != "error"
    )
    volumes = await Depot("volume", m.Volume).tous(
        ctx, filtre=lambda v: getattr(v, "espaceId", None) == espace_id
    )
    return {
        "vcpu": sum(v.vcpu for v in vms),
        "ramGo": sum(v.ramGo for v in vms),
        "stockageTo": round(
            (sum(v.diskGo for v in vms) + sum(getattr(v, "tailleGo", 0) or 0 for v in volumes))
            / 1024,
            2,
        ),
    }


async def verifier_quota(
    ctx: Contexte, espace_id: str, vcpu: int = 0, ram_go: int = 0, disk_go: int = 0
) -> m.EspaceCloud:
    e = await depot.obtenir(ctx, espace_id)
    u = await usage(ctx, espace_id)
    if (
        u["vcpu"] + vcpu > e.quota.vcpu
        or u["ramGo"] + ram_go > e.quota.ramGo
        or u["stockageTo"] + disk_go / 1024 > e.quota.stockageTo
    ):
        raise erreurs.quota_depasse(
            "Le quota de l'Espace Cloud est atteint.",
            detail=f"usage={u} quota={e.quota.model_dump()}",
        )
    return e


@executeur("espace.create")
class ExecuteurEspaceCreate(Executeur):
    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        e = await depot.obtenir(ctx, travail.cible_id or "")
        a = amont()
        c = dict(travail.contexte)
        if index == 0:
            return f"Quota réservé : {e.quota.vcpu} vCPU, {e.quota.ramGo} Go RAM"
        if index == 1:
            c["domaine_id"] = c.get("domaine_id") or a.creer_domaine(f"org-{e.orgId}")
            c["projet_id"] = a.creer_projet(
                c["domaine_id"], f"espace-{e.code}", "RegionOne" if e.site == "ABJ" else "GBM"
            )
            a.poser_quotas(c["projet_id"], e.quota.vcpu, e.quota.ramGo, e.quota.stockageTo)
        elif index == 2:
            c.update(a.creer_reseau(c["projet_id"], f"{e.code}-net", e.cidr))
        elif index == 3:
            ac = a.creer_application_credential(c["projet_id"])
            await depot.definir_secrets(
                ctx,
                e.id,
                {
                    "application_credential_id": ac["id"],
                    "application_credential_secret": ac["secret"],
                },
            )
        travail.contexte = c
        return None

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        pid = travail.contexte.get("projet_id")
        if pid:
            amont().supprimer_projet(pid)
        await depot.definir_statut(ctx, travail.cible_id or "", "suspendue")

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "active")


@executeur("espace.delete")
class ExecuteurEspaceDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        pid = travail.contexte.get("projet_id")
        if pid:
            amont().supprimer_projet(pid)
        await depot.supprimer(ctx, travail.cible_id or "", logique=True)


def consommation_vide(periode: str) -> dict[str, Any]:
    return {"periode": periode, "jours": [], "total": 0, "prevision": 0, "totalMoisPrecedent": 0}
