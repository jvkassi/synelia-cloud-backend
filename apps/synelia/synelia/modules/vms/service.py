from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Organisation, Ressource, Travail, Utilisateur
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id
from synelia_openstack import fournisseur
from synelia_openstack.compute import ComputeOpenStack, ComputeSimule

from synelia.demo import peupleur
from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot("vm", m.Vm, champs_recherche=("nom", "os"))
instantane_depot = Depot(
    "vm_instantane", m.InstantaneVm, libelle="Instantané de machine", champ_nom="nom"
)


def amont() -> ComputeSimule:
    return fournisseur(ComputeSimule, ComputeOpenStack)


def ip_privee(vm: m.Vm) -> str:
    return f"10.{hash(vm.nom) % 250}.0.{hash(vm.os) % 250 + 2}"


def ip_publique(vm: m.Vm) -> str:
    return f"196.202.{hash(vm.nom) % 250}.{hash(vm.os) % 250 + 2}"


async def serveur_id(ctx: Contexte, vm_id: str, travail: Travail | None = None) -> str:
    """Identifiant Nova du serveur : dans les secrets de la VM (posé à la création), sinon le contexte du travail."""
    if travail and travail.contexte.get("serveur_id"):
        return str(travail.contexte["serveur_id"])
    try:
        sec = await depot.secrets(ctx, vm_id)
    except Exception:  # noqa: BLE001
        sec = {}
    return str(sec.get("serveur_id") or vm_id)


@executeur("vm.create")
class ExecuteurVmCreate(Executeur):
    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 1:
            vm = await depot.obtenir(ctx, travail.cible_id or "")
            entre = travail.entree or {}
            from synelia.modules.espaces.service import depot as depot_espaces

            secrets_espace = await depot_espaces.secrets(ctx, vm.espaceId)
            srv = amont().creer_serveur(
                nom=vm.nom,
                image_id=entre.get("imageId"),
                gabarit_id=entre.get("gabarit"),
                reseau_id=entre.get("reseauId") or secrets_espace.get("reseau_id"),
                identifiants=secrets_espace,
                org_id=ctx.org_id_ou_none,
                espace_id=vm.espaceId,
                cle_ssh=entre.get("cleSsh"),
                cloud_init=entre.get("cloudInit"),
            )
            c = dict(travail.contexte)
            c["serveur_id"] = srv["id"]
            await depot.definir_secrets(ctx, vm.id, {"serveur_id": srv["id"]})
            c["ip_privee"] = srv.get("ip_privee") or ip_privee(vm)
            travail.contexte = c
            return f"Serveur amont {srv['id']} créé"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        vm = await depot.obtenir(ctx, travail.cible_id or "")
        entre = travail.entree or {}
        ips = [m.Ip(adresse=travail.contexte.get("ip_privee") or ip_privee(vm), type="privee")]
        if entre.get("ipPubliqueDemandee"):
            ips.append(m.Ip(adresse=ip_publique(vm), type="publique"))
        await depot.modifier(
            ctx, travail.cible_id or "", {"statut": "running", "ips": [i.model_dump() for i in ips]}
        )

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        sid = await serveur_id(ctx, travail.cible_id or "", travail)
        if sid and sid != (travail.cible_id or ""):
            amont().supprimer_serveur(sid)
        await depot.definir_statut(ctx, travail.cible_id or "", "error")


