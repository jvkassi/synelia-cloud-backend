"""Charges de travail Kubernetes (namespaces/déploiements) sur le cluster Magnum du PaaS.

Même motif `Simule`/`Reel` que partout ailleurs dans `synelia_openstack`. Le réel ne
construit un `kubernetes.client.ApiClient` qu'à la demande, à partir du kubeconfig
renvoyé par Magnum (`GET /clusters/{cluster_id}/config`, la route qu'utilise aussi
`openstack coe cluster config`) — jamais de fichier kubeconfig persistant sur disque.
Le cluster ciblé est désigné par la variable d'environnement `SYNELIA_PAAS_CLUSTER_ID`
(id du cluster côté Magnum), lue à chaque appel : ce module ne modélise volontairement
qu'un seul cluster PaaS pour cette itération.
"""

from __future__ import annotations

import os
from typing import Any

from synelia_kernel import erreurs

ENV_CLUSTER_ID = "SYNELIA_PAAS_CLUSTER_ID"


class K8sWorkloadSimule:
    """Aucun cluster réel : simule namespaces et déploiements, instantanément."""

    def creer_namespace(self, nom: str) -> None:
        return None

    def supprimer_namespace(self, nom: str) -> None:
        return None

    def appliquer_deployment(
        self,
        namespace: str,
        nom: str,
        image: str,
        *,
        replicas: int = 1,
        env: dict[str, str] | None = None,
        ports: list[int] | None = None,
    ) -> None:
        return None

    def supprimer_deployment(self, namespace: str, nom: str) -> None:
        return None


class K8sWorkloadReel(K8sWorkloadSimule):
    """`kubernetes-client` vers le cluster Magnum désigné par `SYNELIA_PAAS_CLUSTER_ID`."""

    def _cluster_id(self) -> str:
        cluster_id = os.environ.get(ENV_CLUSTER_ID)
        if not cluster_id:
            raise erreurs.amont_indisponible(
                "kubernetes", f"{ENV_CLUSTER_ID} non configuré : aucun cluster PaaS ciblé."
            )
        return cluster_id

    def _kubeconfig(self, cluster_id: str) -> dict[str, Any]:
        import yaml

        from synelia_openstack.fabrique import connexion

        c = connexion()
        # openstacksdk n'expose pas (encore) de méthode dédiée pour cette route Magnum :
        # on appelle l'endpoint brut, identique à celui qu'utilise `openstack coe cluster config`.
        reponse = c.container_infra.get(f"/clusters/{cluster_id}/config", params={"dir": "."})
        reponse.raise_for_status()
        return yaml.safe_load(reponse.json()["config"])

    def _api_client(self) -> Any:
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config

        kubeconfig = self._kubeconfig(self._cluster_id())
        configuration = k8s_client.Configuration()
        k8s_config.load_kube_config_from_dict(
            kubeconfig, client_configuration=configuration, persist_config=False
        )
        return k8s_client.ApiClient(configuration)

    def creer_namespace(self, nom: str) -> None:
        from kubernetes import client as k8s_client

        api = k8s_client.CoreV1Api(self._api_client())
        try:
            api.create_namespace(
                k8s_client.V1Namespace(metadata=k8s_client.V1ObjectMeta(name=nom))
            )
        except k8s_client.exceptions.ApiException as exc:
            if exc.status != 409:  # déjà présent : idempotent
                raise erreurs.amont_indisponible("kubernetes", str(exc)) from exc

    def supprimer_namespace(self, nom: str) -> None:
        from kubernetes import client as k8s_client

        api = k8s_client.CoreV1Api(self._api_client())
        try:
            api.delete_namespace(nom)
        except k8s_client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise erreurs.amont_indisponible("kubernetes", str(exc)) from exc

    def appliquer_deployment(
        self,
        namespace: str,
        nom: str,
        image: str,
        *,
        replicas: int = 1,
        env: dict[str, str] | None = None,
        ports: list[int] | None = None,
    ) -> None:
        from kubernetes import client as k8s_client

        api_client = self._api_client()
        ports = ports or [8080]
        conteneur = k8s_client.V1Container(
            name=nom,
            image=image,
            env=[k8s_client.V1EnvVar(name=k, value=v) for k, v in (env or {}).items()],
            ports=[k8s_client.V1ContainerPort(container_port=p) for p in ports],
        )
        gabarit = k8s_client.V1PodTemplateSpec(
            metadata=k8s_client.V1ObjectMeta(labels={"app": nom}),
            spec=k8s_client.V1PodSpec(containers=[conteneur]),
        )
        spec = k8s_client.V1DeploymentSpec(
            replicas=replicas,
            selector=k8s_client.V1LabelSelector(match_labels={"app": nom}),
            template=gabarit,
        )
        deployment = k8s_client.V1Deployment(
            metadata=k8s_client.V1ObjectMeta(name=nom, namespace=namespace), spec=spec
        )
        apps = k8s_client.AppsV1Api(api_client)
        try:
            apps.create_namespaced_deployment(namespace, deployment)
        except k8s_client.exceptions.ApiException as exc:
            if exc.status == 409:
                apps.replace_namespaced_deployment(nom, namespace, deployment)
            else:
                raise erreurs.amont_indisponible("kubernetes", str(exc)) from exc

        service = k8s_client.V1Service(
            metadata=k8s_client.V1ObjectMeta(name=nom, namespace=namespace),
            spec=k8s_client.V1ServiceSpec(
                selector={"app": nom},
                type="ClusterIP",
                ports=[
                    k8s_client.V1ServicePort(port=p, target_port=p, name=f"port-{p}")
                    for p in ports
                ],
            ),
        )
        core = k8s_client.CoreV1Api(api_client)
        try:
            core.create_namespaced_service(namespace, service)
        except k8s_client.exceptions.ApiException as exc:
            if exc.status == 409:
                core.replace_namespaced_service(nom, namespace, service)
            else:
                raise erreurs.amont_indisponible("kubernetes", str(exc)) from exc

    def supprimer_deployment(self, namespace: str, nom: str) -> None:
        from kubernetes import client as k8s_client

        api_client = self._api_client()
        apps = k8s_client.AppsV1Api(api_client)
        core = k8s_client.CoreV1Api(api_client)
        try:
            apps.delete_namespaced_deployment(nom, namespace)
        except k8s_client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise erreurs.amont_indisponible("kubernetes", str(exc)) from exc
        try:
            core.delete_namespaced_service(nom, namespace)
        except k8s_client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise erreurs.amont_indisponible("kubernetes", str(exc)) from exc


_SIMULE = K8sWorkloadSimule()


def obtenir() -> K8sWorkloadSimule:
    """Choisit `K8sWorkloadReel` seulement si `SYNELIA_PAAS_CLUSTER_ID` est configuré.

    Contrairement aux amonts purement OpenStack (Magnum, Nova…), ce choix ne dépend
    **pas** du mode `fournisseur` global : sans cette variable, le PaaS reste en
    simulation même quand le reste de la plateforme tourne en réel — pour ne pas
    faire échouer la création de projets/composants tant qu'aucun cluster PaaS
    n'a été désigné.
    """
    if not os.environ.get(ENV_CLUSTER_ID):
        return _SIMULE
    from synelia_openstack.fabrique import fournisseur

    return fournisseur(K8sWorkloadSimule, K8sWorkloadReel)
