"""Amont relais d'envoi SMTP (Postal) : relais, clés, messages, webhooks.

Paire `PostalSimule` / `PostalReel`. Le réel n'est appelé que si
`SYNELIA_POSTAL_URL` est défini."""

from __future__ import annotations

import os
from typing import Any

import httpx
from synelia_kernel import erreurs
from synelia_kernel.ids import jeton_opaque

ENV_URL = "SYNELIA_POSTAL_URL"


class PostalSimule:
    def activer(self, domaines: list[str], quota_jour: int | None) -> tuple[str, str]:
        return "smtp", jeton_opaque(18)

    def verifier(self, domaine: str) -> dict[str, Any]:
        return {"spf": "valide", "dkim": "valide", "dmarc": "valide"}

    def envoyer_test(self, de: str, destinataire: str) -> dict[str, Any]:
        return {"envoye": True, "code": "250", "detail": "Message d'essai remis."}

    def creer_cle(self) -> str:
        return jeton_opaque(24)

    def regenerer_identifiants(self) -> str:
        return jeton_opaque(18)


class PostalReel(PostalSimule):
    def __init__(self) -> None:
        self.base = os.environ[ENV_URL].rstrip("/")

    def _post(self, chemin: str, json: dict[str, Any] | None = None) -> httpx.Response:
        try:
            return httpx.post(f"{self.base}{chemin}", json=json or {}, timeout=30)
        except httpx.HTTPError as exc:
            raise erreurs.amont_indisponible("postal", str(exc)) from exc

    def _check(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise erreurs.amont_indisponible("postal", f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    def activer(self, domaines: list[str], quota_jour: int | None) -> tuple[str, str]:
        r = self._check(self._post("/relais", {"domaines": domaines, "quotaJour": quota_jour}))
        return (r or {}).get("identifiant", "smtp"), (r or {}).get("motDePasse", jeton_opaque(18))

    def verifier(self, domaine: str) -> dict[str, Any]:
        return self._check(self._post(f"/domaines/{domaine}/verifier"))

    def envoyer_test(self, de: str, destinataire: str) -> dict[str, Any]:
        return self._check(self._post("/test", {"de": de, "destinataire": destinataire}))

    def creer_cle(self) -> str:
        r = self._check(self._post("/cles"))
        return (r or {}).get("secret", jeton_opaque(24))

    def regenerer_identifiants(self) -> str:
        r = self._check(self._post("/identifiants/regenerer"))
        return (r or {}).get("motDePasse", jeton_opaque(18))


def choisir_postal() -> PostalSimule:
    if os.environ.get(ENV_URL):
        return PostalReel()
    return PostalSimule()
