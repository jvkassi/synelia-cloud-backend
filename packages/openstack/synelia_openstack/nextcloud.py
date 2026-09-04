"""Amont drive (Nextcloud) : instances, sièges, ouverture SSO.

Paire `NextcloudSimule` / `NextcloudReel`. Le réel n'est appelé que si
`SYNELIA_NEXTCLOUD_URL` est défini."""

from __future__ import annotations

import os
from typing import Any

import httpx
from synelia_kernel import erreurs
from synelia_kernel.ids import nouvel_id

ENV_URL = "SYNELIA_NEXTCLOUD_URL"


class NextcloudSimule:
    def activer(self, domaine: str, palier: str, sieges: int) -> None:
        return None

    def ouvrir(self, utilisateur: str | None) -> str:
        return f"https://cloud.synelia.cloud/apps/files/?sso={nouvel_id()}"

    def attribuer_siege(self, utilisateur_id: str, quota_total: float | None) -> None:
        return None

    def liberer_siege(self, utilisateur_id: str) -> None:
        return None


class NextcloudReel(NextcloudSimule):
    def __init__(self) -> None:
        self.base = os.environ[ENV_URL].rstrip("/")

    def _post(self, chemin: str, json: dict[str, Any] | None = None) -> httpx.Response:
        try:
            return httpx.post(f"{self.base}{chemin}", json=json or {}, timeout=30)
        except httpx.HTTPError as exc:
            raise erreurs.amont_indisponible("nextcloud", str(exc)) from exc

    def _check(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise erreurs.amont_indisponible("nextcloud", f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    def activer(self, domaine: str, palier: str, sieges: int) -> None:
        self._check(
            self._post("/instance", {"domaine": domaine, "palier": palier, "sieges": sieges})
        )

    def ouvrir(self, utilisateur: str | None) -> str:
        data = self._check(self._post("/sso/ouvrir", {"utilisateur": utilisateur})) or {}
        return data.get("url") or f"https://cloud.synelia.cloud/apps/files/?sso={nouvel_id()}"

    def attribuer_siege(self, utilisateur_id: str, quota_total: float | None) -> None:
        self._check(
            self._post(f"/utilisateurs/{utilisateur_id}/siege", {"quotaTotal": quota_total})
        )

    def liberer_siege(self, utilisateur_id: str) -> None:
        self._check(self._post(f"/utilisateurs/{utilisateur_id}/siege/liberer"))


def choisir_nextcloud() -> NextcloudSimule:
    if os.environ.get(ENV_URL):
        return NextcloudReel()
    return NextcloudSimule()
