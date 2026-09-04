from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import or_, select
from synelia_contract import modeles as m
from synelia_db.modeles import Audit, Organisation
from synelia_kernel.dates import dans

from synelia.audit import journaliser
from synelia.deps import Contexte, Page, exige
from synelia.deps.pagination import filtrer_trier_paginer
from synelia.modules.audit import service
from synelia.travaux import demarrer_travail

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("", response_model=m.AuditGetResponse, response_model_exclude_none=True)
async def lister_evenements_audit(  # noqa: PLR0913, PLR0917
    page: Page,
    depuis: datetime | None = None,
    jusqua: datetime | None = None,
    acteur: str | None = None,
    action: str | None = None,
    cible: str | None = None,
    resultat: str | None = None,
    scopeType: str | None = None,  # noqa: N803
    ctx: Contexte = Depends(exige("audit.view", lecture=True)),
) -> Any:
    org_id = ctx.org_id
    if scopeType and scopeType not in ("org",):
        return filtrer_trier_paginer([], page)
    q = select(Audit).where(Audit.org_id == org_id)
    if depuis:
        q = q.where(Audit.date >= service.utc(depuis))
    if jusqua:
        q = q.where(Audit.date <= service.utc(jusqua))
    if acteur:
        q = q.where(or_(Audit.acteur_id == acteur, Audit.acteur.ilike(f"%{acteur}%")))
    if action:
        q = q.where(Audit.action.ilike(f"%{action}%"))
    if cible:
        q = q.where(
            or_(Audit.cible_id == cible, Audit.cible.ilike(f"%{cible}%"), Audit.cible_type == cible)
        )
    if resultat:
        if resultat in service.RESULTATS_INVERSE:
            q = q.where(Audit.resultat.in_(service.RESULTATS_INVERSE[resultat]))
        else:
            q = q.where(Audit.resultat.not_in(("succes", "ok", "refus", "refuse")))
    lignes = list((await ctx.session.execute(q.order_by(Audit.date.desc()))).scalars().all())
    org = await ctx.session.get(Organisation, org_id)
    noms = await service.noms_acteurs(ctx, lignes)
    evenements = [service.vers_contrat(a, org.nom if org else None, noms) for a in lignes]
    return filtrer_trier_paginer(
        evenements, page, champs_recherche=("action", "target", "detail", "acteur")
    )


@router.post(
    "/export",
    response_model=m.AuditExportPostResponse,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def exporter_audit(
    corps: m.AuditExportPostRequest, ctx: Contexte = Depends(exige("compliance.export"))
) -> Any:
    libelle = (
        f"{corps.depuis.date().isoformat()} → {corps.jusqua.date().isoformat()} ({corps.format})"
    )
    travail = await demarrer_travail(
        ctx,
        "audit.export",
        libelle,
        cible_type="audit",
        entree=corps.model_dump(mode="json"),
        etapes=[
            {"nom": "Sélectionner les événements de la période", "dureeS": 5},
            {"nom": f"Générer le fichier {corps.format.upper()}", "dureeS": 15},
            {
                "nom": "Signer l'empreinte" if corps.signature else "Calculer l'empreinte",
                "dureeS": 3,
            },
            {"nom": "Publier le lien de téléchargement", "dureeS": 2},
        ],
    )
    await journaliser(
        ctx,
        action="audit.export",
        cible_type="travail",
        cible_id=travail["id"],
        cible=libelle,
        details={"format": corps.format, "signature": bool(corps.signature)},
    )
    return {
        "travailId": travail["id"],
        "urlTelechargement": f"{ctx.reglages.url_publique}{ctx.reglages.prefixe_api}/audit/exports/{travail['id']}",
        "expire": dans(24 * 3600),
    }
