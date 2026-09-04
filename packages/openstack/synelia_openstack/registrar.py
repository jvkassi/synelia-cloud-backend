"""Registrar : disponibilité, commande, transfert, renouvellement, code-auth."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import jeton_opaque, nouvel_id

OCCUPES = {"google.com", "synelia.ci"}


class RegistrarSimule:
    def verifier(self, nom: str) -> bool:
        return nom.lower() not in OCCUPES

    def commander(self, nom: str, duree_annees: int) -> dict[str, Any]:
        return {
            "id": f"dom-{nouvel_id()[:8]}",
            "code_auth": jeton_opaque(12),
            "expiration": duree_annees,
        }

    def transferer(self, nom: str, code_auth: str) -> dict[str, Any]:
        return {"id": f"dom-{nouvel_id()[:8]}", "code_auth": jeton_opaque(12)}

    def renouveler(self, nom: str, duree_annees: int) -> None:
        return None

    def code_auth(self, nom: str) -> dict[str, Any]:
        return {"code": jeton_opaque(12), "expire_heures": 24}


class RegistrarOpenStack(RegistrarSimule):
    """Registrar partenaire via son API HTTP (variable d'environnement d'URL)."""
