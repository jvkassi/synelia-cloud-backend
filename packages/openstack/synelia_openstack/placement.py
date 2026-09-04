"""Placement Nova : répartition des ressources entre backends."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import nouvel_id


class PlacementSimule:
    """Aucun amont : renvoie un placement plausible, instantanément."""

    def replanifier(self, espace_id: str, affectations: list[dict[str, Any]]) -> dict[str, Any]:
        """Prend une liste `[{backend_id, percent}]`, renvoie un plan de migration réaliste."""
        plans = []
        for a in affectations:
            plans.append(
                {
                    "backend_id": a["backend_id"],
                    "pourcentage": a.get("percent", 0),
                    "machines": max(0, int(a.get("percent", 0) / 20)),
                    "migrations_chaud": max(0, int(a.get("percent", 0) / 40)),
                    "planifiees": max(0, int(a.get("percent", 0) / 30)),
                }
            )
        return {"plan_id": f"pl-{nouvel_id()[:8]}", "etapes": plans, "statut": "planifie"}


class PlacementOpenStack(PlacementSimule):
    """openstacksdk : aggregates + weight-bearing sur les pools d'hôtes."""

    def _conn(self, region: str | None = None):
        from synelia_openstack.fabrique import connexion

        return connexion(region)

    def replanifier(self, espace_id: str, affectations: list[dict[str, Any]]) -> dict[str, Any]:
        c = self._conn("RegionOne")
        zones = {}
        for agg in c.placement.aggregates():
            zones[agg.name] = agg.id
        plans = []
        for a in affectations:
            agg_id = zones.get(a["backend_id"])
            machine_count = int(a.get("percent", 0) / 20)
            c.placement.update_aggregate(
                agg_id,
                metadata={"weight": str(a.get("percent", 0))},
            ) if agg_id else None
            plans.append(
                {
                    "backend_id": a["backend_id"],
                    "pourcentage": a.get("percent", 0),
                    "machines": machine_count,
                    "migrations_chaud": max(0, min(machine_count, int(a.get("percent", 0) / 40))),
                    "planifiees": max(0, int(a.get("percent", 0) / 30)),
                }
            )
        return {"plan_id": f"pl-{nouvel_id()[:8]}", "etapes": plans, "statut": "planifie"}
