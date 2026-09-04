from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_openstack import fournisseur
from synelia_openstack.block_storage import BlockStorageOpenStack, BlockStorageSimule
from synelia_openstack.objet import ObjetOpenStack, ObjetSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot_volume = Depot("volume", m.Volume)
depot_bucket = Depot("bucket", m.Bucket, champ_nom="nom")
depot_cle = Depot("cle_s3", m.CleS3)


def amont_cinder() -> BlockStorageSimule:
    return fournisseur(BlockStorageSimule, BlockStorageOpenStack)


def amont_objet() -> ObjetSimule:
    return fournisseur(ObjetSimule, ObjetOpenStack)


def iops_pour(classe: str) -> int:
    return {"nvme": 30000, "ssd": 6000, "hdd": 1200, "archive": 200}.get(classe, 1000)


@executeur("volume.create")
class ExecuteurVolumeCreate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_volume.definir_statut(ctx, travail.cible_id or "", "disponible")


@executeur("volume.attach")
class ExecuteurVolumeAttach(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
        await depot_volume.remplacer(
            ctx,
            travail.cible_id or "",
            vol.model_copy(
                update={
                    "attachedTo": travail.contexte.get("vm_id"),
                    "montage": travail.contexte.get("montage"),
                }
            ),
        )


@executeur("volume.detach")
class ExecuteurVolumeDetach(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
        await depot_volume.remplacer(
            ctx,
            travail.cible_id or "",
            vol.model_copy(update={"attachedTo": None, "attachedLabel": None, "montage": None}),
        )


@executeur("volume.extend")
class ExecuteurVolumeExtend(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
        await depot_volume.remplacer(
            ctx,
            travail.cible_id or "",
            vol.model_copy(update={"tailleGo": travail.contexte.get("taille_go")}),
        )
