from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from synelia_contract import modeles as m
from synelia_kernel import erreurs
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id

from synelia.audit import journaliser
from synelia.deps import Contexte, Page, exige, exiger_confirmation
from synelia.modules.ia_agents import service
from synelia.modules.ia_agents.service import depot_agents, depot_modeles

router = APIRouter(tags=["IA — Agents"])

# ─── Catalogue de modèles (lecture ; POST réservé au support de nouveaux modèles) ──


@router.get("/ia/modeles", response_model=m.IaModelesGetResponse, response_model_exclude_none=True)
async def lister_modeles_ia(
    page: Page, ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True))
) -> Any:
    await service._semer_modeles(ctx)
    return await depot_modeles.lister(ctx, page, tri_defaut="nom")


@router.post(
    "/ia/modeles",
    response_model=m.ModeleIA,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def creer_modele_ia(corps: m.ModeleIACreation, ctx: Contexte = Depends(exige(None))) -> Any:
    await service._semer_modeles(ctx)
    donnees = corps.model_dump(exclude={"invocable", "statut"})
    modele = m.ModeleIA(
        id=corps.slug.replace("/", "-"),
        statut=corps.statut or "disponible",
        invocable=corps.invocable if corps.invocable is not None else False,
        **donnees,
    )
    return await depot_modeles.creer(ctx, modele, id_=modele.id)


@router.get(
    "/ia/modeles/{modeleId}", response_model=m.ModeleIA, response_model_exclude_none=True
)
async def obtenir_modele_ia(
    modeleId: str, ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True))
) -> Any:  # noqa: N803
    await service._semer_modeles(ctx)
    return await depot_modeles.obtenir(ctx, modeleId)


# ─── Agents ────────────────────────────────────────────────────────────


@router.get("/ia/agents", response_model=m.IaAgentsGetResponse, response_model_exclude_none=True)
async def lister_agents_ia(
    page: Page, ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True))
) -> Any:
    return await depot_agents.lister(ctx, page, tri_defaut="nom")


@router.post(
    "/ia/agents",
    response_model=m.AgentIA,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def creer_agent_ia(
    corps: m.AgentIACreation, ctx: Contexte = Depends(exige("ia.agent.write"))
) -> Any:
    modele = await service.obtenir_modele_par_slug(ctx, corps.modele)
    if modele is None:
        raise erreurs.validation(
            "Modèle IA inconnu.", champs={"modele": f"Aucun modèle avec le slug « {corps.modele} »."}
        )
    agent = m.AgentIA(
        id=nouvel_id(),
        nom=corps.nom,
        consigne=corps.consigne,
        espaceId=corps.espaceId,
        modele=corps.modele,
        temperature=corps.temperature if corps.temperature is not None else 0.7,
        topP=corps.topP if corps.topP is not None else 1,
        jetonsMax=corps.jetonsMax if corps.jetonsMax is not None else 1024,
        statut="brouillon",
        createdAt=maintenant(),
    )
    agent = await depot_agents.creer(ctx, agent)
    await journaliser(
        ctx, action="agent_ia.creation", cible_type="agent_ia", cible_id=agent.id, cible=agent.nom
    )
    return agent


@router.get("/ia/agents/{agentId}", response_model=m.AgentIA, response_model_exclude_none=True)
async def obtenir_agent_ia(
    agentId: str, ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True))
) -> Any:  # noqa: N803
    return await depot_agents.obtenir(ctx, agentId)


@router.patch("/ia/agents/{agentId}", response_model=m.AgentIA, response_model_exclude_none=True)
async def modifier_agent_ia(
    agentId: str, corps: m.AgentIAModification, ctx: Contexte = Depends(exige("ia.agent.write"))
) -> Any:  # noqa: N803
    if corps.modele and await service.obtenir_modele_par_slug(ctx, corps.modele) is None:
        raise erreurs.validation(
            "Modèle IA inconnu.", champs={"modele": f"Aucun modèle avec le slug « {corps.modele} »."}
        )
    await depot_agents.modifier(ctx, agentId, corps)
    agent = await depot_agents.obtenir(ctx, agentId)
    await journaliser(
        ctx,
        action="agent_ia.modification",
        cible_type="agent_ia",
        cible_id=agentId,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return agent


@router.delete("/ia/agents/{agentId}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_agent_ia(
    agentId: str,
    confirmation: str | None = None,
    ctx: Contexte = Depends(exige("ia.agent.write")),
) -> Response:  # noqa: N803
    agent = await depot_agents.obtenir(ctx, agentId)
    exiger_confirmation(agent.nom, confirmation)
    await depot_agents.supprimer(ctx, agentId)
    await journaliser(
        ctx, action="agent_ia.suppression", cible_type="agent_ia", cible_id=agentId, cible=agent.nom
    )
    return Response(status_code=204)


@router.post(
    "/ia/agents/{agentId}/invoquer",
    response_model=m.AgentInvocationResponse,
    response_model_exclude_none=True,
)
async def invoquer_agent(
    agentId: str, corps: m.AgentInvocationRequest, ctx: Contexte = Depends(exige(None))
) -> Any:  # noqa: N803
    agent = await depot_agents.obtenir(ctx, agentId)
    resultat = await service.invoquer(ctx, agent, corps.message)
    await journaliser(
        ctx,
        action="agent_ia.invocation",
        cible_type="agent_ia",
        cible_id=agentId,
        cible=agent.nom,
        details={"jetonsEntree": resultat["jetonsEntree"], "jetonsSortie": resultat["jetonsSortie"]},
    )
    return resultat
