"""Facturation : exécuteur du cycle mensuel, grand-livre (écritures), démo."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from synelia_db.modeles import Organisation, Ressource, Utilisateur
from synelia_kernel import argent
from synelia_kernel.ids import nouvel_id

from synelia.demo import peupleur
from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.modules.facturation import metrologie
from synelia.travaux import Executeur, executeur


class Ecriture(BaseModel):
    """Une écriture du grand-livre (crédit positif)."""

    id: str
    orgId: str
    libelle: str
    type: str
    montant: int


class CycleFacturation(BaseModel):
    id: str
    periode: str
    lanceLe: datetime
    statut: str
    organisations: int
    facturesEmises: int | None = None
    montantTotal: int | None = None
    echecs: list[dict[str, str]] | None = None


depot_ecriture = Depot("ecriture", Ecriture, champ_nom="libelle", libelle="Écriture")

depot_cycle = Depot(
    "cycle_facturation", CycleFacturation, champ_nom="periode", libelle="Cycle de facturation"
)


def mois_precedent(periode: str) -> str:
    annee, mois = (int(x) for x in periode.split("-")[:2])
    return (date(annee, mois, 1) - timedelta(days=1)).strftime("%Y-%m")


async def solde_credit(ctx: Contexte) -> int:
    ecritures = await depot_ecriture.tous(ctx, filtre=lambda e: e.type == "credit")
    return sum(e.montant for e in ecritures)


async def crediter(ctx: Contexte, org_id: str, libelle: str, montant: int) -> None:
    e = Ecriture(id=nouvel_id(), orgId=org_id, libelle=libelle, type="credit", montant=montant)
    r = Ressource(
        id=e.id, org_id=org_id, type="ecriture", nom=libelle, donnees=e.model_dump(mode="json")
    )
    ctx.session.add(r)
    await ctx.session.flush()


async def prochain_numero(ctx: Contexte, annee: int) -> str:
    """Numéro séquentiel `SYN-{année}-{n:06d}` par année, toutes organisations confondues."""
    q = (
        select(func.count())
        .select_from(Ressource)
        .where(Ressource.type == "facture", Ressource.supprime_le.is_(None))
    )
    total = int((await ctx.session.execute(q)).scalar_one())
    return f"SYN-{annee}-{total + 1:06d}"


async def construire_facture(ctx: Contexte, org_id: str, periode: str) -> dict[str, Any]:
    cons = await metrologie.consommation(ctx, periode)
    total = int(cons["total"])
    numero = await prochain_numero(ctx, int(periode.split("-", maxsplit=1)[0]))
    facture = {
        "id": nouvel_id(),
        "orgId": org_id,
        "numero": numero,
        "periode": periode,
        "lignes": [
            {
                "libelle": f"Consommation {periode}",
                "ref": periode,
                "quantite": 1,
                "pu": total,
                "total": total,
            }
        ],
        "sousTotal": total,
        "tvaPct": float(argent.TVA_CI_PCT),
        "total": argent.ttc(total),
        "devise": "XOF",
        "statut": "emise",
        "pdfUrl": f"/v1/facturation/factures/{nouvel_id()}/pdf",
        "echeance": (
            date(int(periode.split("-", maxsplit=1)[0]), int(periode.split("-")[1]), 1)
            + timedelta(days=31)
        ).isoformat(),
    }
    r = Ressource(
        id=facture["id"], org_id=org_id, type="facture", nom=numero, statut="emise", donnees=facture
    )
    ctx.session.add(r)
    await ctx.session.flush()
    return facture


@executeur("facturation.cycle")
class ExecuteurCycleFacturation(Executeur):
    async def terminer(self, ctx: Contexte, travail) -> None:
        periode = str(travail.contexte.get("periode") or "")
        org_ids = travail.contexte.get("org_ids") or None
        if not periode:
            return
        q = select(Organisation).where(Organisation.statut == "active")
        if org_ids:
            q = q.where(Organisation.id.in_(org_ids))
        orgs = (await ctx.session.execute(q)).scalars().all()
        previous = mois_precedent(periode)
        for org in orgs:
            await construire_facture(ctx, org.id, previous)


@peupleur
async def demo(session, org: Organisation, admin: Utilisateur) -> None:
    offres = [
        {
            "id": "offre-standard",
            "code": "standard",
            "nom": "Espace Standard",
            "categorie": "espace_cloud",
            "specs": "4 vCPU · 16 Go · 500 Go",
            "caracteristiques": ["IPv4 publique", "Sauvegarde quotidienne"],
            "prix": 45000,
            "populaire": True,
            "statut": "publiee",
            "souscriptionsActives": 3,
            "sla": "99.9",
            "surDevis": False,
        },
        {
            "id": "offre-performance",
            "code": "performance",
            "nom": "Espace Performance",
            "categorie": "espace_cloud",
            "specs": "8 vCPU · 32 Go · 1 To",
            "caracteristiques": ["IPv4 publique", "Sauvegarde horaire"],
            "prix": 90000,
            "statut": "publiee",
            "souscriptionsActives": 1,
            "sla": "99.95",
        },
        {
            "id": "offre-vm",
            "code": "vm-t2",
            "nom": "VM t2.micro",
            "categorie": "image_vm",
            "specs": "1 vCPU · 2 Go · 20 Go",
            "caracteristiques": [],
            "prix": 8000,
            "statut": "publiee",
            "souscriptionsActives": 0,
        },
    ]
    for o in offres:
        session.add(
            Ressource(
                id=o["id"], org_id=None, type="offre", nom=o["nom"], statut=o["statut"], donnees=o
            )
        )

    facture = {
        "id": "facture-demo",
        "orgId": org.id,
        "numero": "SYN-2026-000001",
        "periode": "2026-08",
        "lignes": [
            {
                "libelle": "Consommation Espace Standard",
                "ref": "2026-08",
                "quantite": 1,
                "pu": 45000,
                "total": 45000,
            }
        ],
        "sousTotal": 45000,
        "tvaPct": 18,
        "total": 53100,
        "devise": "XOF",
        "statut": "emise",
        "pdfUrl": "/v1/facturation/factures/facture-demo/pdf",
        "echeance": "2026-09-15",
    }
    session.add(
        Ressource(
            id=facture["id"],
            org_id=org.id,
            type="facture",
            nom=facture["numero"],
            statut=facture["statut"],
            donnees=facture,
        )
    )
