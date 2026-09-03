"""Exécution d'un travail hors requête HTTP (worker Temporal, tâche de fond)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from synelia_db.modeles import Travail
from synelia_db.session import fabrique
from synelia_kernel.config import reglages

from synelia.deps.contexte import Contexte, Principal
from synelia.travaux import moteur


async def executer_depuis_worker(travail_id: str, depuis: int | None) -> str:
    async with fabrique()() as session:
        travail = await session.get(Travail, travail_id)
        if travail is None:
            return "introuvable"
        faux_request: Any = SimpleNamespace(headers={}, client=None, state=SimpleNamespace(correlation_id=travail.correlation_id or "-"))
        ctx = Contexte(
            request=faux_request,
            session=session,
            reglages=reglages(),
            correlation_id=travail.correlation_id or "-",
            principal=Principal(
                utilisateur_id=travail.demande_par,
                email="worker",
                nom="worker",
                org_id=travail.org_id,
                role="platform_operator",
                equipe=True,
                role_equipe="platform_operator",
            ),
        )
        if depuis is None:
            taches = travail.taches or []
            depuis = next((i for i, t in enumerate(taches) if t["statut"] == "failed"), 0)
            for t in taches[depuis:]:
                t["statut"] = "pending"
            travail.taches = list(taches)
        await moteur._executer(ctx, travail, depuis=depuis)
        await session.commit()
        return travail.statut
