from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from synelia_contract import modeles as m
from synelia_kernel.ids import nouvel_id

from synelia.audit import journaliser
from synelia.deps import Contexte, Page, exige
from synelia.modules.conformite.service import (
    ETAPES_AUDIT,
    _corriger_anomalie,
    anomalies,
    attestations,
    rapports,
)
from synelia.travaux import demarrer_travail

router = APIRouter(tags=["Tableau de bord", "Audit"])


@router.get("/anomalies", response_model=m.AnomaliesGetResponse, response_model_exclude_none=True)
async def lister_anomalies(
    page: Page,
    gravite: str | None = None,
    statut: str | None = None,
    portee: str | None = None,
    ctx: Contexte = Depends(exige(None)),
) -> Any:
    return await anomalies.lister(
        ctx,
        page,
        filtre=lambda a: (
            (not gravite or a.gravite == gravite)
            and (not statut or a.statut == statut)
            and (not portee or portee in (a.portee.type, a.portee.libelle))
        ),
        tri_defaut="detecteeLe",
    )


@router.post(
    "/anomalies/{anomalieId}/correctif",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def traiter_anomalie(
    anomalieId: str, corps: m.DecisionAnomalie, ctx: Contexte = Depends(exige(None))
) -> Any:  # noqa: N803
    anomalie = await anomalies.obtenir(ctx, anomalieId)
    await journaliser(
        ctx,
        action="conformite.correctif",
        cible_type="anomalie",
        cible_id=anomalieId,
        cible=anomalie.titre,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return await demarrer_travail(
        ctx,
        "conformite.correctif",
        anomalie.titre,
        cible_type="anomalie",
        cible_id=anomalieId,
        entree=corps.model_dump(mode="json"),
        contexte={"changements": _corriger_anomalie(anomalie, corps)},
        etapes=[
            {"nom": "Analyser la cause", "dureeS": 3},
            {"nom": "Appliquer le correctif", "dureeS": 20},
            {"nom": "Vérifier et journaliser", "dureeS": 5},
        ],
    )


@router.get("/attestations", response_model=list[m.Attestation], response_model_exclude_none=True)
async def lister_attestations(
    type: str | None = None,
    periode: str | None = None,
    ctx: Contexte = Depends(exige("compliance.export", lecture=True)),
) -> Any:  # noqa: A002
    return await attestations.tous(
        ctx,
        filtre=lambda a: (not type or a.type == type) and (not periode or a.periode == periode),
    )


@router.post(
    "/attestations/{attestationId}",
    response_model=m.Attestation,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def generer_attestation(
    attestationId: str,
    corps: m.AttestationsAttestationIdPostRequest,
    ctx: Contexte = Depends(exige("compliance.export")),
) -> Any:  # noqa: N803
    attestation = await attestations.obtenir(ctx, attestationId)
    await demarrer_travail(
        ctx,
        "attestation.generate",
        attestation.titre,
        cible_type="attestation",
        cible_id=attestationId,
        entree=corps.model_dump(mode="json", exclude_none=True),
        etapes=ETAPES_AUDIT,
    )
    await journaliser(
        ctx,
        action="conformite.attestation",
        cible_type="attestation",
        cible_id=attestationId,
        cible=attestation.titre,
    )
    return await attestations.obtenir(ctx, attestationId)


@router.get(
    "/conformite/rapports",
    response_model=m.ConformiteRapportsGetResponse,
    response_model_exclude_none=True,
)
async def lister_rapports_conformite(
    referentiel: str | None = None,
    ctx: Contexte = Depends(exige("compliance.export", lecture=True)),
) -> Any:
    return await rapports.tous(
        ctx, filtre=lambda r: not referentiel or r.referentiel == referentiel
    )


@router.post(
    "/conformite/rapports",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def generer_rapport_conformite(
    corps: m.ConformiteRapportsPostRequest, ctx: Contexte = Depends(exige("compliance.export"))
) -> Any:
    rapport_id = nouvel_id()
    await journaliser(
        ctx,
        action="conformite.rapport",
        cible_type="rapport_conformite",
        cible_id=rapport_id,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return await demarrer_travail(
        ctx,
        "conformite.rapport",
        f"Conformité {corps.referentiel} — {corps.periode}",
        cible_type="rapport_conformite",
        cible_id=rapport_id,
        entree=corps.model_dump(mode="json", exclude_none=True),
        etapes=ETAPES_AUDIT,
    )
