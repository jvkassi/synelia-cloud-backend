"""Trove : bases de données managées."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import nouvel_id


class TroveSimule:
    def creer_base(self, **kw: Any) -> dict[str, Any]:
        return {
            "id": f"db-{nouvel_id()[:8]}",
            "host": f"db-{nouvel_id()[:8]}.int.synelia.cloud",
            "statut": "running",
        }

    def durable_identifiants(self, moteur: str) -> dict[str, str]:
        return {
            "utilisateur": f"synelia_{moteur}",
            "mot_de_passe_persistant": f"p-{nouvel_id()[:20]}",
        }

    def creer_identifiants(self, moteur: str) -> dict[str, str]:
        return {"utilisateur": f"synelia_{moteur}", "mot_de_passe": f"m-{nouvel_id()[:20]}"}

    def rotation_identifiants(self, base_id: str, delai_grace_min: int | None) -> dict[str, str]:
        return {"utilisateur": "synelia_rot", "mot_de_passe": f"r-{nouvel_id()[:20]}"}

    def ajouter_replica(self, base_id: str, site: str | None) -> None:
        return None

    def restaurer(self, base_id: str, instant: str, nom_cible: str) -> None:
        return None

    def supprimer_base(self, base_id: str) -> None:
        return None


class TroveOpenStack(TroveSimule):
    def _c(self):
        from synelia_openstack.fabrique import connexion

        return connexion()

    def creer_base(self, **kw: Any) -> dict[str, Any]:
        c = self._c()
        db = c.database.create_instance(
            name=kw["nom"],
            flavor=kw["palier"],
            databases=[{"name": kw["nom"]}],
            users=[{"name": kw["nom"], "password": kw.get("mot_de_passe", "changeme")}],
            datastore_type=kw["moteur"],
            datastore_version=kw["version"],
        )
        db = c.database.wait_for_status(db, "ACTIVE", wait=900)
        return {"id": db.id, "host": db.hostname, "statut": db.status}

    def durable_identifiants(self, moteur: str) -> dict[str, str]:
        return {
            "utilisateur": f"synelia_{moteur}",
            "mot_de_passe_persistant": f"p-{nouvel_id()[:20]}",
        }

    def creer_identifiants(self, moteur: str) -> dict[str, str]:
        return {"utilisateur": f"synelia_{moteur}", "mot_de_passe": f"m-{nouvel_id()[:20]}"}

    def rotation_identifiants(self, base_id: str, delai_grace_min: int | None) -> dict[str, str]:
        return {"utilisateur": "synelia_rot", "mot_de_passe": f"r-{nouvel_id()[:20]}"}

    def ajouter_replica(self, base_id: str, site: str | None) -> None:
        return None

    def restaurer(self, base_id: str, instant: str, nom_cible: str) -> None:
        return None

    def supprimer_base(self, base_id: str) -> None:
        self._c().database.delete_instance(base_id, ignore_missing=True)
