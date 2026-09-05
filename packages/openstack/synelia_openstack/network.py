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
        lb = {
            "id": f"lb-{nouvel_id()[:8]}",
            "vip": self.allouer_vip(),
            "statut": "ACTIVE",
            "listener_id": f"lsnr-{nouvel_id()[:8]}",
            "pool_id": f"pool-{nouvel_id()[:8]}",
        }
        if exposure == "public":
            fip = self.associer_ip_flottante_lb(lb["id"], projet_id)
            lb["fip_id"] = fip.get("id")
            lb["fip_adresse"] = fip.get("adresse")
        return lb

    def supprimer_load_balancer(self, lb_id: str) -> None:
        return None

    def associer_ip_flottante_lb(self, lb_id: str, projet_id: str | None) -> dict[str, Any]:
        return {"id": f"fip-{nouvel_id()[:8]}", "adresse": self.allouer_vip()}

    def supprimer_ip_flottante_lb(self, fip_id: str) -> None:
        return None

    def creer_pool(self, *, loadbalancer_id: str | None, nom: str, protocole: str = "http") -> dict[str, Any]:
        return {"id": f"pool-{nouvel_id()[:8]}"}

    def supprimer_pool(self, pool_id: str, loadbalancer_id: str | None = None) -> None:
        return None

    def ajouter_membre(
        self,
        *,
        pool_id: str,
        adresse: str,
        port: int,
        subnet_id: str | None = None,
        loadbalancer_id: str | None = None,
    ) -> dict[str, Any]:
        return {"id": f"mbr-{nouvel_id()[:8]}"}

    def supprimer_membre(
        self, pool_id: str, membre_id: str, loadbalancer_id: str | None = None
    ) -> None:
        return None

    def ajouter_regle_hote(
        self, *, listener_id: str | None, loadbalancer_id: str | None, pool_id: str, hote: str
    ) -> dict[str, Any]:
        return {"policy_id": f"l7p-{nouvel_id()[:8]}", "rule_id": f"l7r-{nouvel_id()[:8]}"}

    def supprimer_regle_hote(self, policy_id: str, loadbalancer_id: str | None = None) -> None:
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
        listener_id = None
        pool_id = None
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
                listener_id = ecouteur.id
                lb = self._attendre_actif(c, lb.id)
                statut = lb.provisioning_status
                if statut == "ACTIVE":
                    pool = c.load_balancer.create_pool(
                        name=f"{nom}-pool",
                        listener_id=ecouteur.id,
                        protocol=protocole,
                        lb_algorithm="ROUND_ROBIN",
                    )
                    pool_id = pool.id
                    lb = self._attendre_actif(c, lb.id)
                    statut = lb.provisioning_status
        resultat = {
            "id": lb.id,
            "vip": vip or lb.vip_address,
            "statut": statut,
            "listener_id": listener_id,
            "pool_id": pool_id,
        }
        if exposure == "public":
            fip = self.associer_ip_flottante_lb(lb.id, projet_id)
            resultat["fip_id"] = fip.get("id")
            resultat["fip_adresse"] = fip.get("adresse")
        return resultat

    def supprimer_load_balancer(self, lb_id: str) -> None:
        self._c().load_balancer.delete_load_balancer(lb_id, cascade=True, ignore_missing=True)

    def _reseau_externe(self, c: Any) -> Any:
        return next((n for n in c.network.networks(is_router_external=True)), None)

    def associer_ip_flottante_lb(self, lb_id: str, projet_id: str | None) -> dict[str, Any]:
        """Alloue une IP flottante publique et l'associe au VIP d'un load balancer
        `exposure=public` — équivalent, pour un LB, de `identite.associer_ip_flottante`
        pour un serveur Nova."""
        c = self._c()
        lb = c.load_balancer.get_load_balancer(lb_id)
        ext = self._reseau_externe(c)
        if ext is None or not lb.vip_port_id:
            return {}
        fip = c.network.create_ip(
            floating_network_id=ext.id, port_id=lb.vip_port_id, project_id=projet_id
        )
        return {"id": fip.id, "adresse": fip.floating_ip_address}

    def supprimer_ip_flottante_lb(self, fip_id: str) -> None:
        self._c().network.delete_ip(fip_id, ignore_missing=True)

    def creer_pool(
        self, *, loadbalancer_id: str | None, nom: str, protocole: str = "http"
    ) -> dict[str, Any]:
        """Pool additionnel (pas le pool par défaut d'un listener) : cible d'une policy L7,
        un par hébergement — c'est lui qui reçoit le(s) membre(s) (VM du client)."""
        c = self._c()
        pool = c.load_balancer.create_pool(
            name=nom[:255],
            loadbalancer_id=loadbalancer_id,
            protocol=protocole.upper(),
            lb_algorithm="ROUND_ROBIN",
        )
        self._attendre_actif(c, loadbalancer_id)
        return {"id": pool.id}

    def supprimer_pool(self, pool_id: str, loadbalancer_id: str | None = None) -> None:
        c = self._c()
        c.load_balancer.delete_pool(pool_id, ignore_missing=True)
        if loadbalancer_id:
            self._attendre_actif(c, loadbalancer_id)

    def ajouter_membre(
        self,
        *,
        pool_id: str,
        adresse: str,
        port: int,
        subnet_id: str | None = None,
        loadbalancer_id: str | None = None,
    ) -> dict[str, Any]:
        c = self._c()
        attrs: dict[str, Any] = {"address": adresse, "protocol_port": port}
        if subnet_id:
            attrs["subnet_id"] = subnet_id
        m = c.load_balancer.create_member(pool_id, **attrs)
        if loadbalancer_id:
            # Octavia passe le LB en `PENDING_UPDATE` le temps de reconfigurer les amphores :
            # sans attendre son retour à `ACTIVE`, la policy L7 suivante (même hébergement)
            # échoue avec `409 Load Balancer ... is immutable`.
            self._attendre_actif(c, loadbalancer_id)
        return {"id": m.id}

    def supprimer_membre(
        self, pool_id: str, membre_id: str, loadbalancer_id: str | None = None
    ) -> None:
        c = self._c()
        c.load_balancer.delete_member(membre_id, pool_id, ignore_missing=True)
        if loadbalancer_id:
            self._attendre_actif(c, loadbalancer_id)

    def ajouter_regle_hote(
        self, *, listener_id: str | None, loadbalancer_id: str | None, pool_id: str, hote: str
    ) -> dict[str, Any]:
        """Route `hote` (Host HTTP) vers `pool_id` : une policy L7 `REDIRECT_TO_POOL` +
        une règle `HOST_NAME` — un couple par hébergement, sur le listener partagé de la
        zone VPS."""
        c = self._c()
        policy = c.load_balancer.create_l7_policy(
            listener_id=listener_id,
            action="REDIRECT_TO_POOL",
            redirect_pool_id=pool_id,
            name=f"host-{hote}"[:255],
        )
        self._attendre_actif(c, loadbalancer_id)
        regle = c.load_balancer.create_l7_rule(
            policy.id, type="HOST_NAME", compare_type="EQUAL_TO", rule_value=hote
        )
        self._attendre_actif(c, loadbalancer_id)
        return {"policy_id": policy.id, "rule_id": regle.id}

    def supprimer_regle_hote(self, policy_id: str, loadbalancer_id: str | None = None) -> None:
        # Supprimer la policy L7 supprime ses règles en cascade côté Octavia.
        c = self._c()
        c.load_balancer.delete_l7_policy(policy_id, ignore_missing=True)
        if loadbalancer_id:
            self._attendre_actif(c, loadbalancer_id)
