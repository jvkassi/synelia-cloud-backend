from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from synelia_contract import modeles as m
from synelia_kernel import erreurs
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id

from synelia.audit import journaliser
from synelia.deps import Contexte, Page, exige, exiger_confirmation
from synelia.modules.espaces.service import verifier_quota
from synelia.modules.vms import service
from synelia.modules.vms.service import amont, depot, instantane_depot
from synelia.travaux import demarrer_travail

router = APIRouter(prefix="/vms", tags=["Machines virtuelles"])

_MATERIEL_DEFAUT = m.MateielVirtuel(scsiControllers=1, nics=1, usb=False, secureBoot=False)

_SERIES = [
    ("cpu", "%"),
    ("ram", "%"),
    ("disque", "Go"),
    ("reseau_entrant", "Mo/s"),
]


def _specs(corps: m.VmCreation) -> tuple[str | None, int, int, int]:
    flore = {g["id"]: g for g in amont().gabarits()}
    if corps.gabarit:
        g = flore.get(corps.gabarit)
        if not g:
            raise erreurs.validation(
                "Gabarit inconnu.", champs={"gabarit": "Identifiant inexistant."}
            )
        return corps.gabarit, g["vcpu"], g["ramGo"], g["diskGo"]
    if corps.vcpu is not None and corps.ramGo is not None and corps.diskGo is not None:
        return None, corps.vcpu, corps.ramGo, corps.diskGo
    raise erreurs.validation(
        "Indiquez un gabarit ou vcpu/ramGo/diskGo.",
        champs={"gabarit": "ou vcpu/ramGo/diskGo requis."},
    )


def _image_par_id(image_id: str) -> dict[str, Any]:
    images = {i["id"]: i for i in amont().images()}
    img = images.get(image_id)
    if not img:
        raise erreurs.validation(
            "Image système inconnue.", champs={"imageId": "Identifiant inexistant."}
        )
    return img


async def _vm(ctx: Contexte, vm_id: str) -> m.Vm:
    return await depot.obtenir(ctx, vm_id)


@router.get("", response_model=m.VmsGetResponse, response_model_exclude_none=True)
async def lister_vms(  # noqa: PLR0917
    page: Page,
    espaceId: str | None = None,
    site: str | None = None,
    statut: str | None = None,
    tag: str | None = None,
    applicationId: str | None = None,
    ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True)),
) -> Any:
    return await depot.lister(
        ctx,
        page,
        filtre=lambda v: (
            (not espaceId or v.espaceId == espaceId)
            and (not site or v.site == site)
            and (not statut or v.statut == statut)
            and (not tag or tag in (v.tags or []))
            and (not applicationId or v.applicationId == applicationId)
        ),
        tri_defaut="nom",
    )


@router.post(
    "",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def creer_vm(corps: m.VmCreation, ctx: Contexte = Depends(exige("vm.create_delete"))) -> Any:
    espace = await verifier_quota(
        ctx, corps.espaceId, corps.vcpu or 0, corps.ramGo or 0, corps.diskGo or 0
    )
    flavor, vcpu, ram_go, disk_go = _specs(corps)
    image = _image_par_id(corps.imageId)
    await depot.exiger_nom_libre(ctx, corps.nom, parent_id=corps.espaceId)
    vm = m.Vm(
        id=nouvel_id(),
        espaceId=corps.espaceId,
        nom=corps.nom,
        os=image["id"],
        vcpu=vcpu,
        ramGo=ram_go,
        diskGo=disk_go,
        ips=[],
        statut="creating",
        hardware=corps.hardware or _MATERIEL_DEFAUT,
        site=corps.site or espace.site,
        tags=corps.tags,
        flavor=flavor,
        backupPlanId=corps.backupPlanId,
    )
    await depot.creer(ctx, vm, parent_id=corps.espaceId)
    await journaliser(ctx, action="vm.creation", cible_type="vm", cible_id=vm.id, cible=vm.nom)
    return await demarrer_travail(
        ctx,
        "vm.create",
        vm.nom,
        cible_type="vm",
        cible_id=vm.id,
        entree=corps.model_dump(mode="json"),
    )


@router.get("/{vmId}", response_model=m.Vm, response_model_exclude_none=True)
async def obtenir_vm(
    vmId: str, ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True))
) -> Any:  # noqa: N803
    return await _vm(ctx, vmId)


