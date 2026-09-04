from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import select
from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel import erreurs
from synelia_kernel.dates import depuis_iso

from synelia.deps import Ctx, Page
from synelia.deps.contexte import Contexte
from synelia.deps.pagination import filtrer_trier_paginer
from synelia.travaux import moteur, vers_contrat

router = APIRouter(prefix="/travaux", tags=["Travaux de provisioning"])


async def _travail(ctx: Contexte, travail_id: str) -> Travail:
    t = await ctx.session.get(Travail, travail_id)
    if t is None or (
        t.org_id != ctx.org_id_ou_none
        and not (ctx.principal and ctx.principal.est_admin_plateforme)
    ):
        raise erreurs.introuvable("Travail", travail_id)
    return t


@router.get("", response_model=m.TravauxGetResponse, response_model_exclude_none=True)
async def lister_travaux(
    ctx: Ctx,
    page: Page,
    statut: str | None = None,
    type: str | None = None,
    depuis: str | None = None,
) -> Any:  # noqa: A002
    q = select(Travail).where(Travail.org_id == ctx.org_id).order_by(Travail.started_at.desc())
    if statut:
        q = q.where(Travail.statut == statut)
    if type:
        q = q.where(Travail.type == type)
    if depuis:
        q = q.where(Travail.started_at >= depuis_iso(depuis))
    items = [vers_contrat(t) for t in (await ctx.session.execute(q)).scalars()]
    return filtrer_trier_paginer(items, page, champs_recherche=("label", "type"))


@router.get("/{travailId}", response_model=m.TravailProvisioning, response_model_exclude_none=True)
async def obtenir_travail(ctx: Ctx, travailId: str) -> Any:  # noqa: N803
    return vers_contrat(await _travail(ctx, travailId))


@router.post(
    "/{travailId}/relance",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def relancer_travail(ctx: Ctx, travailId: str) -> Any:  # noqa: N803
    return vers_contrat(await moteur.relancer(ctx, await _travail(ctx, travailId)))


@router.post(
    "/{travailId}/annulation",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def annuler_travail(ctx: Ctx, travailId: str) -> Any:  # noqa: N803
    return vers_contrat(await moteur.annuler(ctx, await _travail(ctx, travailId)))
