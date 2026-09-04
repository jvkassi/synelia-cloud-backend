"""Amont ACME / autorité de certification : commande, validation DNS, renouvellement.

Paire `AcmeSimule` / `AcmeReel`. Le réel n'est appelé que si `SYNELIA_ACME_URL`
est défini ; sinon le simulé répond instantanément."""

from __future__ import annotations

import os
from typing import Any

import httpx
from synelia_kernel import erreurs
from synelia_kernel.ids import nouvel_id

ENV_URL = "SYNELIA_ACME_URL"


class AcmeSimule:
    def commander(self, hote: str, type_: str, validation: str) -> dict[str, Any]:
        return {
            "enregistrement": {
                "type": "TXT",
                "nom": f"_acme-challenge.{hote}",
                "valeur": f"tok-{nouvel_id()[:8]}",
            },
            "expirationJours": 90 if type_ == "letsencrypt" else 365,
        }

    def valider(self, hote: str) -> dict[str, Any]:
        return {
            "etat": "ok",
            "methode": "dns",
            "detail": "Enregistrement de validation publié et visible.",
        }

    def renouveler(self, hote: str, duree_annees: int) -> dict[str, Any]:
        return {"expirationJours": duree_annees * 365 if duree_annees else 90}

    def revoquer(self, hote: str) -> None:
        return None


class AcmeReel(AcmeSimule):
    def __init__(self) -> None:
        self.base = os.environ[ENV_URL].rstrip("/")

    def _post(self, chemin: str, json: dict[str, Any] | None = None) -> httpx.Response:
        try:
            return httpx.post(f"{self.base}{chemin}", json=json or {}, timeout=30)
        except httpx.HTTPError as exc:
            raise erreurs.amont_indisponible("acme", str(exc)) from exc

    def _check(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise erreurs.amont_indisponible("acme", f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    def commander(self, hote: str, type_: str, validation: str) -> dict[str, Any]:
        return self._check(
            self._post("/acme/commander", {"hote": hote, "type": type_, "validation": validation})
        )

    def valider(self, hote: str) -> dict[str, Any]:
        return self._check(self._post(f"/acme/{hote}/valider"))

    def renouveler(self, hote: str, duree_annees: int) -> dict[str, Any]:
        return self._check(self._post(f"/acme/{hote}/renouveler", {"dureeAnnees": duree_annees}))

    def revoquer(self, hote: str) -> None:
        self._check(self._post(f"/acme/{hote}/revoquer"))


def choisir_acme() -> AcmeSimule:
    if os.environ.get(ENV_URL):
        return AcmeReel()
    return AcmeSimule()