@router.patch("/{vmId}", response_model=m.Vm, response_model_exclude_none=True)
async def modifier_vm(
    vmId: str, corps: m.VmModification, ctx: Contexte = Depends(exige("vm.create_delete"))
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    if corps.nom and corps.nom != vm.nom:
        await depot.exiger_nom_libre(ctx, corps.nom, parent_id=vm.espaceId)
    await depot.modifier(ctx, vmId, corps)
    await journaliser(
        ctx,
        action="vm.modification",
        cible_type="vm",
        cible_id=vmId,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return await _vm(ctx, vmId)


@router.delete(
    "/{vmId}",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def supprimer_vm(
    vmId: str, confirmation: str | None = None, ctx: Contexte = Depends(exige("vm.create_delete"))
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    exiger_confirmation(vm.nom, confirmation)
    await journaliser(ctx, action="vm.suppression", cible_type="vm", cible_id=vmId, cible=vm.nom)
    return await demarrer_travail(
        ctx,
        "vm.delete",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        etapes=[
            {"nom": "Arrêter la machine", "dureeS": 18},
            {"nom": "Supprimer les disques", "dureeS": 12},
            {"nom": "Libérer les adresses IP", "dureeS": 6},
        ],
    )


async def _controle_etat(ctx: Contexte, vm_id: str, sens: str) -> m.Vm:
    vm = await _vm(ctx, vm_id)
    deja = {("arret", "stopped"), ("demarrage", "running")}
    if sens == "redemarrage" and vm.statut != "running":
        raise erreurs.conflit(
            "On ne redémarre qu'une machine en cours d'exécution.", code="etat_incompatible"
        )
    if (sens, vm.statut) in deja:
        cible = {"arret": "arrêtée", "demarrage": "démarrée", "redemarrage": "redémarrée"}[sens]
        raise erreurs.conflit(f"La machine est déjà {cible}.", code="etat_deja_atteint")
    return vm


@router.post(
    "/{vmId}/arret",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def arreter_vm(
    vmId: str, corps: m.VmsVmIdArretPostRequest, ctx: Contexte = Depends(exige("vm.power"))
) -> Any:  # noqa: N803
    vm = await _controle_etat(ctx, vmId, "arret")
    await journaliser(ctx, action="vm.arret", cible_type="vm", cible_id=vmId, cible=vm.nom)
    return await demarrer_travail(
        ctx,
        "vm.power.stop",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        entree=corps.model_dump(mode="json"),
    )


@router.post(
    "/{vmId}/demarrage",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def demarrer_vm(
    vmId: str, corps: m.VmsVmIdDemarragePostRequest, ctx: Contexte = Depends(exige("vm.power"))
) -> Any:  # noqa: N803
    vm = await _controle_etat(ctx, vmId, "demarrage")
    await journaliser(ctx, action="vm.demarrage", cible_type="vm", cible_id=vmId, cible=vm.nom)
    return await demarrer_travail(
        ctx,
        "vm.power.start",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        entree=corps.model_dump(mode="json"),
    )


@router.post(
    "/{vmId}/redemarrage",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def redemarrer_vm(
    vmId: str, corps: m.VmsVmIdRedemarragePostRequest, ctx: Contexte = Depends(exige("vm.power"))
) -> Any:  # noqa: N803
    vm = await _controle_etat(ctx, vmId, "redemarrage")
    await journaliser(ctx, action="vm.redemarrage", cible_type="vm", cible_id=vmId, cible=vm.nom)
    return await demarrer_travail(
        ctx,
        "vm.power.reboot",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        entree=corps.model_dump(mode="json"),
    )


@router.post(
    "/{vmId}/console",
    response_model=m.ConsoleVm,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def ouvrir_console_vm(vmId: str, ctx: Contexte = Depends(exige("vm.power"))) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    url = amont().console(await service.serveur_id(ctx, vm.id))
    return m.ConsoleVm(url=url, protocole="vnc", expire=maintenant() + timedelta(hours=2))


@router.get("/{vmId}/journaux", response_model=m.ExtraitLogs, response_model_exclude_none=True)
async def obtenir_journaux_vm(
    vmId: str, niveau: str | None = None, ctx: Contexte = Depends(exige(None))
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    lignes = amont().journaux(await service.serveur_id(ctx, vm.id))
    extrait = [m.LigneLog(ts=maintenant(), niveau="INFO", source="vm", message=ln) for ln in lignes]
    return m.ExtraitLogs(lignes=extrait, tronque=len(extrait) >= 20)


@router.put(
    "/{vmId}/materiel",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def modifier_materiel_vm(
    vmId: str, corps: m.MateielVirtuel, ctx: Contexte = Depends(exige("vm.hardware.update"))
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    if corps.scsiControllers != vm.hardware.scsiControllers:
        raise erreurs.non_porte("La modification des contrôleurs SCSI n'est pas supportée à chaud.")
    await depot.modifier(ctx, vmId, {"hardware": corps.model_dump()})
    await journaliser(
        ctx, action="vm.materiel", cible_type="vm", cible_id=vmId, details=corps.model_dump()
    )
    return await demarrer_travail(
        ctx,
        "vm.hardware",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        etapes=[
            {"nom": "Appliquer la configuration matérielle", "dureeS": 12},
            {"nom": "Redémarrer si nécessaire", "dureeS": 18},
        ],
    )


@router.get(
    "/{vmId}/metriques",
    response_model=m.VmsVmIdMetriquesGetResponse,
    response_model_exclude_none=True,
)
async def obtenir_metriques_vm(
    vmId: str, fenetre: str | None = None, ctx: Contexte = Depends(exige(None))
) -> Any:  # noqa: N803
    await _vm(ctx, vmId)
    fen = fenetre if fenetre in ("24h", "7j", "30j") else "24h"
    series = [
        m.Serie(metrique=metrique, unite=unite, fenetre=fen, points=[])
        for metrique, unite in _SERIES
    ]
    return m.VmsVmIdMetriquesGetResponse(series=series)


@router.post(
    "/{vmId}/migration",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def migrer_vm(
    vmId: str,
    corps: m.VmsVmIdMigrationPostRequest,
    ctx: Contexte = Depends(exige("vm.hardware.update")),
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    if corps.site and corps.site != vm.site:
        raise erreurs.non_porte("La migration entre sites n'est pas supportée.")
    await journaliser(ctx, action="vm.migration", cible_type="vm", cible_id=vmId, cible=vm.nom)
    return await demarrer_travail(
        ctx,
        "vm.migrate",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        entree=corps.model_dump(mode="json"),
    )


@router.post(
    "/{vmId}/redimensionnement",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def redimensionner_vm(
    vmId: str, corps: m.VmRedimensionnement, ctx: Contexte = Depends(exige("vm.hardware.update"))
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    nouveau = {
        "vcpu": corps.vcpu if corps.vcpu is not None else vm.vcpu,
        "ramGo": corps.ramGo if corps.ramGo is not None else vm.ramGo,
        "diskGo": corps.diskGo if corps.diskGo is not None else vm.diskGo,
    }
    if nouveau["diskGo"] < vm.diskGo:
        raise erreurs.validation(
            "Un disque ne se réduit pas.", champs={"diskGo": "doit être ≥ à la taille actuelle."}
        )
    delta_vcpu = nouveau["vcpu"] - vm.vcpu
    delta_ram = nouveau["ramGo"] - vm.ramGo
    delta_disk = nouveau["diskGo"] - vm.diskGo
    await verifier_quota(
        ctx, vm.espaceId, max(0, delta_vcpu), max(0, delta_ram), max(0, delta_disk)
    )
    await journaliser(
        ctx, action="vm.redimensionnement", cible_type="vm", cible_id=vmId, details=nouveau
    )
    return await demarrer_travail(
        ctx, "vm.resize", vm.nom, cible_type="vm", cible_id=vmId, entree=nouveau
    )


@router.post(
    "/lot",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def creer_vms_en_lot(
    corps: m.VmLotCreation, ctx: Contexte = Depends(exige("vm.create_delete"))
) -> Any:
    total_vcpu = sum((mac.vcpu or 0) * (mac.quantite or 1) for mac in corps.machines)
    total_ram = sum((mac.ramGo or 0) * (mac.quantite or 1) for mac in corps.machines)
    total_disk = sum((mac.diskGo or 0) * (mac.quantite or 1) for mac in corps.machines)
    await verifier_quota(ctx, corps.espaceId, total_vcpu, total_ram, total_disk)
    images = {i["id"] for i in amont().images()}
    for mac in corps.machines:
        if mac.imageId not in images:
            raise erreurs.validation(
                "Image système inconnue.", champs={"imageId": "Identifiant inexistant."}
            )
    await journaliser(ctx, action="vm.compose", cible_type="espace", cible_id=corps.espaceId)
    return await demarrer_travail(
        ctx,
        "vm.compose",
        f"{len(corps.machines)} machines",
        cible_type="espace",
        cible_id=corps.espaceId,
        entree=corps.model_dump(mode="json"),
    )


@router.get(
    "/{vmId}/instantanes", response_model=list[m.InstantaneVm], response_model_exclude_none=True
)
async def lister_instantanes_vm(vmId: str, ctx: Contexte = Depends(exige(None))) -> Any:  # noqa: N803
    await _vm(ctx, vmId)
    return await instantane_depot.tous(ctx, parent_id=vmId)


@router.post(
    "/{vmId}/instantanes",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def creer_instantane_vm(
    vmId: str,
    corps: m.VmsVmIdInstantanesPostRequest,
    ctx: Contexte = Depends(exige("backup.plan.write")),
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    await journaliser(ctx, action="vm.instantane", cible_type="vm", cible_id=vmId, cible=vm.nom)
    return await demarrer_travail(
        ctx,
        "vm.snapshot",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        entree=corps.model_dump(mode="json"),
    )


@router.delete(
    "/{vmId}/instantanes/{instantaneId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def supprimer_instantane_vm(
    instantaneId: str, ctx: Contexte = Depends(exige("backup.plan.write"))
) -> Any:  # noqa: N803
    await instantane_depot.obtenir(ctx, instantaneId)
    await instantane_depot.supprimer(ctx, instantaneId, logique=False)
    return Response(status_code=204)


@router.post(
    "/{vmId}/instantanes/{instantaneId}",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def restaurer_instantane_vm(
    vmId: str,
    instantaneId: str,
    confirmation: str | None = None,
    ctx: Contexte = Depends(exige("backup.restore")),
) -> Any:  # noqa: N803
    vm = await _vm(ctx, vmId)
    inst = await instantane_depot.obtenir(ctx, instantaneId)
    exiger_confirmation(inst.nom, confirmation)
    await journaliser(
        ctx, action="vm.instantane_restauration", cible_type="vm", cible_id=vmId, cible=vm.nom
    )
    return await demarrer_travail(
        ctx,
        "vm.restore",
        vm.nom,
        cible_type="vm",
        cible_id=vmId,
        etapes=[
            {"nom": "Préparer la restauration", "dureeS": 20},
            {"nom": "Restaurer les volumes", "dureeS": 45},
            {"nom": "Redémarrer la machine", "dureeS": 25},
        ],
    )
