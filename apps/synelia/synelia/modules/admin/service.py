"""Module admin (pilotage plateforme) : dépôts plateforme, agrégations inter-organisations, exécuteurs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from synelia_contract import modeles as m
from synelia_db.modeles import Ressource, Travail, Utilisateur
from synelia_kernel import erreurs
from synelia_kernel.dates import depuis_iso, maintenant
from synelia_kernel.ids import nouvel_id

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot_backend = Depot("backend", m.Backend, plateforme=True, libelle="Backend", champ_nom="code")
depot_placement = Depot("placement", m.Placement, plateforme=True, libelle="Placement")
depot_fenetre = Depot(
    "fenetre_patching",
    m.FenetrePatching,
    plateforme=True,
    libelle="Fenêtre de patching",
    champ_nom="libelle",
)
depot_lead = Depot("lead", m.Lead, plateforme=True, libelle="Lead", champ_nom="nom")
depot_campagne_maj = Depot(
    "campagne_maj",
    m.CampagneMaj,
    plateforme=True,
    libelle="Campagne de mise à jour",
    champ_nom="nom",
)
depot_campagne_migration = Depot(
    "campagne_migration",
    m.CampagneMigration,
    plateforme=True,
    libelle="Campagne de migration",
    champ_nom="nom",
)
depot_incident = Depot(
    "incident", m.Incident, plateforme=True, libelle="Incident", champ_nom="titre"
)
depot_statut_service = Depot(
    "statut_service", m.StatutService, plateforme=True, libelle="Service", champ_nom="nom"
)


def utc(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


async def lignes_type(ctx: Contexte, type_: str, org_id: str | None = None) -> list[Ressource]:
    q = select(Ressource).where(Ressource.type == type_)
    if org_id is not None:
        q = q.where(Ressource.org_id == org_id)
    q = q.order_by(Ressource.cree_le.desc())
    return list((await ctx.session.execute(q)).scalars().all())


async def amacer_backends(ctx: Contexte) -> list[m.Backend]:
    """Crée les backends par défaut si la table est vide (actif ABJ + maintenance GBM)."""
    existants = await depot_backend.tous(ctx)
    if existants:
        return existants
    base = [
        ("backend-abj", "openstack-abj", "ABJ", 24, "en_ligne", 1024, 8192, 1024),
        ("backend-gbm", "openstack-gbm", "GBM", 18, "maintenance", 768, 6144, 768),
    ]
    for id_, code, site, hosts, statut, vcpu, ram, stockage in base:
        await depot_backend.creer(
            ctx,
            m.Backend(
                id=id_,
                code=code,
                type="openstack",
                site=site,
                hosts=hosts,
                statut=statut,
                usage=m.Usage(vcpuPct=0, ramPct=0, stockagePct=0),
                capacite=m.Quota(vcpu=vcpu, ramGo=ram, stockageTo=stockage),
                souverain=True,
            ),
        )
    return await depot_backend.tous(ctx)


async def usage_plateforme(ctx: Contexte) -> dict[str, float]:
    """Consommation agrégée des machines `vm` à travers toutes les organisations."""
    vcpu = ram_go = disk_go = 0
    for r in await lignes_type(ctx, "vm"):
        vcpu += int(r.donnees.get("vcpu") or 0)
        ram_go += int(r.donnees.get("ramGo") or 0)
        disk_go += int(r.donnees.get("diskGo") or 0)
    return {
        "vcpu": vcpu,
        "ramGo": ram_go,
        "stockageTo": round(disk_go / 1024, 2),
    }


def _equipe(u: Utilisateur) -> dict[str, Any] | None:
    return u.equipe if isinstance(u.equipe, dict) and u.equipe.get("role") else None


async def membres_equipe(ctx: Contexte) -> list[Utilisateur]:
    tous = list((await ctx.session.execute(select(Utilisateur))).scalars().all())
    return [u for u in tous if _equipe(u)]


async def membre_equipe(ctx: Contexte, membreId: str) -> Utilisateur:  # noqa: N803
    for u in await membres_equipe(ctx):
        if u.id == membreId:
            return u
    raise erreurs.introuvable("Membre de l'équipe", membreId)


def elevation_contrat(e: dict[str, Any], membre: str | None = None) -> dict[str, Any]:
    role = e.get("role")
    expire = e.get("expire")
    accorde = e.get("accordePar")
    actif = bool(e.get("actif", True))
    if expire:
        actif = actif and depuis_iso(expire) > maintenant()
    duree = e.get("duree") or "4 h"
    out = {
        "id": e["id"],
        "qui": e.get("qui", ""),
        "quand": e.get("quand"),
        "duree": duree,
        "motif": e.get("motif", ""),
        "actif": actif,
        "membreId": membre,
        "role": role,
        "ticketId": e.get("ticketId"),
        "expire": expire,
        "accordePar": accorde,
        "actionsJournalisees": e.get("actionsJournalisees"),
    }
    return {k: v for k, v in out.items() if v is not None}


@executeur("admin.maj.lancement")
class ExecuteurMaj(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        campagne = await depot_campagne_maj.obtenir(ctx, travail.cible_id or "")
        await depot_campagne_maj.definir_statut(ctx, campagne.id, "terminee")


@executeur("admin.migration.lancement")
class ExecuteurMigration(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        campagne = await depot_campagne_migration.obtenir(ctx, travail.cible_id or "")
        await depot_campagne_migration.definir_statut(ctx, campagne.id, "terminee")


@executeur("admin.tests_restauration")
class ExecuteurTestsRestauration(Executeur):
    pass


@executeur("capacite.rebalance")
class ExecuteurRebalance(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        entree = travail.entree or {}
        espace_id = entree.get("espaceId")
        if espace_id:
            placements = entree.get("placements")
            if placements is not None:
                existants = await depot_placement.tous(
                    ctx, filtre=lambda p: p.espaceId == espace_id
                )
                for p in existants:
                    await depot_placement.supprimer(ctx, p.id)
                for pl in placements:
                    await depot_placement.creer(
                        ctx,
                        m.Placement(
                            id=nouvel_id(),
                            espaceId=espace_id,
                            backendId=pl["backendId"],
                            percent=pl["percent"],
                        ),
                    )
