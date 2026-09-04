"""Sauvegarde : plans, exécutions, points de restauration, restaurations, conformité 3-2-1."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id
from synelia_openstack import fournisseur
from synelia_openstack.backup import BackupOpenStack, BackupSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot(
    "plan_sauvegarde", m.PlanSauvegarde, libelle="Plan de sauvegarde", champs_recherche=("nom",)
)
points = Depot(
    "point_restauration",
    m.PointRestauration,
    libelle="Point de restauration",
    champs_recherche=("resourceNom", "planNom"),
)
restaurations = Depot(
    "restauration", m.Restauration, libelle="Restauration", champs_recherche=("ressourceNom",)
)


def amont() -> BackupSimule:
    return fournisseur(BackupSimule, BackupOpenStack)


def plan_vers_modele(
    corps: m.PlanSauvegardeCreation, ctx: Contexte, ressources: int
) -> m.PlanSauvegarde:
    return m.PlanSauvegarde(
        id=nouvel_id(),
        orgId=ctx.org_id,
        nom=corps.nom,
        scope=corps.scope,
        frequence=corps.frequence,
        mode=corps.mode,
        retentionJours=corps.retentionJours,
        immutable=bool(corps.immutable),
        destinations=corps.destinations,
        prochaineExecution=maintenant() + timedelta(hours=24),
        chiffrement=m.Chiffrement(
            mode=(corps.chiffrement.mode if corps.chiffrement else "synelia"),
            kmsRef=corps.chiffrement.kmsRef if corps.chiffrement else None,
        ),
        ressourcesProtegees=ressources,
        dernierResultat="ok",
    )


def _nouveau_point(ctx: Contexte, plan: m.PlanSauvegarde) -> m.PointRestauration:
    main = maintenant()
    destination = plan.destinations[0].type if plan.destinations else "local"
    ressource_type = plan.scope.type if plan.scope.type in {"vm", "ressource"} else "vm"
    return m.PointRestauration(
        id=nouvel_id(),
        planId=plan.id,
        planNom=plan.nom,
        resourceId=plan.scope.valeur,
        resourceNom=plan.scope.valeur,
        resourceType=ressource_type,
        date=main,
        tailleGo=round(2.4 + plan.ressourcesProtegees * 0.6, 1),
        type="complete" if plan.mode == "complete" else "incrementale",
        immuableJusquau=main + timedelta(days=plan.retentionJours) if plan.immutable else None,
        verifie=False,
        destination=destination,
        expiration=main + timedelta(days=plan.retentionJours),
    )


@executeur("backup.run")
class ExecuteurSauvegarde(Executeur):
    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        plan = await depot.obtenir(ctx, travail.cible_id or "")
        if index == 0:
            return f"Plan « {plan.nom} » validé, {plan.ressourcesProtegees} ressources couvertes."
        if index == 1:
            a = amont().executer_plan(plan.nom, plan.ressourcesProtegees)
            travail.contexte = {**dict(travail.contexte), "taille_go": a["taille_go"]}
            return f"Snapshot créé ({a['taille_go']} Go)."
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        plan = await depot.obtenir(ctx, travail.cible_id or "")
        point = _nouveau_point(ctx, plan)
        await points.creer(ctx, point)
        await depot.modifier(ctx, plan.id, {"dernierResultat": "ok"})


@executeur("backup.verify")
class ExecuteurVerification(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await points.modifier(ctx, travail.cible_id or "", {"verifie": True})


@executeur("backup.restore")
class ExecuteurRestauration(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        restauration_id = travail.cible_id or ""
        await restaurations.definir_statut(ctx, restauration_id, "done")


async def conformite(ctx: Contexte) -> list[dict[str, Any]]:
    plans = await depot.tous(ctx)
    pts = await points.tous(ctx)
    restaure = await restaurations.tous(ctx)
    lignes: list[dict[str, Any]] = []
    for plan in plans:
        pts_plan = [p for p in pts if p.planId == plan.id]
        destinations = {p.destination for p in pts_plan} | {d.type for d in plan.destinations}
        copies = len(pts_plan)
        supports = len(destinations)
        hors_site = any(d in {"autre_site", "immuable"} for d in destinations)
        if plan.dernierResultat == "echec":
            protection = "echec"
        elif (copies >= 3 or plan.mode == "complete") and supports >= 2 and hors_site:
            protection = "protegee"
        else:
            protection = "non_protegee"
        dernier_succes = next(
            (p.date for p in sorted(pts_plan, key=lambda x: x.date, reverse=True) if p.verifie),
            None,
        )
        test = [r for r in restaure if r.pointId in {p.id for p in pts_plan}]
        dernier_test = None
        if test:
            dernier_test = m.DernierTestRestauration(
                date=max(r.demandeeLe for r in test), succes=False, dureeMin=0
            )
        lignes.append(
            {
                "ressourceId": plan.scope.valeur,
                "ressourceNom": plan.scope.valeur,
                "type": plan.scope.type,
                "protection": protection,
                "dernierSucces": dernier_succes,
                "rpoConstateMin": int((maintenant() - dernier_succes).total_seconds() // 60)
                if dernier_succes
                else None,
                "regle321": m.Regle321(
                    copies=copies >= 3 or plan.mode == "complete",
                    supports=supports >= 2,
                    horsSite=hors_site,
                ),
                "dernierTestRestauration": dernier_test,
            }
        )
    return lignes