@executeur("vm.compose")
class ExecuteurVmCompose(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        entre = travail.entree or {}
        espace_id = entre.get("espaceId")
        site = entre.get("site") or "ABJ"
        for mac in entre.get("machines") or []:
            quantite = mac.get("quantite") or 1
            for i in range(quantite):
                nom = mac["nom"] if quantite == 1 else f"{mac['nom']}{i + 1}"
                vm = m.Vm(
                    id=nouvel_id(),
                    espaceId=espace_id,
                    nom=nom,
                    os=mac["imageId"],
                    vcpu=mac["vcpu"],
                    ramGo=mac["ramGo"],
                    diskGo=mac["diskGo"],
                    ips=[m.Ip(adresse=ip_privee_mac(nom, mac["imageId"]), type="privee")],
                    statut="running",
                    hardware=m.MateielVirtuel(
                        scsiControllers=1, nics=mac.get("nics") or 1, usb=False, secureBoot=False
                    ),
                    site=site,
                )
                await depot.creer(ctx, vm, parent_id=espace_id)


def ip_privee_mac(nom: str, image_id: str) -> str:
    return f"10.{hash(nom) % 250}.0.{hash(image_id) % 250 + 2}"


@executeur("vm.power.start")
@executeur("vm.power.stop")
@executeur("vm.power.reboot")
class ExecuteurVmPower(Executeur):
    _ACTION = {
        "vm.power.start": "demarrage",
        "vm.power.stop": "arret",
        "vm.power.reboot": "redemarrage",
    }
    _STATUT = {
        "vm.power.stop": "stopped",
        "vm.power.start": "running",
        "vm.power.reboot": "running",
    }

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 0:
            vm = await depot.obtenir(ctx, travail.cible_id or "")
            amont().action(await serveur_id(ctx, vm.id, travail), self._ACTION[travail.type])
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", self._STATUT[travail.type])


@executeur("vm.resize")
class ExecuteurVmResize(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        entre = travail.entree or {}
        patch = {k: entre[k] for k in ("vcpu", "ramGo", "diskGo") if entre.get(k) is not None}
        if patch:
            await depot.modifier(ctx, travail.cible_id or "", patch)


@executeur("vm.migrate")
class ExecuteurVmMigrate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "running")


@executeur("vm.snapshot")
class ExecuteurVmSnapshot(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        vm = await depot.obtenir(ctx, travail.cible_id or "")
        entre = travail.entree or {}
        nom = entre.get("nom") or "snapshot"
        amont().instantane(await serveur_id(ctx, vm.id, travail), nom)
        inst = m.InstantaneVm(
            id=nouvel_id(),
            vmId=vm.id,
            nom=nom,
            cree=maintenant(),
            tailleGo=1.0,
            avecMemoire=bool(entre.get("avecMemoire")),
            description=entre.get("description"),
        )
        await instantane_depot.creer(ctx, inst, parent_id=vm.id)


@executeur("vm.hardware")
class ExecuteurVmHardware(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "running")


@executeur("vm.restore")
class ExecuteurVmRestore(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "running")


@executeur("vm.delete")
class ExecuteurVmDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        sid = await serveur_id(ctx, travail.cible_id or "", travail)
        if sid and sid != (travail.cible_id or ""):
            amont().supprimer_serveur(sid)
        await depot.supprimer(ctx, travail.cible_id or "", logique=True)


@peupleur
async def demo(session, org: Organisation, admin: Utilisateur) -> None:
    espace_abj = m.EspaceCloud(
        id="espace-demo-abj",
        orgId=org.id,
        code="demo-abj",
        offerId="offre-standard",
        offreNom="Espace Standard",
        site="ABJ",
        cidr="10.20.0.0/16",
        quota=m.Quota(vcpu=8, ramGo=32, stockageTo=1),
        usage=m.Quota(vcpu=0, ramGo=0, stockageTo=0),
        projets=1,
        statut="active",
        createdAt=maintenant(),
        dnsInterne="dns.synelia.cloud",
    )
    session.add(
        Ressource(
            id=espace_abj.id,
            org_id=org.id,
            type="espace",
            nom=espace_abj.code,
            statut=espace_abj.statut,
            donnees=espace_abj.model_dump(mode="json"),
        )
    )
    vms = [
        m.Vm(
            id="vm-demo-web",
            espaceId=espace_abj.id,
            nom="web-01",
            os="ubuntu-24.04",
            vcpu=2,
            ramGo=4,
            diskGo=40,
            ips=[m.Ip(adresse="10.20.1.10", type="privee")],
            statut="running",
            hardware=m.MateielVirtuel(scsiControllers=1, nics=1, usb=False, secureBoot=False),
            site="ABJ",
        ),
        m.Vm(
            id="vm-demo-db",
            espaceId=espace_abj.id,
            nom="db-01",
            os="debian-12",
            vcpu=1,
            ramGo=2,
            diskGo=20,
            ips=[m.Ip(adresse="10.20.1.11", type="privee")],
            statut="running",
            hardware=m.MateielVirtuel(scsiControllers=1, nics=1, usb=False, secureBoot=False),
            site="ABJ",
        ),
    ]
    for vm in vms:
        session.add(
            Ressource(
                id=vm.id,
                org_id=org.id,
                type="vm",
                nom=vm.nom,
                statut=vm.statut,
                parent_id=espace_abj.id,
                donnees=vm.model_dump(mode="json"),
            )
        )
