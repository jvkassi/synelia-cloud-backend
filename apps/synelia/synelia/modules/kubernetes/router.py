from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from synelia_contract import modeles as m
from synelia_kernel.ids import nouvel_id

from synelia.audit import journaliser
from synelia.depot import Depot
from synelia.deps import Contexte, Page, exige, exiger_confirmation
from synelia.modules.kubernetes.service import depot_cluster, depot_pool
from synelia.travaux import demarrer_travail

router = APIRouter(prefix="/kubernetes", tags=["Kubernetes"])

VERSIONS = ["1.31.4", "1.32.2", "1.33.0"]


def _version_detail(version: str, recommandee: bool = False) -> m.VersionK8s:
    return m.VersionK8s(version=version, statut="recommandee" if recommandee else "supportee")


@router.get("", response_model=m.KubernetesGetResponse, response_model_exclude_none=True)
async def lister_clusters(
    page: Page,
    espaceId: str | None = None,  # noqa: N803
    site: str | None = None,
    statut: str | None = None,
    ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True)),
) -> Any:
    return await depot_cluster.lister(
        ctx,
        page,
        filtre=lambda c: (
            (not espaceId or c.espaceId == espaceId)
            and (not site or c.site == site)
            and (not statut or c.statut == statut)
        ),
        tri_defaut="nom",
    )


