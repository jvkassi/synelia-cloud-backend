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

    def creer_load_balancer(
        self,
        *,
        projet_id: str | None,
        nom: str,
        reseau_id: str | None,
        layer: str,
        exposure: str,
        listeners: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {"id": f"lb-{nouvel_id()[:8]}", "vip": self.allouer_vip(), "statut": "ACTIVE"}

    def supprimer_load_balancer(self, lb_id: str) -> None:
        return None


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
        return {"id": nouvel_id()}

    def _attendre_actif(self, c: Any, lb_id: str, wait: int = 60) -> Any:
        """Attente bornée (Octavia déploie une paire d'amphores : bien plus long qu'une étape
        de travail). Au-delà de `wait`, on relit juste le statut courant et on continue :
        le load balancer reste `PENDING_CREATE`/`PENDING_UPDATE` tant qu'un réconciliateur (à
        écrire) n'a pas confirmé `ACTIVE` côté Octavia."""
        try:
            return c.load_balancer.wait_for_load_balancer(lb_id, wait=wait)
        except Exception:  # noqa: BLE001
            return c.load_balancer.get_load_balancer(lb_id)

    def creer_load_balancer(
        self,
        *,
        projet_id: str | None,
        nom: str,
        reseau_id: str | None,
        layer: str,
        exposure: str,
        listeners: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        c = self._c()
        lb = c.load_balancer.create_load_balancer(
            name=nom, vip_network_id=reseau_id, project_id=projet_id
        )
        vip = lb.vip_address
        lb = self._attendre_actif(c, lb.id)
        statut = lb.provisioning_status
        if statut == "ACTIVE":
            proto_defaut = "tcp" if layer == "l4" else "http"
            for ln in listeners or [{"protocole": proto_defaut, "port": 80}]:
                protocole = str(ln.get("protocole") or proto_defaut).upper()
                port = int(ln.get("port") or 80)
                ecouteur = c.load_balancer.create_listener(
                    name=f"{nom}-ecouteur",
                    loadbalancer_id=lb.id,
                    protocol=protocole,
                    protocol_port=port,
                )
                lb = self._attendre_actif(c, lb.id)
                statut = lb.provisioning_status
                if statut == "ACTIVE":
                    c.load_balancer.create_pool(
                        name=f"{nom}-pool",
                        listener_id=ecouteur.id,
                        protocol=protocole,
                        lb_algorithm="ROUND_ROBIN",
                    )
                    lb = self._attendre_actif(c, lb.id)
                    statut = lb.provisioning_status
        return {"id": lb.id, "vip": vip or lb.vip_address, "statut": statut}

    def supprimer_load_balancer(self, lb_id: str) -> None:
        self._c().load_balancer.delete_load_balancer(lb_id, cascade=True, ignore_missing=True)
