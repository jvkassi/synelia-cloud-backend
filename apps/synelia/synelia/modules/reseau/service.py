from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Organisation, Ressource, Travail, Utilisateur
from synelia_openstack import fournisseur
from synelia_openstack.network import NetworkOpenStack, NetworkSimule

from synelia.demo import peupleur
from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot_reseau = Depot("reseau", m.Reseau, libelle="Réseau")
depot_ip = Depot(
    "ip_publique", m.IpPublique, libelle="IP publique", champs_recherche=("adresse", "ptr")
)
depot_groupe = Depot("groupe_securite", m.GroupeSecurite, libelle="Groupe de sécurité")
depot_lb = Depot("load_balancer", m.LoadBalancer, libelle="Load balancer")
depot_vpn = Depot(
    "vpn_tunnel", m.TunnelVpn, libelle="Tunnel VPN", champs_recherche=("nom", "passerelleDistante")
)


def amont() -> NetworkSimule:
    return fournisseur(NetworkSimule, NetworkOpenStack)


async def prochaine_ip(ctx: Contexte, espace_id: str) -> str:
    ips = await depot_ip.tous(ctx, filtre=lambda ip: ip.espaceId == espace_id)
    n = len(ips)
    octet3 = (n // 250) + 1
    octet4 = (n % 250) + 2
    return f"196.201.{octet3}.{octet4}"


def sante_defaut() -> m.HealthCheck:
    return m.HealthCheck(
        protocole="http", chemin="/health", codeAttendu=200, intervalleS=30, seuilKo=3, seuilOk=2
    )


def metriques_vides() -> m.Metriques:
    return m.Metriques(rps=0, p50=0, p95=0, p99=0, taux4xx=0, taux5xx=0, connexions=0)


@executeur("lb.create")
class ExecuteurLbCreate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        lb = await depot_lb.obtenir(ctx, travail.cible_id or "")
        await depot_lb.modifier(ctx, lb.id, {"vip": amont().allouer_vip()})


@peupleur
async def demo(session, org: Organisation, admin: Utilisateur) -> None:
    espace_id = "espace-demo-abj"
    ressources = [
        m.Reseau(
            id="reseau-demo-prod",
            espaceId=espace_id,
            nom="prod-net",
            cidr="10.50.0.0/16",
            dnsInterne=True,
            workloads=2,
            vlan=101,
        ),
        m.Reseau(
            id="reseau-demo-app",
            espaceId=espace_id,
            nom="app-net",
            cidr="10.51.0.0/16",
            dnsInterne=True,
            workloads=0,
            vlan=102,
        ),
        m.IpPublique(
            id="ip-demo-1",
            espaceId=espace_id,
            adresse="196.201.1.10",
            ptr="api.example.com",
            attachedTo="vm-demo-web",
            attachedLabel="web-01",
            antiDdos=False,
        ),
        m.IpPublique(
            id="ip-demo-2",
            espaceId=espace_id,
            adresse="196.201.1.11",
            ptr="db.example.com",
            attachedTo=None,
            attachedLabel=None,
            antiDdos=True,
        ),
    ]
    for res in ressources:
        session.add(
            Ressource(
                id=res.id,
                org_id=org.id,
                type={"Reseau": "reseau", "IpPublique": "ip_publique"}[type(res).__name__],
                nom=getattr(res, "nom", getattr(res, "adresse", None)),
                donnees=res.model_dump(mode="json"),
            )
        )
