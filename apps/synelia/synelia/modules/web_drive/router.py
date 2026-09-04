"""Drive (Web Cloud) : activation, sièges, ouverture SSO."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, status
from synelia_contract import modeles as m
from synelia_kernel import erreurs
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id

from synelia.audit import journaliser
from synelia.deps import Contexte, Page, exige
from synelia.modules.web_drive import service
from synelia.modules.web_drive.service import depot, depot_siege
from synelia.travaux import demarrer_travail

router = APIRouter(prefix="/web/drive", tags=["Web Cloud — drive"])


def _nouveau(domaine: str, palier: str, sieges: int | None) -> m.Drive:
    p = service.palier(palier)
    return m.Drive(
        id=nouvel_id(),
        domaine=domaine,
        actif=False,
        palier=palier,
        solutionOSS="nextcloud",
        hote="cloud.synelia.cloud",
        sieges=m.Sieges(attribues=0, souscrits=sieges or p["sieges"]),
        quota=m.Quota1(utiliseGo=0.0, totalGo=100.0),
        partage=m.Partage(
            externeAutorise=True, motDePasseObligatoire=False, expirationJours=30, liensActifs=0
        ),
        versionsFichiers=m.VersionsFichiers(actif=True, retentionJours=30),
        corbeille=m.Corbeille(retentionJours=30, tailleGo=50.0),
        prixSiege=p["prixSiege"],
    )


@router.get("", response_model=m.WebDriveGetResponse, response_model_exclude_none=True)
async def lister_drives(
    page: Page,
    domaine: str | None = None,
    actif: bool | None = None,
    ctx: Contexte = Depends(exige(None)),
) -> Any:
    return await depot.lister(
        ctx,
        page,
        filtre=lambda e: (
            (not domaine or e.domaine == domaine) and (actif is None or e.actif == actif)
        ),
        tri_defaut="domaine",
    )


@router.post(
    "",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def activer_drive(
    corps: m.WebDrivePostRequest, ctx: Contexte = Depends(exige("marketplace.subscribe"))
) -> Any:
    await depot.exiger_nom_libre(ctx, corps.domaine)
    drive = _nouveau(corps.domaine, corps.palier, corps.sieges)
    await depot.creer(ctx, drive)
    await journaliser(
        ctx,
        action="web.drive.activation",
        cible_type="web_drive",
        cible_id=drive.id,
        cible=drive.domaine,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return await demarrer_travail(
        ctx,
        "web.drive.activate",
        drive.domaine,
        cible_type="web_drive",
        cible_id=drive.id,
        entree=corps.model_dump(mode="json"),
    )


@router.get("/{driveId}", response_model=m.Drive, response_model_exclude_none=True)
async def obtenir_drive(driveId: str, ctx: Contexte = Depends(exige(None))) -> Any:  # noqa: N803
    return await depot.obtenir(ctx, driveId)


@router.patch("/{driveId}", response_model=m.Drive, response_model_exclude_none=True)
async def modifier_drive(
    driveId: str,
    corps: m.WebDriveDriveIdPatchRequest,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Any:  # noqa: N803
    await depot.obtenir(ctx, driveId)
    modifs = {
        k: v for k, v in corps.model_dump(mode="json", exclude_unset=True).items() if v is not None
    }
    await depot.modifier(ctx, driveId, modifs)
    await journaliser(
        ctx,
        action="web.drive.modification",
        cible_type="web_drive",
        cible_id=driveId,
        details=modifs,
    )
    return await depot.obtenir(ctx, driveId)


@router.post(
    "/{driveId}/ouverture",
    response_model=m.OuvertureService,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def ouvrir_drive(driveId: str, ctx: Contexte = Depends(exige("service.open"))) -> Any:  # noqa: N803
    drive = await depot.obtenir(ctx, driveId)
    url = service.amont().ouvrir(utilisateur=ctx.principal.email if ctx.principal else None)
    await journaliser(
        ctx,
        action="web.drive.ouverture",
        cible_type="web_drive",
        cible_id=drive.id,
        cible=drive.domaine,
    )
    return m.OuvertureService(
        url=url, expire=maintenant() + timedelta(seconds=60), methode="redirection"
    )


@router.get("/{driveId}/sieges", response_model=list[m.Siege], response_model_exclude_none=True)
async def lister_sieges_drive(driveId: str, ctx: Contexte = Depends(exige(None))) -> Any:  # noqa: N803
    await depot.obtenir(ctx, driveId)
    return await depot_siege.tous(ctx, parent_id=driveId)


@router.post(
    "/{driveId}/sieges",
    response_model=m.Siege,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def attribuer_siege_drive(
    driveId: str, corps: m.SiegeAttribution, ctx: Contexte = Depends(exige("seat.assign"))
) -> Any:  # noqa: N803
    drive = await depot.obtenir(ctx, driveId)
    if any(s.userId == corps.userId for s in await depot_siege.tous(ctx, parent_id=driveId)):
        raise erreurs.conflit("Cet utilisateur a déjà un siège.", code="siege_deja_attribue")
    if drive.sieges.attribues >= drive.sieges.souscrits:
        raise erreurs.quota_depasse(
            "Le plan drive ne comprend pas plus de sièges.",
            detail=f"souscrits={drive.sieges.souscrits}",
        )
    siege = m.Siege(
        id=nouvel_id(),
        managedServiceId=driveId,
        userId=corps.userId,
        statut="actif",
        quotaUtilise=0.0,
        quotaTotal=corps.quotaTotal,
    )
    service.amont().attribuer_siege(corps.userId, corps.quotaTotal)
    await depot_siege.creer(ctx, siege, parent_id=driveId)
    await depot.modifier(
        ctx,
        driveId,
        {"sieges": {"attribues": drive.sieges.attribues + 1, "souscrits": drive.sieges.souscrits}},
    )
    await journaliser(
        ctx,
        action="web.drive.siege.attribution",
        cible_type="web_drive",
        cible_id=driveId,
        cible=corps.userId,
    )
    return siege
