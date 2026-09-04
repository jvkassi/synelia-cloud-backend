from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from synelia_contract import modeles as m

from synelia.depot import Depot
from synelia.deps import Contexte, Page, exige
from synelia.modules.modeles import service

router = APIRouter(prefix="/modeles", tags=["Modèles applicatifs"])

depot = Depot("modele_applicatif", m.ModeleApplicatif, plateforme=True)


@router.get("", response_model=m.ModelesGetResponse, response_model_exclude_none=True)
async def lister_modeles(
    page: Page,
    categorie: str | None = None,
    certifie: bool | None = None,
    populaire: bool | None = None,
    ctx: Contexte = Depends(exige(None)),
) -> Any:
    await service._semer(ctx)
    filtre = lambda mo: (  # noqa: E731
        (not categorie or mo.categorie == categorie)
        and (certifie is None or mo.certifie == certifie)
        and (populaire is None or mo.populaire == populaire)
    )
    return await depot.lister(ctx, page, filtre=filtre, tri_defaut="nom")


@router.get("/{slug}", response_model=m.ModeleApplicatif, response_model_exclude_none=True)
async def obtenir_modele(slug: str, ctx: Contexte = Depends(exige(None))) -> Any:
    return await service.obtenir(ctx, slug)


@router.post(
    "/{slug}/estimation", response_model=m.EstimationCout, response_model_exclude_none=True
)
async def estimer_modele(
    slug: str, corps: m.ModelesSlugEstimationPostRequest, ctx: Contexte = Depends(exige(None))
) -> Any:
    modele = await service.obtenir(ctx, slug)
    return service.estimer(modele, corps.ressources, corps.sieges)
