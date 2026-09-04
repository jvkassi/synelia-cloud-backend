"""Cinder : volumes de stockage en bloc (création, attachement, extension, suppression)."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import nouvel_id


class BlockStorageSimule:
    def creer_volume(self, **kw: Any) -> dict[str, Any]:
        return {
            "id": f"vol-{nouvel_id()[:8]}",
            "statut": "available",
            "taille_go": kw.get("taille_go", 10),
        }

    def attacher(self, volume_id: str, vm_id: str, montage: str | None = None) -> None:
        return None

    def detacher(self, volume_id: str, vm_id: str) -> None:
        return None

    def etendre(self, volume_id: str, taille_go: int) -> None:
        return None

    def supprimer(self, volume_id: str) -> None:
        return None


class BlockStorageOpenStack(BlockStorageSimule):
    def _c(self):
        from synelia_openstack.fabrique import connexion

        return connexion()

    def creer_volume(self, **kw: Any) -> dict[str, Any]:
        c = self._c()
        v = c.block_storage.create_volume(
            size=kw.get("taille_go", 10),
            name=kw.get("nom"),
            volume_type=kw.get("classe"),
            encrypted=bool(kw.get("chiffre")),
        )
        v = c.block_storage.wait_for_status(v, "available", wait=600)
        return {"id": v.id, "statut": v.status, "taille_go": v.size}

    def attacher(self, volume_id: str, vm_id: str, montage: str | None = None) -> None:
        self._c().block_storage.attach_volume(volume_id, vm_id)

    def detacher(self, volume_id: str, vm_id: str) -> None:
        self._c().block_storage.detach_volume(volume_id)

    def etendre(self, volume_id: str, taille_go: int) -> None:
        self._c().block_storage.extend_volume(volume_id, taille_go)

    def supprimer(self, volume_id: str) -> None:
        self._c().block_storage.delete_volume(volume_id, ignore_missing=True)
