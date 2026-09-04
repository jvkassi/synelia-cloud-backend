"""Swift/S3 : buckets d'objets et clés d'accès."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import jeton_opaque, nouvel_id


class ObjetSimule:
    def creer_bucket(self, **kw: Any) -> dict[str, Any]:
        return {"id": f"bucket-{nouvel_id()[:8]}", "taille_go": 0.0, "objets": 0}

    def usage(self, bucket_id: str) -> dict[str, Any]:
        return {"taille_go": 0.0, "objets": 0, "requetes": 0, "egress_go": 0.0}

    def supprimer_bucket(self, bucket_id: str) -> None:
        return None

    def creer_cle(self, nom: str, buckets: list[str] | None, droits: str) -> dict[str, str]:
        return {
            "access_key_id": f"AKIA{nouvel_id()[:16].upper()}",
            "secret_access_key": jeton_opaque(32),
            "endpoint": "https://obj.synelia.cloud",
        }

    def revoquer_cle(self, access_key_id: str) -> None:
        return None


class ObjetOpenStack(ObjetSimule):
    def _c(self):
        from synelia_openstack.fabrique import connexion

        return connexion()

    def creer_bucket(self, **kw: Any) -> dict[str, Any]:
        c = self._c()
        b = c.create_container(name=kw["nom"])
        return {"id": b.id, "taille_go": 0.0, "objets": 0}

    def usage(self, bucket_id: str) -> dict[str, Any]:
        c = self._c()
        cont = c.get_container(bucket_id)
        objects = list(c.objects(cont, limit=10000))
        total = sum((o.get("bytes") or 0) for o in objects)
        return {
            "taille_go": round(total / 2**30, 3),
            "objets": len(objects),
            "requetes": 0,
            "egress_go": 0.0,
        }

    def supprimer_bucket(self, bucket_id: str) -> None:
        self._c().delete_container(bucket_id, ignore_missing=True)

    def creer_cle(self, nom: str, buckets: list[str] | None, droits: str) -> dict[str, str]:
        return {
            "access_key_id": f"AKIA{nouvel_id()[:16].upper()}",
            "secret_access_key": jeton_opaque(32),
            "endpoint": "https://obj.synelia.cloud",
        }

    def revoquer_cle(self, access_key_id: str) -> None:
        return None
