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


async def associer_ip_amont(ctx: Contexte, ip_id_local: str, vm_id: str) -> str | None:
    """Associe réellement l'IP flottante au port Neutron du serveur Nova de la VM cible —
    sans cet appel l'attachement ne vivait que côté DB (constaté en direct : `openstack
    floating ip show` restait sans port associé après un `PUT .../attachement` réussi)."""
    from synelia.modules.vms.service import serveur_id

    secrets = await depot_ip.secrets(ctx, ip_id_local)
    fid = secrets.get("ip_flottante_id")
    if not fid:
        return None
    sid = await serveur_id(ctx, vm_id)
    return amont_identite().associer_ip_flottante(fid, sid)


async def dissocier_ip_amont(ctx: Contexte, ip_id_local: str) -> None:
    secrets = await depot_ip.secrets(ctx, ip_id_local)
    fid = secrets.get("ip_flottante_id")
    if fid:
        amont_identite().dissocier_ip_flottante(fid)


def _regle_neutron(regle: m.RegleSecurite) -> dict[str, object]:
    """Traduit une `RegleSecurite` applicative en attributs Neutron. Sans cette traduction (et
    sans qu'aucune règle ne soit jamais posée côté amont, cf. `ajouter_regle_amont`), un groupe
    de sécurité créé par l'API n'avait strictement aucun effet réel : il ne vivait qu'en base,
    n'était jamais attaché à un port Neutron ni doté de la moindre règle (constaté en direct —
    un port bloqué par une règle « deny » restait joignable après création de la règle)."""
    port_min = port_max = None
    protocole = None if regle.protocole == "any" else regle.protocole
    if regle.ports and protocole in ("tcp", "udp"):
        if "-" in regle.ports:
            lo, hi = regle.ports.split("-", 1)
            port_min, port_max = int(lo), int(hi)
        else:
            port_min = port_max = int(regle.ports)
    attrs: dict[str, object] = {
        "direction": "ingress" if regle.direction == "in" else "egress",
        "protocol": protocole,
        "port_range_min": port_min,
        "port_range_max": port_max,
        "ethertype": "IPv4",
    }
    try:
        import ipaddress

        ipaddress.ip_network(regle.cible, strict=False)
        attrs["remote_ip_prefix"] = regle.cible
    except ValueError:
        # Pas un CIDR : `cible` est l'identifiant (local) d'un autre groupe de sécurité —
        # on ne peut le référencer côté amont qu'en résolvant son identifiant Neutron réel.
        attrs["remote_group_id"] = regle.cible
    return attrs


async def creer_groupe_amont(ctx: Contexte, espace_id: str, nom: str, description: str | None) -> str:
    projet_id = await _projet_id(ctx, espace_id)
    return amont().creer_groupe(nom, description, projet_id)


async def supprimer_groupe_amont(ctx: Contexte, groupe_id_local: str) -> None:
    secrets = await depot_groupe.secrets(ctx, groupe_id_local)
    gid = secrets.get("groupe_id")
    if gid:
        amont().supprimer_groupe(gid)


async def ajouter_regle_amont(ctx: Contexte, groupe_id_local: str, regle: m.RegleSecurite) -> None:
    secrets = await depot_groupe.secrets(ctx, groupe_id_local)
    gid = secrets.get("groupe_id")
    if not gid:
        return
    rid = amont().ajouter_regle_securite(gid, **_regle_neutron(regle))
    await depot_groupe.definir_secrets(ctx, groupe_id_local, {f"regle_{regle.id}": rid})


async def supprimer_regle_amont(ctx: Contexte, groupe_id_local: str, regle_id: str) -> None:
    secrets = await depot_groupe.secrets(ctx, groupe_id_local)
    rid = secrets.get(f"regle_{regle_id}")
    if rid:
        amont().supprimer_regle_securite(rid)


async def attacher_groupe_amont(ctx: Contexte, groupe_id_local: str, cibles: list[str]) -> None:
    """Reflète l'ensemble des cibles demandées sur le port Neutron de chaque VM concernée :
    attache le groupe aux VM nouvellement listées, le détache de celles retirées."""
    from synelia.modules.vms.service import serveur_id

    secrets = await depot_groupe.secrets(ctx, groupe_id_local)
    gid = secrets.get("groupe_id")
    if not gid:
        return
    anciennes = {c for c in secrets if c.startswith("attache_")}
    anciens_ids = {c.removeprefix("attache_") for c in anciennes}
    nouveaux_ids = set(cibles)
    for retire in anciens_ids - nouveaux_ids:
        sid = await serveur_id(ctx, retire)
        amont().detacher_groupe_serveur(gid, sid)
    nouveaux_secrets: dict[str, str] = {}
    for ajoute in nouveaux_ids - anciens_ids:
        sid = await serveur_id(ctx, ajoute)
        amont().attacher_groupe_serveur(gid, sid)
        nouveaux_secrets[f"attache_{ajoute}"] = "1"
    if nouveaux_secrets:
        await depot_groupe.definir_secrets(ctx, groupe_id_local, nouveaux_secrets)


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
