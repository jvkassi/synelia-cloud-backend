"""Neutron : réseaux privés, IP flottantes, groupes de sécurité, load balancers, VPN.

Chaque domaine expose une paire `XxxSimule` / `XxxOpenStack` et le module obtient
l'implémentation par `fournisseur(XxxSimule, XxxOpenStack)`."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import nouvel_id


class NetworkSimule:
    """Aucun amont : renvoie des identifiants plausibles, instantanément."""

    def creer_reseau(self, nom: str, cidr: str, **kw: Any) -> dict[str, Any]:
        return {"id": f"net-{nouvel_id()[:8]}", "vlan": kw.get("vlan")}

    def obtenable_reseau(self) -> int:
        return int(nouvel_id()[:8], 16) % 200 + 100

    def allouer_vip(self) -> str:
        return f"196.201.{int(nouvel_id()[:2], 16) % 240 + 1}.{int(nouvel_id()[:2], 16) % 240 + 1}"

    def regles_vip(self) -> dict[str, Any]:
        return {"id": f"fl-{nouvel_id()[:8]}"}

    def creer_groupe(self, nom: str, description: str | None = None) -> str:
        return f"sg-{nouvel_id()[:8]}"


class NetworkOpenStack(NetworkSimule):
    """openstacksdk : Neutron (networks, floating IPs, security groups), Octavia, VPN."""

    def _c(self):  # type: ignore[no-untyped-def]
        from synelia_openstack.fabrique import connexion

        return connexion()

    def creer_reseau(self, nom: str, cidr: str, **kw: Any) -> dict[str, Any]:
        c = self._c()
        net = c.network.create_network(name=nom, project_id=kw.get("project_id"))
        sub = c.network.create_subnet(
            name=f"{nom}-sub",
            network_id=net.id,
            cidr=cidr,
            ip_version=4,
            project_id=kw.get("project_id"),
        )
        return {"id": net.id, "sous_reseau_id": sub.id, "vlan": kw.get("vlan")}

    def allouer_vip(self) -> str:
        return "196.201.1.10"

    def regles_vip(self) -> dict[str, Any]:
        return {"id": nouvel_id}
