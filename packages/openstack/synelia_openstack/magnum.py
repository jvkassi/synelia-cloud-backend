"""Magnum : clusters et pools Kubernetes."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import nouvel_id


class MagnumSimule:
    def creer_cluster(self, **kw: Any) -> dict[str, Any]:
        return {"id": f"k8s-{nouvel_id()[:8]}", "statut": "CREATE_COMPLETE"}

    def creer_pool(self, cluster_id: str, **kw: Any) -> None:
        return None

    def modifier_pool(self, cluster_id: str, pool_nom: str, **kw: Any) -> None:
        return None

    def supprimer_pool(self, cluster_id: str, pool_nom: str) -> None:
        return None

    def monter_version(self, cluster_id: str, version: str) -> None:
        return None

    def installer_modules(self, cluster_id: str, modules: list[str]) -> None:
        return None

    def activer_reparateur(self, cluster_id: str) -> None:
        return None

    def supprimer_cluster(self, cluster_id: str) -> None:
        return None


class MagnumOpenStack(MagnumSimule):
    def _c(self):
        from synelia_openstack.fabrique import connexion

        return connexion()

    def _modele_tpl(self, c) -> str:
        """Un seul modèle public existe sur ce lab (`k8s-capi`) ; on prend le premier."""
        tpl = next(iter(c.container_infra.cluster_templates()), None)
        if tpl is None:
            raise RuntimeError("Aucun modèle de cluster Magnum disponible.")
        return tpl.id

    def creer_cluster(self, **kw: Any) -> dict[str, Any]:
        c = self._c()
        attrs: dict[str, Any] = {
            "name": kw["nom"],
            "cluster_template_id": kw.get("modele_tpl") or self._modele_tpl(c),
            "master_count": kw.get("master_count", 1),
            "node_count": max(1, sum(p.get("nodes", 0) for p in kw.get("pools", []))),
            "create_timeout": 60,
        }
        # Le modèle public fixe un réseau par défaut (`demo-net`) : on le remplace par le
        # réseau réel de l'Espace Cloud cible, sinon le cluster atterrit sur le mauvais réseau.
        if kw.get("reseau_id"):
            attrs["fixed_network"] = kw["reseau_id"]
        if kw.get("cle_ssh"):
            attrs["keypair"] = kw["cle_ssh"]
        cl = c.container_infra.create_cluster(**attrs)
        return {"id": cl.id, "statut": cl.status}

    def creer_pool(self, cluster_id: str, **kw: Any) -> None:
        self._c().container_infra.create_nodegroup(
            cluster_id, name=kw["nom"], flavor=kw.get("flavor"), node_count=kw.get("nodes", 1)
        )

    def modifier_pool(self, cluster_id: str, pool_nom: str, **kw: Any) -> None:
        self._c().container_infra.update_nodegroup(cluster_id, pool_nom, dict(kw))

    def supprimer_pool(self, cluster_id: str, pool_nom: str) -> None:
        self._c().container_infra.delete_nodegroup(cluster_id, pool_nom, ignore_missing=True)

    def monter_version(self, cluster_id: str, version: str) -> None:
        self._c().container_infra.update_cluster(cluster_id, version=version)

    def installer_modules(self, cluster_id: str, modules: list[str]) -> None:
        return None

    def activer_reparateur(self, cluster_id: str) -> None:
        return None

    def supprimer_cluster(self, cluster_id: str) -> None:
        self._c().container_infra.delete_cluster(cluster_id, ignore_missing=True)
