"""Amont applicatif des services managés (Stalwart, Nextcloud, n8n…).

Les opérateurs du catalogue sont des produits tiers ; le connecteur ne fait que
créer un sous-domaine Synelia et renseigner l'URL native de rebond. Réel = httpx
(seulement si `SYNELIA_SERVICES_BASE_URL` est défini), sinon simulation locale."""

from __future__ import annotations

import os
from typing import Any

import httpx


class ConnecteurServiceSimule:
    """Aucun amont : URL native plausible immédiatement."""

    def provisionner(self, slug: str, domaine: str, id8: str) -> dict[str, Any]:
        return {"domaine": domaine, "urlNative": f"https://{slug}-{id8}.apps.synelia.cloud"}

    def ouverture(self, slug: str, domaine: str) -> dict[str, Any]:
        return {"url": f"https://{slug}-{domaine}.app.synelia.cloud", "methode": "redirection"}


class ConnecteurServiceReel(ConnecteurServiceSimule):
    """httpx vers le gestionnaire de domaine / le fournisseur SaaS du catalogue."""

    _url = os.environ.get("SYNELIA_SERVICES_BASE_URL")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._url or "http://localhost")

    def provisionner(self, slug: str, domaine: str, id8: str) -> dict[str, Any]:
        if not self._url:
            return super().provisionner(slug, domaine, id8)
        r = httpx.post(
            f"{self._url}/provision", json={"slug": slug, "domaine": domaine, "id": id8}, timeout=30
        )
        r.raise_for_status()
        return r.json()

    def ouverture(self, slug: str, domaine: str) -> dict[str, Any]:
        if not self._url:
            return super().ouverture(slug, domaine)
        r = httpx.post(f"{self._url}/ouvrir", json={"slug": slug, "domaine": domaine}, timeout=30)
        r.raise_for_status()
        return r.json()


def connecteur() -> ConnecteurServiceSimule:
    from synelia_openstack import fournisseur

    return fournisseur(ConnecteurServiceSimule, ConnecteurServiceReel)


def service_amont() -> ConnecteurServiceSimule:
    return connecteur()
