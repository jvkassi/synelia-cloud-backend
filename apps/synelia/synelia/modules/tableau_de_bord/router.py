"""Tableau de bord : synthèse client, copilote (réponses déterministes), suggestions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel.dates import maintenant

from synelia.depot import Depot
from synelia.deps import Contexte, Ctx, exige
from synelia.modules.facturation import metrologie
from synelia.travaux import vers_contrat

router = APIRouter(prefix="/tableau-de-bord", tags=["Tableau de bord"])

COMPTEURS: dict[str, str] = {
    "espace": "espaces",
    "vm": "vms",
    "k8s_cluster": "clusters",
    "service_manage": "servicesManages",
    "application": "applications",
    "environnement": "environnements",
}


async def _compter(ctx: Contexte, type_: str) -> int:
    return await Depot(type_, m.Vm).compter(ctx)


async def _evenements(ctx: Contexte) -> list[dict[str, Any]]:
    lignes = list(
        (
            await ctx.session.execute(
                select(Travail)
                .where(Travail.org_id == ctx.org_id)
                .order_by(Travail.cree_le.desc())
                .limit(8)
            )
        ).scalars()
    )
    evts = []
    for t in lignes:
        evts.append(
            {
                "id": t.id,
                "ts": t.started_at,
                "gravite": "majeure"
                if t.statut == "failed"
                else ("info" if t.statut == "done" else "mineure"),
                "ressource": t.label,
                "message": t.label,
                "site": None,
            }
        )
    return evts


async def _travaux_en_cours(ctx: Contexte) -> list[dict[str, Any]]:
    lignes = list(
        (
            await ctx.session.execute(
                select(Travail)
                .where(Travail.org_id == ctx.org_id, Travail.statut.in_(["queued", "running"]))
                .order_by(Travail.cree_le.desc())
                .limit(20)
            )
        ).scalars()
    )
    return [vers_contrat(t) for t in lignes]


async def _synthese(ctx: Contexte) -> dict[str, Any]:
    compteurs = {champ: await _compter(ctx, type_) for type_, champ in COMPTEURS.items()}
    espaces = await Depot("espace", m.EspaceCloud).tous(ctx)
    quota = {
        "vcpu": sum(e.quota.vcpu for e in espaces),
        "ramGo": sum(e.quota.ramGo for e in espaces),
        "stockageTo": sum(e.quota.stockageTo for e in espaces),
    }
    usage = {
        "vcpu": sum(e.usage.vcpu for e in espaces),
        "ramGo": sum(e.usage.ramGo for e in espaces),
        "stockageTo": sum(e.usage.stockageTo for e in espaces),
    }
    cons = await metrologie.consommation(ctx, maintenant().strftime("%Y-%m"))
    tickets = await Depot("ticket", m.Ticket).tous(
        ctx, filtre=lambda t: t.statut not in {"resolu", "ferme"}
    )
    return {
        **compteurs,
        "siegesUtilises": None,
        "siegesSouscrits": None,
        "quota": quota,
        "usage": usage,
        "uptime30j": 99.9,
        "slaContractuel": 99.95,
        "depenseMois": int(cons["total"]),
        "previsionMois": int(cons["prevision"]),
        "depenseMoisPrecedent": int(cons["totalMoisPrecedent"]),
        "facturesEnAttente": None,
        "ticketsOuverts": len(tickets),
        "prochainRdv": None,
        "evenements": await _evenements(ctx),
        "travauxEnCours": await _travaux_en_cours(ctx),
    }


@router.get("", response_model=m.SyntheseClient, response_model_exclude_none=True)
async def obtenir_tableau_de_bord(
    ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True)),
) -> Any:
    return await _synthese(ctx)


router_copilote = APIRouter(prefix="/copilote", tags=["Tableau de bord"])

SUGGESTIONS = [
    "Combien de VMs mon organisation utilise-t-elle ?",
    "Comment créer un nouvel Espace Cloud ?",
    "Quel est mon niveau de quota restant ?",
]


@router_copilote.post("", response_model=m.ReponseCopilote, response_model_exclude_none=True)
async def interroger_copilote(corps: m.QuestionCopilote, ctx: Ctx) -> Any:
    q = (corps.question or "").lower()
    syn = await _synthese(ctx)
    if "vm" in q or "machine" in q:
        reponse = f"Votre organisation compte actuellement {syn['vms']} machine(s) virtuelle(s) sur {syn['espaces']} espace(s)."
        actions = [
            {
                "libelle": "Voir les machines virtuelles",
                "href": "/app/vms",
                "actionRbac": "org.dashboard.view",
            }
        ]
        sources = [{"titre": "Machine virtuelle", "url": "/docs/vm", "type": "documentation"}]
    elif "espace" in q or "espace cloud" in q:
        reponse = f"Vous disposez de {syn['espaces']} espace(s) Cloud. Pour en créer un, utilisez l'action dédiée."
        actions = [
            {
                "libelle": "Créer un espace",
                "href": "/app/espaces/nouveau",
                "actionRbac": "espace.create",
            }
        ]
        sources = [{"titre": "Espace Cloud", "url": "/docs/espace", "type": "documentation"}]
    elif "quota" in q or "ressource" in q:
        reponse = f"Quota : {syn['quota']['vcpu']} vCPU / {syn['quota']['ramGo']} Go RAM / {syn['quota']['stockageTo']} To disque. Utilisé : {syn['usage']['vcpu']} vCPU / {syn['usage']['ramGo']} Go / {syn['usage']['stockageTo']} To."
        actions = [
            {
                "libelle": "Voir les espaces",
                "href": "/app/espaces",
                "actionRbac": "org.dashboard.view",
            }
        ]
        sources = None
    elif "facturation" in q or "cout" in q or "prix" in q or "depense" in q:
        reponse = f"Vos dépenses du mois s'élèvent à {syn['depenseMois']} FCFA, avec une prévision de {syn['previsionMois']} FCFA."
        actions = [
            {
                "libelle": "Voir la facturation",
                "href": "/app/facturation",
                "actionRbac": "billing.view",
            }
        ]
        sources = [{"titre": "Facturation", "url": "/docs/facturation", "type": "documentation"}]
    else:
        reponse = "Je peux vous aider à piloter votre organisation : machines virtuelles, espaces, quotas, facturation et services managés."
        actions = None
        sources = None
    return {
        "reponse": reponse,
        "sources": sources,
        "actionsProposees": actions,
        "suggestions": SUGGESTIONS,
        "horsPerimetre": False,
    }


@router_copilote.get(
    "/suggestions",
    response_model=m.CopiloteSuggestionsGetResponse,
    response_model_exclude_none=True,
)
async def lister_suggestions_copilote(ctx: Ctx) -> Any:
    return SUGGESTIONS
