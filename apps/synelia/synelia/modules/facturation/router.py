"""Row de la facturation : estimation, consommation, factures, paiement, prépayé, SLA, souscriptions, devis."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from synelia_contract import modeles as m
from synelia_kernel import erreurs
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id

from synelia.audit import journaliser
from synelia.depot import Depot
from synelia.deps import Page, exige
from synelia.deps.contexte import Contexte
from synelia.modules.facturation import metrologie, service, tarification
from synelia.modules.facturation.service import crediter
from synelia.travaux import demarrer_travail

router = APIRouter(prefix="/facturation", tags=["Facturation"])

_RE_PERIODE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


@router.get("/consommation", response_model=m.Consommation, response_model_exclude_none=True)
async def obtenir_consommation(
    periode: str | None = None, ctx: Contexte = Depends(exige("invoice.view", lecture=True))
) -> Any:
    return await metrologie.consommation(ctx, periode or maintenant().strftime("%Y-%m"))


@router.post(
    "/consommation/export",
    response_model=m.FacturationConsommationExportPostResponse,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def exporter_consommation(
    corps: m.FacturationConsommationExportPostRequest,
    ctx: Contexte = Depends(exige("invoice.view", lecture=True)),
) -> Any:
    if not _RE_PERIODE.match(corps.periode or ""):
        raise erreurs.validation(
            "Periode invalide, attendu AAAA-MM.", {"periode": "Format attendu : AAAA-MM."}
        )
    await metrologie.consommation(ctx, corps.periode)
    travail = await demarrer_travail(
        ctx,
        "facturation.export",
        f"Export {corps.format} {corps.periode}",
        entree=corps.model_dump(mode="json"),
        etapes=[
            {"nom": "Générer le fichier", "dureeS": 3},
            {"nom": "Publier l'URL de téléchargement", "dureeS": 2},
        ],
    )
    return {"url": f"/v1/travaux/{travail['id']}/export", "expire": None}


@router.get(
    "/devis", response_model=m.FacturationDevisGetResponse, response_model_exclude_none=True
)
async def lister_devis(
    page: Page,
    statut: str | None = None,
    ctx: Contexte = Depends(exige("invoice.view", lecture=True)),
) -> Any:
    return await Depot("devis", m.Devis).lister(
        ctx, page, filtre=lambda d: not statut or d.statut == statut, tri_defaut="numero"
    )


@router.post(
    "/devis/{devisId}/acceptation", response_model=m.Devis, response_model_exclude_none=True
)
async def accepter_devis(devisId: str, ctx: Contexte = Depends(exige("payment.update"))) -> Any:  # noqa: N803
    depot = Depot("devis", m.Devis)
    devis = await depot.obtenir(ctx, devisId)
    if devis.statut != "envoye":
        raise erreurs.conflit(
            "Ce devis n'est plus en attente d'acceptation.", code="devis_non_accepte"
        )
    await depot.definir_statut(ctx, devisId, "accepte")
    offre = await Depot("offre", m.Offre, plateforme=True).trouver(ctx, devis.id)
    souscription = m.Souscription(
        id=nouvel_id(),
        orgId=ctx.org_id,
        cible=m.Cible1(
            type="offer",
            ref=offre.id if offre else devis.id,
            label=offre.nom if offre else devis.objet,
        ),
        quantite=1,
        prixApplique=devis.montant,
        debut=date.today(),
        periodicite="mensuelle",
    )
    await Depot("souscription", m.Souscription).creer(ctx, souscription)
    await journaliser(ctx, action="devis.acceptation", cible_type="devis", cible_id=devisId)
    return await depot.obtenir(ctx, devisId)


@router.post("/estimation", response_model=m.EstimationCout, response_model_exclude_none=True)
async def estimer_cout(corps: m.DemandeEstimation, ctx: Contexte = Depends(exige(None))) -> Any:
    return tarification.estimer(corps)


@router.get(
    "/factures", response_model=m.FacturationFacturesGetResponse, response_model_exclude_none=True
)
async def lister_factures(
    page: Page,
    statut: str | None = None,
    periode: str | None = None,
    devise: str | None = None,
    ctx: Contexte = Depends(exige("invoice.view", lecture=True)),
) -> Any:
    return await Depot("facture", m.Facture).lister(
        ctx,
        page,
        filtre=lambda f: (
            (not statut or f.statut == statut)
            and (not periode or f.periode == periode)
            and (not devise or f.devise == devise)
        ),
        tri_defaut="numero",
    )


@router.get("/factures/{factureId}", response_model=m.Facture, response_model_exclude_none=True)
async def obtenir_facture(
    factureId: str, ctx: Contexte = Depends(exige("invoice.view", lecture=True))
) -> Any:  # noqa: N803
    return await Depot("facture", m.Facture).obtenir(ctx, factureId)


@router.post(
    "/factures/{factureId}/paiement",
    response_model=m.FacturationFacturesFactureIdPaiementPostResponse,
    response_model_exclude_none=True,
)
async def payer_facture(
    factureId: str,
    corps: m.FacturationFacturesFactureIdPaiementPostRequest,
    ctx: Contexte = Depends(exige("payment.update")),
) -> Any:  # noqa: N803
    depot = Depot("facture", m.Facture)
    facture = await depot.obtenir(ctx, factureId)
    if facture.statut == "payee":
        raise erreurs.conflit("Cette facture est déjà payée.", code="facture_deja_payee")
    await crediter(ctx, ctx.org_id, f"Paiement facture {facture.numero}", facture.total)
    facture = await depot.definir_statut(ctx, factureId, "payee")
    await journaliser(ctx, action="facture.paiement", cible_type="facture", cible_id=factureId)
    return {"facture": facture, "urlRedirection": None, "statut": "payee"}


_PDF = "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R>>endobj\n4 0 obj<</Length 80>>stream\nBT /F1 14 Tf 60 780 Td (FACTURE {numero}) Tj 0 -20 Td (Total: {total} FCFA) Tj ET\nendstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


@router.get("/factures/{factureId}/pdf")
async def obtenir_pdf_facture(
    factureId: str, ctx: Contexte = Depends(exige("invoice.view", lecture=True))
) -> Response:  # noqa: N803
    facture = await Depot("facture", m.Facture).obtenir(ctx, factureId)
    pdf = _PDF.format(numero=facture.numero, total=facture.total).encode("latin-1")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{facture.numero}.pdf"'},
    )


@router.get("/moyens-paiement", response_model=list[m.MoyenPaiement])
async def lister_moyens_paiement(ctx: Contexte = Depends(exige("payment.update"))) -> Any:
    return await Depot("moyen_paiement", m.MoyenPaiement).tous(ctx)


@router.post(
    "/moyens-paiement",
    response_model=m.MoyenPaiement,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def ajouter_moyen_paiement(
    corps: m.MoyenPaiementCreation, ctx: Contexte = Depends(exige("payment.update"))
) -> Any:
    depot = Depot("moyen_paiement", m.MoyenPaiement)
    libelle = corps.libelle or corps.type.replace("_", " ").title()
    detail = None
    if corps.numero and len(corps.numero) >= 4:
        detail = f"•••• {corps.numero[-4:]}"
    moyen = m.MoyenPaiement(
        id=nouvel_id(),
        type=corps.type,
        libelle=libelle,
        detail=detail,
        defaut=bool(corps.defaut),
        expire=corps.expiration,
        statut="actif",
    )
    await depot.creer(ctx, moyen)
    await journaliser(
        ctx, action="moyen_paiement.creation", cible_type="moyen_paiement", cible_id=moyen.id
    )
    return moyen


@router.patch(
    "/moyens-paiement/{moyenId}", response_model=m.MoyenPaiement, response_model_exclude_none=True
)
async def modifier_moyen_paiement(
    moyenId: str,
    corps: m.FacturationMoyensPaiementMoyenIdPatchRequest,
    ctx: Contexte = Depends(exige("payment.update")),
) -> Any:  # noqa: N803
    depot = Depot("moyen_paiement", m.MoyenPaiement)
    if corps.defaut:
        for autre in await depot.tous(ctx):
            if autre.id != moyenId and autre.defaut:
                await depot.modifier(ctx, autre.id, {"defaut": False})
    m_ = await depot.modifier(ctx, moyenId, corps)
    return m_


@router.delete("/moyens-paiement/{moyenId}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_moyen_paiement(
    moyenId: str, ctx: Contexte = Depends(exige("payment.update"))
) -> Response:  # noqa: N803
    await Depot("moyen_paiement", m.MoyenPaiement).supprimer(ctx, moyenId, logique=True)
    await journaliser(
        ctx, action="moyen_paiement.suppression", cible_type="moyen_paiement", cible_id=moyenId
    )
    return Response(status_code=204)


@router.post(
    "/prepaye/rechargement",
    response_model=m.FacturationPrepayeRechargementPostResponse,
    response_model_exclude_none=True,
)
async def recharger_prepaye(
    corps: m.Rechargement, ctx: Contexte = Depends(exige("payment.update"))
) -> Any:
    if not (1 <= corps.montant <= 100_000_000_000):
        raise erreurs.validation(
            "Montant invalide.", {"montant": "Doit etre un entier positif raisonnable."}
        )
    await crediter(ctx, ctx.org_id, f"Rechargement prépayé {corps.montant} FCFA", corps.montant)
    solde = await service.solde_credit(ctx)
    return {"solde": solde, "urlRedirection": None, "statut": "credite"}


@router.get("/sla", response_model=m.FacturationSlaGetResponse, response_model_exclude_none=True)
async def obtenir_sla(ctx: Contexte = Depends(exige("invoice.view", lecture=True))) -> Any:
    return {
        "engagements": [
            m.EngagementSla(
                composant="compute",
                dispo=99.9,
                constate=99.95,
                reponseCritique=15,
                resolutionCritique=60,
            ),
            m.EngagementSla(
                composant="stockage",
                dispo=99.9,
                constate=99.98,
                reponseCritique=15,
                resolutionCritique=60,
            ),
            m.EngagementSla(
                composant="reseau",
                dispo=99.9,
                constate=99.92,
                reponseCritique=15,
                resolutionCritique=60,
            ),
        ],
        "credits": [],
    }


@router.post(
    "/sla/reclamations",
    response_model=m.AccuseReception,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def reclamer_credit_sla(
    corps: m.ReclamationCredit, ctx: Contexte = Depends(exige("invoice.view", lecture=True))
) -> Any:
    await crediter(ctx, ctx.org_id, f"Crédit SLA {corps.composant} {corps.periode}", 5000)
    ref = nouvel_id()
    await journaliser(
        ctx,
        action="sla.reclamation",
        cible_type="sla",
        cible_id=ref,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return {
        "reference": ref,
        "message": "Réclamation enregistrée, un crédit SLA de 5 000 FCFA a été appliqué.",
        "delaiReponseHeures": 48,
    }


@router.get(
    "/souscriptions",
    response_model=m.FacturationSouscriptionsGetResponse,
    response_model_exclude_none=True,
)
async def lister_souscriptions(
    page: Page,
    actives: bool | None = None,
    ctx: Contexte = Depends(exige("invoice.view", lecture=True)),
) -> Any:
    return await Depot("souscription", m.Souscription).lister(
        ctx,
        page,
        filtre=lambda s: actives is None or (s.fin is None if actives else s.fin is not None),
        tri_defaut="debut",
    )


@router.patch(
    "/souscriptions/{souscriptionId}",
    response_model=m.Souscription,
    response_model_exclude_none=True,
)
async def modifier_souscription(
    souscriptionId: str,
    corps: m.FacturationSouscriptionsSouscriptionIdPatchRequest,
    ctx: Contexte = Depends(exige("payment.update")),
) -> Any:  # noqa: N803
    return await Depot("souscription", m.Souscription).modifier(ctx, souscriptionId, corps)


@router.delete(
    "/souscriptions/{souscriptionId}",
    response_model=m.FacturationSouscriptionsSouscriptionIdDeleteResponse,
    response_model_exclude_none=True,
)
async def resilier_souscription(
    souscriptionId: str,
    confirmation: str | None = None,
    ctx: Contexte = Depends(exige("payment.update")),
) -> Any:  # noqa: N803
    depot = Depot("souscription", m.Souscription)
    s = await depot.obtenir(ctx, souscriptionId)
    if s.fin is not None:
        raise erreurs.conflit(
            "Cette souscription est déjà résiliée.", code="souscription_deja_resiliee"
        )
    fin = date.today().isoformat()
    await depot.modifier(ctx, souscriptionId, {"fin": fin})
    s = await depot.obtenir(ctx, souscriptionId)
    return {"souscription": s, "finEffet": fin}


@router.get("/ventilation", response_model=m.Ventilation, response_model_exclude_none=True)
async def obtenir_ventilation(
    axe: str = "espace",
    periode: str | None = None,
    ctx: Contexte = Depends(exige("invoice.view", lecture=True)),
) -> Any:
    vms = await Depot("vm", m.Vm).tous(ctx)
    lignes: dict[str, int] = {}
    for v in vms:
        if axe == "application":
            label = v.applicationNom or v.applicationId or "Général"
        elif axe == "site":
            label = v.site or "Général"
        else:
            label = v.espaceId or "Général"
        prix = tarification._prix_ressource(
            "vm", {"vcpu": v.vcpu, "ramGo": v.ramGo, "diskGo": v.diskGo}, 1
        )
        lignes[label] = lignes.get(label, 0) + prix
    total = sum(lignes.values())
    if not lignes:
        lignes["Général"] = 0
    partes = [
        m.Ligne2(label=k, montant=v, pct=round(v * 100 / total, 1) if total else 0)
        for k, v in lignes.items()
    ]
    return {"axe": axe, "lignes": partes, "total": total}
