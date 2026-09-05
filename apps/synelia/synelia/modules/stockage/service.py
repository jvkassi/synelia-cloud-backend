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


async def identifiants_espace(ctx: Contexte, espace_id: str) -> dict[str, str]:
    """Secrets (application credential, projet) de l'Espace Cloud propriétaire du volume."""
    from synelia.modules.espaces.service import depot as depot_espaces

    return await depot_espaces.secrets(ctx, espace_id)


async def volume_id_reel(ctx: Contexte, volume_id: str, travail: Travail | None = None) -> str:
    """Identifiant Cinder du volume : dans les secrets du volume (posé à la création), sinon le
    contexte du travail (même job), sinon l'identifiant plateforme (mode simulé)."""
    if travail and travail.contexte.get("volume_id"):
        return str(travail.contexte["volume_id"])
    try:
        sec = await depot_volume.secrets(ctx, volume_id)
    except Exception:  # noqa: BLE001
        sec = {}
    return str(sec.get("volume_id") or volume_id)


@executeur("volume.create")
class ExecuteurVolumeCreate(Executeur):
    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 0:
            vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
            secrets_espace = await identifiants_espace(ctx, vol.espaceId)
            v = amont_cinder().creer_volume(
                nom=vol.nom,
                taille_go=vol.tailleGo,
                classe=vol.classe,
                chiffre=vol.chiffre,
                identifiants=secrets_espace,
            )
            await depot_volume.definir_secrets(ctx, vol.id, {"volume_id": v["id"]})
            return f"Volume Cinder {v['id']} créé"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_volume.definir_statut(ctx, travail.cible_id or "", "disponible")

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
        secrets = await depot_volume.secrets(ctx, vol.id)
        vid = secrets.get("volume_id")
        if vid:
            secrets_espace = await identifiants_espace(ctx, vol.espaceId)
            amont_cinder().supprimer(vid, identifiants=secrets_espace)
        await depot_volume.definir_statut(ctx, travail.cible_id or "", "erreur")


@executeur("volume.attach")
class ExecuteurVolumeAttach(Executeur):
    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 0:
            vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
            vid = await volume_id_reel(ctx, vol.id, travail)
            from synelia.modules.vms.service import serveur_id

            sid = await serveur_id(ctx, str(travail.contexte.get("vm_id") or ""))
            secrets_espace = await identifiants_espace(ctx, vol.espaceId)
            amont_cinder().attacher(
                vid, sid, travail.contexte.get("montage"), identifiants=secrets_espace
            )
            return f"Volume {vid} attaché au serveur {sid}"
        return None

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
    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 1:
            vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
            vid = await volume_id_reel(ctx, vol.id, travail)
            from synelia.modules.vms.service import serveur_id

            sid = await serveur_id(ctx, str(travail.contexte.get("vm_id") or ""))
            secrets_espace = await identifiants_espace(ctx, vol.espaceId)
            amont_cinder().detacher(vid, sid, identifiants=secrets_espace)
            return f"Volume {vid} détaché du serveur {sid}"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
        await depot_volume.remplacer(
            ctx,
            travail.cible_id or "",
            vol.model_copy(update={"attachedTo": None, "attachedLabel": None, "montage": None}),
        )


@executeur("volume.extend")
class ExecuteurVolumeExtend(Executeur):
    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 0:
            vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
            vid = await volume_id_reel(ctx, vol.id, travail)
            taille_go = travail.contexte.get("taille_go")
            secrets_espace = await identifiants_espace(ctx, vol.espaceId)
            amont_cinder().etendre(vid, taille_go, identifiants=secrets_espace)
            return f"Volume {vid} étendu à {taille_go} Go"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        vol = await depot_volume.obtenir(ctx, travail.cible_id or "")
        await depot_volume.remplacer(
            ctx,
            travail.cible_id or "",
            vol.model_copy(update={"tailleGo": travail.contexte.get("taille_go")}),
        )
