from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Organisation, Ressource, Travail, Utilisateur
from synelia_openstack import fournisseur
from synelia_openstack.identite import IdentiteOpenStack, IdentiteSimule
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


def amont_identite() -> IdentiteSimule:
    """Réseaux secondaires et IP flottantes vivent dans le projet de l'Espace Cloud parent :
    même amont (Keystone/Neutron scopé projet) que `espaces.service.amont()`."""
    return fournisseur(IdentiteSimule, IdentiteOpenStack)


async def prochaine_ip(ctx: Contexte, espace_id: str) -> str:
    ips = await depot_ip.tous(ctx, filtre=lambda ip: ip.espaceId == espace_id)
    n = len(ips)
    octet3 = (n // 250) + 1
    octet4 = (n % 250) + 2
    return f"196.201.{octet3}.{octet4}"


async def _projet_id(ctx: Contexte, espace_id: str) -> str | None:
    from synelia.modules.espaces.service import depot as depot_espaces

    secrets_espace = await depot_espaces.secrets(ctx, espace_id)
    return secrets_espace.get("projet_id")


async def creer_reseau_amont(ctx: Contexte, espace_id: str, nom: str, cidr: str) -> dict[str, str]:
    """Crée le réseau/sous-réseau amont (sans routeur : c'est un réseau interne de plus dans un
    projet qui en a déjà un) et renvoie les identifiants à poser en secrets sur la ressource."""
    projet_id = await _projet_id(ctx, espace_id)
    r = amont_identite().creer_reseau_secondaire(projet_id, nom, cidr)
    return {"reseau_id": r["reseau_id"], "sous_reseau_id": r.get("sous_reseau_id") or ""}


async def supprimer_reseau_amont(ctx: Contexte, reseau_id_local: str) -> None:
    secrets = await depot_reseau.secrets(ctx, reseau_id_local)
    rid = secrets.get("reseau_id")
    if rid:
        amont_identite().supprimer_reseau_secondaire(rid)


async def reserver_ip_amont(ctx: Contexte, espace_id: str) -> dict[str, str]:
    """Alloue une IP flottante amont ; le simulé ne renvoie pas d'adresse plausible-mais-stable
    (pas d'accès à la base), on retombe alors sur l'allocation séquentielle locale."""
    projet_id = await _projet_id(ctx, espace_id)
    fip = amont_identite().creer_ip_flottante(projet_id)
    adresse = fip.get("adresse") or await prochaine_ip(ctx, espace_id)
    return {"id": fip["id"], "adresse": adresse}


async def liberer_ip_amont(ctx: Contexte, ip_id_local: str) -> None:
    secrets = await depot_ip.secrets(ctx, ip_id_local)
    fid = secrets.get("ip_flottante_id")
    if fid:
        amont_identite().supprimer_ip_flottante(fid)


async def supprimer_lb_amont(ctx: Contexte, lb_id_local: str) -> None:
    secrets = await depot_lb.secrets(ctx, lb_id_local)
    oid = secrets.get("octavia_lb_id")
    if oid:
        amont().supprimer_load_balancer(oid)


def sante_defaut() -> m.HealthCheck:
    return m.HealthCheck(
        protocole="http", chemin="/health", codeAttendu=200, intervalleS=30, seuilKo=3, seuilOk=2
    )


def metriques_vides() -> m.Metriques:
    return m.Metriques(rps=0, p50=0, p95=0, p99=0, taux4xx=0, taux5xx=0, connexions=0)


@executeur("lb.create")
class ExecuteurLbCreate(Executeur):
    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 1:
            lb = await depot_lb.obtenir(ctx, travail.cible_id or "")
            entree = travail.entree or {}
            from synelia.modules.espaces.service import depot as depot_espaces

            secrets_espace = await depot_espaces.secrets(ctx, lb.espaceId)
            res = amont().creer_load_balancer(
                projet_id=secrets_espace.get("projet_id"),
                nom=lb.nom,
                reseau_id=secrets_espace.get("reseau_id"),
                layer=lb.layer,
                exposure=lb.exposure,
                listeners=entree.get("listeners"),
            )
            await depot_lb.definir_secrets(ctx, lb.id, {"octavia_lb_id": res["id"]})
            c = dict(travail.contexte)
            c["vip"] = res["vip"]
            travail.contexte = c
            return f"Load balancer amont {res['id']} créé ({res['statut']})"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        lb = await depot_lb.obtenir(ctx, travail.cible_id or "")
        vip = travail.contexte.get("vip") or amont().allouer_vip()
        await depot_lb.modifier(ctx, lb.id, {"vip": vip})

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        await supprimer_lb_amont(ctx, travail.cible_id or "")


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