@router.post(
    "",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def creer_cluster(
    corps: m.ClusterK8sCreation, ctx: Contexte = Depends(exige("vm.create_delete"))
) -> Any:
    await depot_cluster.exiger_nom_libre(ctx, corps.nom)
    espace = await Depot("espace", m.EspaceCloud).obtenir(ctx, corps.espaceId)
    cluster = m.ClusterK8s(
        id=nouvel_id(),
        espaceId=corps.espaceId,
        nom=corps.nom,
        version=corps.version,
        controlPlane=m.ControlPlane(
            mode=corps.controlPlane.mode, nodes=3 if corps.controlPlane.mode == "ha" else 1
        ),
        pools=corps.pools,
        modules=corps.modules or ["ingress-nginx"],
        statut="provisioning",
        site=corps.site,
        applicationId=getattr(espace, "applicationId", None),
    )
    await depot_cluster.creer(ctx, cluster)
    await journaliser(
        ctx, action="k8s.creation", cible_type="k8s_cluster", cible_id=cluster.id, cible=cluster.nom
    )
    return await demarrer_travail(
        ctx,
        "k8s.create",
        cluster.nom,
        cible_type="k8s_cluster",
        cible_id=cluster.id,
        entree=corps.model_dump(mode="json"),
    )


@router.get(
    "/modules", response_model=m.KubernetesModulesGetResponse, response_model_exclude_none=True
)
async def lister_modules_k8s(
    version: str | None = None, ctx: Contexte = Depends(exige(None))
) -> Any:  # noqa: PLE0118
    items = [
        m.KubernetesModulesGetResponseItem(
            slug="cni",
            nom="Réseau de pods",
            description="Réseau de pods (Calico)",
            categorie="réseau",
            version="3.28",
            recommande=True,
            coutMensuel=0,
        ),
        m.KubernetesModulesGetResponseItem(
            slug="ingress-nginx",
            nom="Ingress NGINX",
            description="Contrôleur d'entrée HTTP/S",
            categorie="réseau",
            version="1.11",
            recommande=True,
            coutMensuel=0,
        ),
        m.KubernetesModulesGetResponseItem(
            slug="monitoring",
            nom="Monitoring",
            description="Surveillance et alerting (Prometheus/Grafana)",
            categorie="observabilité",
            version="23.0",
            recommande=True,
            coutMensuel=0,
        ),
        m.KubernetesModulesGetResponseItem(
            slug="cert-manager",
            nom="cert-manager",
            description="Certificats TLS automatiques",
            categorie="sécurité",
            version="1.16",
            recommande=True,
            coutMensuel=0,
        ),
        m.KubernetesModulesGetResponseItem(
            slug="autoscaler",
            nom="Autoscaler HPA",
            description="Autoscaling horizontal de pods",
            categorie="échelle",
            version="1.30",
            recommande=False,
            coutMensuel=0,
        ),
    ]
    if version:
        items = [i for i in items if i.version == version]
    return items


@router.get("/versions", response_model=list[m.VersionK8s], response_model_exclude_none=True)
async def lister_versions_k8s(ctx: Contexte = Depends(exige(None))) -> Any:
    return [_version_detail(VERSIONS[0], recommandee=True)] + [
        _version_detail(v) for v in VERSIONS[1:]
    ]


@router.get("/{clusterId}", response_model=m.ClusterK8s, response_model_exclude_none=True)
async def obtenir_cluster(
    clusterId: str, ctx: Contexte = Depends(exige("org.dashboard.view", lecture=True))
) -> Any:  # noqa: N803
    return await depot_cluster.obtenir(ctx, clusterId)


@router.delete(
    "/{clusterId}",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def supprimer_cluster(
    clusterId: str,
    confirmation: str | None = None,
    ctx: Contexte = Depends(exige("vm.create_delete")),
) -> Any:  # noqa: N803
    cluster = await depot_cluster.obtenir(ctx, clusterId)
    exiger_confirmation(cluster.nom, confirmation)
    await journaliser(
        ctx,
        action="k8s.suppression",
        cible_type="k8s_cluster",
        cible_id=clusterId,
        cible=cluster.nom,
    )
    return await demarrer_travail(
        ctx,
        "k8s.delete",
        cluster.nom,
        cible_type="k8s_cluster",
        cible_id=clusterId,
        etapes=[
            {"nom": "Décommissionner les pools de workers", "dureeS": 180},
            {"nom": "Supprimer le cluster", "dureeS": 240},
        ],
    )


@router.get(
    "/{clusterId}/kubeconfig", response_model=m.Kubeconfig, response_model_exclude_none=True
)
async def obtenir_kubeconfig(
    clusterId: str, ctx: Contexte = Depends(exige("component.restart"))
) -> Any:  # noqa: N803
    cluster = await depot_cluster.obtenir(ctx, clusterId)
    contenu = (
        f"apiVersion: v1\nkind: Config\nclusters:\n- name: {cluster.nom}\n"
        f"  cluster:\n    server: https://{clusterId}.k8s.synelia.cloud:6443\n"
        f"contexts:\n- name: {cluster.nom}\n  context:\n    cluster: {cluster.nom}\n    user: admin\n"
        f"current-context: {cluster.nom}\nusers:\n- name: admin\n  user:\n    token: KUBECONFIG-TOKEN\n"
    )
    return m.Kubeconfig(contenu=contenu, expire=None, utilisateur="admin")


@router.post(
    "/{clusterId}/mise-a-jour",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def mettre_a_jour_cluster_k8s(
    clusterId: str,
    corps: m.KubernetesClusterIdMiseAJourPostRequest,
    ctx: Contexte = Depends(exige("vm.create_delete")),
) -> Any:  # noqa: N803
    cluster = await depot_cluster.obtenir(ctx, clusterId)
    await journaliser(
        ctx,
        action="k8s.mise_a_jour",
        cible_type="k8s_cluster",
        cible_id=clusterId,
        cible=cluster.nom,
        details=corps.model_dump(mode="json"),
    )
    return await demarrer_travail(
        ctx,
        "k8s.upgrade",
        cluster.nom,
        cible_type="k8s_cluster",
        cible_id=clusterId,
        entree=corps.model_dump(mode="json"),
    )


async def _pool(ctx: Contexte, cluster_id: str, pool_nom: str) -> m.PoolWorkers:
    for p in await depot_pool.tous(ctx, parent_id=cluster_id):
        if p.nom == pool_nom:
            return p
    from synelia_kernel import erreurs

    raise erreurs.introuvable("Pool de workers", pool_nom)


@router.put(
    "/{clusterId}/modules",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def modifier_modules_k8s(
    clusterId: str,
    corps: m.KubernetesClusterIdModulesPutRequest,
    ctx: Contexte = Depends(exige("vm.create_delete")),
) -> Any:  # noqa: N803
    cluster = await depot_cluster.obtenir(ctx, clusterId)
    await journaliser(
        ctx,
        action="k8s.modules",
        cible_type="k8s_cluster",
        cible_id=clusterId,
        cible=cluster.nom,
        details=corps.model_dump(mode="json"),
    )
    return await demarrer_travail(
        ctx,
        "k8s.modules",
        cluster.nom,
        cible_type="k8s_cluster",
        cible_id=clusterId,
        entree=corps.model_dump(mode="json"),
    )


@router.get(
    "/{clusterId}/pools", response_model=list[m.PoolWorkers], response_model_exclude_none=True
)
async def lister_pools_k8s(clusterId: str, ctx: Contexte = Depends(exige(None))) -> Any:  # noqa: N803
    await depot_cluster.obtenir(ctx, clusterId)
    return await depot_pool.tous(ctx, parent_id=clusterId)


@router.post(
    "/{clusterId}/pools",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def ajouter_pool_k8s(
    clusterId: str, corps: m.PoolWorkers, ctx: Contexte = Depends(exige("vm.create_delete"))
) -> Any:  # noqa: N803
    await depot_cluster.obtenir(ctx, clusterId)
    await depot_pool.exiger_nom_libre(ctx, corps.nom, parent_id=clusterId)
    await journaliser(
        ctx,
        action="k8s.pool.creation",
        cible_type="k8s_pool",
        cible_id=clusterId,
        cible=corps.nom,
        details=corps.model_dump(mode="json"),
    )
    return await demarrer_travail(
        ctx,
        "k8s.pool.create",
        corps.nom,
        cible_type="k8s_cluster",
        cible_id=clusterId,
        entree=corps.model_dump(mode="json"),
    )


@router.patch(
    "/{clusterId}/pools/{poolNom}",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def modifier_pool_k8s(
    clusterId: str,
    poolNom: str,
    corps: m.PoolWorkers,
    ctx: Contexte = Depends(exige("vm.create_delete")),
) -> Any:  # noqa: N803, PLE0118
    await depot_cluster.obtenir(ctx, clusterId)
    await _pool(ctx, clusterId, poolNom)
    await journaliser(
        ctx,
        action="k8s.pool.modification",
        cible_type="k8s_pool",
        cible_id=clusterId,
        cible=poolNom,
        details=corps.model_dump(mode="json"),
    )
    return await demarrer_travail(
        ctx,
        "k8s.pool.roll",
        poolNom,
        cible_type="k8s_cluster",
        cible_id=clusterId,
        entree=corps.model_dump(mode="json"),
        contexte={"nom": poolNom},
    )


@router.delete(
    "/{clusterId}/pools/{poolNom}",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def supprimer_pool_k8s(
    clusterId: str,
    poolNom: str,
    confirmation: str | None = None,
    ctx: Contexte = Depends(exige("vm.create_delete")),
) -> Any:  # noqa: N803, PLE0118
    await depot_cluster.obtenir(ctx, clusterId)
    await _pool(ctx, clusterId, poolNom)
    exiger_confirmation(poolNom, confirmation)
    await journaliser(
        ctx, action="k8s.pool.suppression", cible_type="k8s_pool", cible_id=clusterId, cible=poolNom
    )
    return await demarrer_travail(
        ctx,
        "k8s.pool.delete",
        poolNom,
        cible_type="k8s_cluster",
        cible_id=clusterId,
        contexte={"nom": poolNom},
    )
