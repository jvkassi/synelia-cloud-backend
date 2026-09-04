"""Observabilité : alertes, événements de supervision, journaux, métriques."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id

from synelia.depot import Depot
from synelia.deps.contexte import Contexte

depot = Depot(
    "regle_alerte", m.RegleAlerte, libelle="Règle d'alerte", champs_recherche=("cible", "metrique")
)


def regle_vers_modele(corps: m.RegleAlerteCreation, ctx: Contexte) -> m.RegleAlerte:
    return m.RegleAlerte(
        id=nouvel_id(),
        cible=corps.cible,
        metrique=corps.metrique,
        seuil=corps.seuil,
        canaux=corps.canaux,
        plage=corps.plage or "24/7",
        escalade=corps.escalade,
        actif=bool(corps.actif if corps.actif is not None else True),
    )


async def evenements(ctx: Contexte) -> list[dict[str, Any]]:
    q = (
        select(Travail)
        .where(Travail.org_id == ctx.org_id)
        .order_by(Travail.started_at.desc())
        .limit(8)
    )
    lignes = list((await ctx.session.execute(q)).scalars().all())
    out: list[dict[str, Any]] = []
    for t in lignes:
        echec = t.statut in {"failed", "rolled_back"}
        evenement = m.EvenementSupervision(
            id=t.id,
            ts=t.started_at,
            gravite="majeure" if echec else "info",
            ressource=t.label or t.type,
            message=t.erreur.get("message")
            if t.erreur
            else "Travail de provisioning terminé avec succès.",
            site=None,
        )
        out.append(evenement.model_dump(mode="json"))
    return out


def _nombre_points(fenetre: str) -> int:
    return {"24h": 24, "7j": 7, "30j": 30}.get(fenetre, 24)


def metriques(fenetre: str, metriques_req: list[str] | None) -> dict[str, Any]:
    fenetre = fenetre if fenetre in {"24h", "7j", "30j"} else "24h"
    metriques_choisies = metriques_req or ["cpu", "ram", "disque", "reseau_entrant", "rps"]
    pas = {"24h": 3600, "7j": 86400, "30j": 86400}[fenetre]
    npoints = _nombre_points(fenetre)
    debut = maintenant() - timedelta(hours={"24h": 24, "7j": 168, "30j": 720}[fenetre])
    series = []
    for metrique in metriques_choisies:
        points = []
        for i in range(npoints):
            points.append({"ts": debut + timedelta(seconds=pas * i), "valeur": 0.0})
        series.append(
            m.Serie(
                metrique=metrique,
                unite=_unite(metrique),
                fenetre=fenetre,  # type: ignore[arg-type]
                points=[m.PointSerie(**p) for p in points],
            )
        )
    tuiles = [
        m.Tuile(cle="cpu.moyen", libelle="CPU moyen", valeur=0.0, unite="%"),
        m.Tuile(cle="ram.utilisation", libelle="RAM utilisée", valeur=0.0, unite="%"),
        m.Tuile(cle="disque.occupation", libelle="Disque occupé", valeur=0.0, unite="%"),
    ]
    return {"tuiles": tuiles, "series": series, "liens": None}


def _unite(metrique: str) -> str:
    return {
        "cpu": "%",
        "ram": "%",
        "disque": "%",
        "reseau_entrant": "Mb/s",
        "rps": "req/s",
        "latence_p95": "ms",
        "erreurs_5xx": "err/min",
    }.get(metrique, "unité")
