"""Amont messagerie (Stalwart) : domaines, boîtes, webmail SSO.

Paire `StalwartSimule` / `StalwartReel`. Le réel n'est appelé que si
`SYNELIA_STALWART_URL` est défini ; sinon le simulé répond instantanément."""

from __future__ import annotations

import os
from typing import Any

import httpx
from synelia_kernel import erreurs
from synelia_kernel.ids import nouvel_id

ENV_URL = "SYNELIA_STALWART_URL"


class StalwartSimule:
    def creer_domaine(self, domaine: str) -> None:
        return None

    def creer_boite(self, domaine: str, adresse: str, mot_de_passe: str | None) -> None:
        return None

    def maj_boite(self, domaine: str, adresse: str, **champs: Any) -> None:
        return None

    def supprimer_boite(self, domaine: str, adresse: str) -> None:
        return None

    def verifier_authentification(self, domaine: str) -> dict[str, Any]:
        return {
            "spf": "valide",
            "dkim": "valide",
            "dmarc": "v=DMARC1; p=none; rua=mailto:dmarc@synelia.cloud",
            "enregistrements": [
                {"type": "TXT", "nom": f"_dmarc.{domaine}", "valeur": "v=DMARC1; p=none"},
                {"type": "TXT", "nom": domaine, "valeur": "v=spf1 include:_spf.synelia.cloud ~all"},
            ],
        }

    def ouvrir_webmail(self, adresse: str | None) -> str:
        return f"https://webmail.synelia.cloud/?boite={adresse or ''}&jeton={nouvel_id()}"


class StalwartReel(StalwartSimule):
    def __init__(self) -> None:
        self.base = os.environ[ENV_URL]
        self._mettre_en_securite()

    def _mettre_en_securite(self) -> None:
        self.base = self.base.rstrip("/")

    def _get(self, chemin: str) -> httpx.Response:
        try:
            return httpx.get(f"{self.base}{chemin}", timeout=30)
        except httpx.HTTPError as exc:
            raise erreurs.amont_indisponible("stalwart", str(exc)) from exc

    def _post(self, chemin: str, json: dict[str, Any] | None = None) -> httpx.Response:
        try:
            return httpx.post(f"{self.base}{chemin}", json=json or {}, timeout=30)
        except httpx.HTTPError as exc:
            raise erreurs.amont_indisponible("stalwart", str(exc)) from exc

    def _parse(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise erreurs.amont_indisponible("stalwart", f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    def creer_domaine(self, domaine: str) -> None:
        self._parse(self._post(f"/admin/domaines/{domaine}"))

    def creer_boite(self, domaine: str, adresse: str, mot_de_passe: str | None) -> None:
        self._parse(
            self._post(
                f"/admin/account/address/{adresse}",
                {"domaine": domaine, "motDePasse": mot_de_passe},
            )
        )

    def maj_boite(self, domaine: str, adresse: str, **champs: Any) -> None:
        self._parse(self._post(f"/admin/account/address/{adresse}", {"domaine": domaine, **champs}))

    def supprimer_boite(self, domaine: str, adresse: str) -> None:
        self._parse(self._post(f"/admin/account/address/{adresse}/supprimer"))

    def verifier_authentification(self, domaine: str) -> dict[str, Any]:
        return self._parse(self._get(f"/admin/domaines/{domaine}/verification"))

    def ouvrir_webmail(self, adresse: str | None) -> str:
        r = self._post("/api/webmail/ouvrir", {"adresse": adresse})
        data = self._parse(r) or {}
        return data.get("url") or f"https://webmail.synelia.cloud/?jeton={nouvel_id()}"


def choisir_stalwart() -> StalwartSimule:
    if os.environ.get(ENV_URL):
        return StalwartReel()
    return StalwartSimule()
