"""Tenancy : organisation → domaine Keystone, Espace → projet + réseau + quotas + application credential."""

from __future__ import annotations

import ipaddress
from typing import Any

from synelia_kernel.ids import jeton_opaque, nouvel_id


class IdentiteSimule:
    """Aucun amont : renvoie des identifiants plausibles, instantanément."""

    def creer_domaine(self, nom: str) -> str:
        return f"dom-{nouvel_id()[:8]}"

    def creer_projet(self, domaine_id: str, nom: str, region: str) -> str:
        return f"proj-{nouvel_id()[:8]}"

    def poser_quotas(self, projet_id: str, vcpu: int, ram_go: int, stockage_to: float) -> None:
        return None

    def creer_reseau(self, projet_id: str, nom: str, cidr: str) -> dict[str, Any]:
        ipaddress.ip_network(cidr)
        return {
            "reseau_id": f"net-{nouvel_id()[:8]}",
            "sous_reseau_id": f"sub-{nouvel_id()[:8]}",
            "routeur_id": f"rtr-{nouvel_id()[:8]}",
        }

    def creer_application_credential(self, projet_id: str) -> dict[str, str]:
        return {"id": f"ac-{nouvel_id()[:8]}", "secret": jeton_opaque(24)}

    def supprimer_projet(self, projet_id: str) -> None:
        return None


class IdentiteOpenStack(IdentiteSimule):
    """openstacksdk : Keystone + Neutron + quotas Nova/Cinder/Neutron."""

    def _conn(self, region: str | None = None):
        from synelia_openstack.fabrique import connexion

        return connexion(region)

    def creer_domaine(self, nom: str) -> str:
        c = self._conn()
        d = c.identity.find_domain(nom) or c.identity.create_domain(name=nom, enabled=True)
        return d.id

    def creer_projet(self, domaine_id: str, nom: str, region: str) -> str:
        c = self._conn(region)
        p = c.identity.find_project(nom, domain_id=domaine_id) or c.identity.create_project(
            name=nom, domain_id=domaine_id, enabled=True
        )
        return p.id

    def poser_quotas(self, projet_id: str, vcpu: int, ram_go: int, stockage_to: float) -> None:
        c = self._conn()
        c.set_compute_quotas(projet_id, cores=vcpu, ram=ram_go * 1024, instances=max(10, vcpu))
        c.set_volume_quotas(projet_id, gigabytes=int(stockage_to * 1024), volumes=max(20, vcpu * 2))

    def creer_reseau(self, projet_id: str, nom: str, cidr: str) -> dict[str, Any]:
        c = self._conn()
        net = c.network.create_network(name=nom, project_id=projet_id)
        sub = c.network.create_subnet(
            name=f"{nom}-sub", network_id=net.id, ip_version=4, cidr=cidr, project_id=projet_id
        )
        ext = next((n for n in c.network.networks(is_router_external=True)), None)
        rtr = c.network.create_router(
            name=f"{nom}-rtr",
            project_id=projet_id,
            external_gateway_info={"network_id": ext.id} if ext else None,
        )
        c.network.add_interface_to_router(rtr, subnet_id=sub.id)
        return {"reseau_id": net.id, "sous_reseau_id": sub.id, "routeur_id": rtr.id}

    def creer_application_credential(self, projet_id: str) -> dict[str, str]:
        c = self._conn()
        ac = c.identity.create_application_credential(
            user=c.current_user_id, name=f"synelia-{projet_id[:8]}", roles=[{"name": "member"}]
        )
        return {"id": ac.id, "secret": ac.secret}

    def supprimer_projet(self, projet_id: str) -> None:
        self._conn().identity.delete_project(projet_id, ignore_missing=True)
