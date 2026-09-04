"""VictoriaMetrics / VictoriaLogs : observabilité (journaux, métriques, liens de sortie).

Paire `VictoriaSimule` / `VictoriaReel`. En simulation, on renvoie des séries vides et un
lien prêt à l'emploi ; le réel n'est appelé que si l'URL VictoriaLogs est configurée."""

from __future__ import annotations

import os
from typing import Any

import httpx


class VictoriaSimule:
    def lien_logs(self, recherche: str | None = None) -> str:
        base = os.environ.get("SYNELIA_VICTORIALOGS_URL", "https://victorialogs.synelia.cloud")
        q = f"?query={recherche}" if recherche else ""
        return f"{base}/select/logsql/ui{q}"

    def lien_grafana(self, metrique: str | None = None) -> str | None:
        return None

    def lien_centreon(self) -> str | None:
        return None

    def requete_metriques(self, metrique: str, fenetre: str) -> list[dict[str, Any]]:
        return []

    def extrait_logs(
        self,
        ressource_id: str | None = None,
        niveau: str | None = None,
        depuis: str | None = None,
        recherche: str | None = None,
    ) -> list[dict[str, Any]]:
        return []


class VictoriaReel(VictoriaSimule):
    def extrait_logs(
        self,
        ressource_id: str | None = None,
        niveau: str | None = None,
        depuis: str | None = None,
        recherche: str | None = None,
    ) -> list[dict[str, Any]]:
        url = os.environ.get("SYNELIA_VICTORIALOGS_URL")
        if not url:
            return super().extrait_logs(ressource_id, niveau, depuis, recherche)
        params: dict[str, Any] = {}
        if ressource_id:
            params["_stream_fields"] = ressource_id
        if recherche:
            params["query"] = recherche
        r = httpx.get(f"{url}/select/logsql/query", params=params, timeout=5)
        r.raise_for_status()
        return r.json()

    def extrait_metriques(
        self, metrique: str, fenetre: str, ressource_id: str | None = None
    ) -> list[dict[str, Any]]:
        url = os.environ.get("SYNELIA_VICTORIAMETRICS_URL")
        if not url:
            return []
        r = httpx.get(
            f"{url}/api/v1/query_range", params={"query": metrique, "step": "300"}, timeout=5
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])
