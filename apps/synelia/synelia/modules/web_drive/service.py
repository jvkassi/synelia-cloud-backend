"""Règles drive (Web Cloud) : dépôt, exécuteurs d'activation/désactivation, VM Nextcloud dédiée.

Drive est scopé par `domaine` (pas par hébergement) : contrairement aux applications de
`web_hebergement.router_sites`, aucun hébergement existant n'est requis. Chaque instance
obtient sa **propre VM Nova** dans la zone VPS partagée, avec exactement la même recette que
`web_hebergement.service.ExecuteurHebergementCreer` : cloud-init Docker + Traefik (provider
fichier, pas Docker — même bug de compat API contourné là-bas) + conteneurs applicatifs,
routée sur le load balancer partagé par un `Host(drive.<domaine>)` dédié. On réutilise
directement `zone_vps_secrets`, `image_ubuntu`, `gabarit_pour_palier` et `amont_network()` de
`web_hebergement` plutôt que de les dupliquer — même zone, mêmes secrets, même load balancer.
"""

from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel.ids import jeton_opaque
from synelia_openstack import fournisseur
from synelia_openstack.compute import ComputeOpenStack, ComputeSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.modules.web_hebergement.service import (
    amont_network,
    gabarit_pour_palier,
    image_ubuntu,
    ip_privee,
    zone_vps_secrets,
)
from synelia.travaux import Executeur, executeur

depot = Depot(
    "web_drive",
    m.Drive,
    libelle="Drive",
    champ_nom="domaine",
    champ_statut="actif",
    champs_recherche=("domaine",),
)
depot_siege = Depot("web_drive_siege", m.Siege, libelle="Siège drive", champ_nom="userId")

PALIERS = {
    "starter": {"sieges": 10, "prixSiege": 1500},
    "pro": {"sieges": 50, "prixSiege": 1000},
    "business": {"sieges": 200, "prixSiege": 800},
}

_RACINE_DOCKER = "/srv/synelia"


def amont() -> ComputeSimule:
    return fournisseur(ComputeSimule, ComputeOpenStack)


def palier(cle: str) -> dict:
    return PALIERS.get(cle, PALIERS["starter"])


def _indenter(bloc: str, colonnes: int) -> str:
    prefixe = " " * colonnes
    return "\n".join(f"{prefixe}{ligne}" for ligne in bloc.splitlines())


def construire_cloud_init(hote: str, mot_de_passe: str) -> str:
    """`#cloud-config` : Docker + Traefik (provider fichier) + Nextcloud + MariaDB, sur une VM
    dédiée à cette seule instance Drive. Même structure que `web_hebergement.construire_
    cloud_init`, un service applicatif différent derrière le même Traefik."""
    compose = f"""services:
  traefik:
    image: traefik:v3.5
    restart: unless-stopped
    command:
      - --providers.file.directory=/etc/traefik/dynamic
      - --providers.file.watch=true
      - --entrypoints.web.address=:80
    ports:
      - "80:80"
    volumes:
      - {_RACINE_DOCKER}/traefik-dynamic:/etc/traefik/dynamic:ro
    networks:
      - synelia

  db:
    image: mariadb:11
    restart: unless-stopped
    environment:
      - MARIADB_ROOT_PASSWORD={mot_de_passe}
      - MARIADB_DATABASE=nextcloud
      - MARIADB_USER=nextcloud
      - MARIADB_PASSWORD={mot_de_passe}
    volumes:
      - {_RACINE_DOCKER}/db:/var/lib/mysql
    networks:
      - synelia

  nextcloud:
    image: nextcloud:apache
    restart: unless-stopped
    depends_on:
      - db
    environment:
      - MYSQL_HOST=db
      - MYSQL_DATABASE=nextcloud
      - MYSQL_USER=nextcloud
      - MYSQL_PASSWORD={mot_de_passe}
      - NEXTCLOUD_ADMIN_USER=admin
      - NEXTCLOUD_ADMIN_PASSWORD={mot_de_passe}
      - NEXTCLOUD_TRUSTED_DOMAINS={hote}
      - OVERWRITEPROTOCOL=http
    volumes:
      - {_RACINE_DOCKER}/nextcloud:/var/www/html
    networks:
      - synelia

networks:
  synelia:
    name: synelia
"""
    routage = f"""http:
  routers:
    drive:
      rule: "Host(`{hote}`)"
      entryPoints:
        - web
      service: drive
  services:
    drive:
      loadBalancer:
        servers:
          - url: "http://nextcloud:80"
"""
    return (
        "#cloud-config\n"
        "package_update: true\n"
        "packages:\n"
        "  - docker.io\n"
        "  - docker-compose-v2\n"
        "write_files:\n"
        f"  - path: {_RACINE_DOCKER}/docker-compose.yml\n"
        "    content: |\n" + _indenter(compose, 6) + "\n"
        f"  - path: {_RACINE_DOCKER}/traefik-dynamic/drive.yml\n"
        "    content: |\n" + _indenter(routage, 6) + "\n"
        "runcmd:\n"
        "  - systemctl enable --now docker\n"
        f"  - [sh, -c, 'cd {_RACINE_DOCKER} && docker compose up -d']\n"
    )


async def serveur_id(ctx: Contexte, drive_id: str, travail: Travail | None = None) -> str:
    if travail and travail.contexte.get("serveur_id"):
        return str(travail.contexte["serveur_id"])
    try:
        sec = await depot.secrets(ctx, drive_id)
    except Exception:  # noqa: BLE001
        sec = {}
    return str(sec.get("serveur_id") or drive_id)


@executeur("web.drive.activate")
class ExecuteurDriveActivate(Executeur):
    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 1:
            drive = await depot.obtenir(ctx, travail.cible_id or "")
            mdp = jeton_opaque(16)
            zone = await zone_vps_secrets(ctx)
            srv = amont().creer_serveur(
                nom=f"drive-{drive.id[:8]}",
                image_id=image_ubuntu(),
                gabarit_id=gabarit_pour_palier(drive.palier),
                reseau_id=zone.get("reseau_id"),
                identifiants=zone,
                org_id=ctx.org_id_ou_none,
                espace_id=None,
                cloud_init=construire_cloud_init(drive.hote, mdp),
            )
            c = dict(travail.contexte)
            c["serveur_id"] = srv["id"]
            c["ip_privee"] = srv.get("ip_privee") or ip_privee(drive.id)
            travail.contexte = c
            await depot.definir_secrets(
                ctx,
                drive.id,
                {"serveur_id": srv["id"], "admin_utilisateur": "admin", "admin_mdp": mdp},
            )
            return f"Serveur Nextcloud {srv['id']} créé"
        if index == 2:
            did = travail.cible_id or ""
            drive = await depot.obtenir(ctx, did)
            c = dict(travail.contexte)
            zone = await zone_vps_secrets(ctx)
            lb_id = zone.get("lb_id")
            n = amont_network()
            pool = n.creer_pool(loadbalancer_id=lb_id, nom=f"pool-drv-{did[:8]}")
            await depot.definir_secrets(ctx, did, {"lb_pool_id": pool["id"]})
            c["lb_pool_id"] = pool["id"]
            travail.contexte = c
            membre = n.ajouter_membre(
                pool_id=pool["id"],
                adresse=c["ip_privee"],
                port=80,
                subnet_id=zone.get("sous_reseau_id"),
                loadbalancer_id=lb_id,
            )
            await depot.definir_secrets(ctx, did, {"lb_membre_id": membre["id"]})
            c["lb_membre_id"] = membre["id"]
            travail.contexte = c
            regle = n.ajouter_regle_hote(
                listener_id=zone.get("lb_listener_id"),
                loadbalancer_id=lb_id,
                pool_id=pool["id"],
                hote=drive.hote,
            )
            await depot.definir_secrets(ctx, did, {"lb_policy_id": regle["policy_id"]})
            c["lb_policy_id"] = regle["policy_id"]
            travail.contexte = c
            return f"Domaine {drive.hote} routé sur le load balancer partagé"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.modifier(ctx, travail.cible_id or "", {"actif": True})

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        sid = await serveur_id(ctx, travail.cible_id or "", travail)
        if sid and sid != (travail.cible_id or ""):
            amont().supprimer_serveur(sid)
        n = amont_network()
        lb_id = (await zone_vps_secrets(ctx)).get("lb_id")
        policy_id = travail.contexte.get("lb_policy_id")
        if policy_id:
            n.supprimer_regle_hote(policy_id, loadbalancer_id=lb_id)
        pool_id = travail.contexte.get("lb_pool_id")
        membre_id = travail.contexte.get("lb_membre_id")
        if pool_id and membre_id:
            n.supprimer_membre(pool_id, membre_id, loadbalancer_id=lb_id)
        if pool_id:
            n.supprimer_pool(pool_id, loadbalancer_id=lb_id)


@executeur("web.drive.desactiver")
class ExecuteurDriveDesactiver(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        did = travail.cible_id or ""
        try:
            secrets = await depot.secrets(ctx, did)
        except Exception:  # noqa: BLE001
            secrets = {}
        sid = secrets.get("serveur_id")
        if sid:
            amont().supprimer_serveur(sid)
        n = amont_network()
        lb_id = (await zone_vps_secrets(ctx)).get("lb_id")
        policy_id = secrets.get("lb_policy_id")
        if policy_id:
            n.supprimer_regle_hote(policy_id, loadbalancer_id=lb_id)
        pool_id = secrets.get("lb_pool_id")
        membre_id = secrets.get("lb_membre_id")
        if pool_id and membre_id:
            n.supprimer_membre(pool_id, membre_id, loadbalancer_id=lb_id)
        if pool_id:
            n.supprimer_pool(pool_id, loadbalancer_id=lb_id)
        await depot_siege.supprimer_enfants(ctx, did)
        await depot.supprimer(ctx, did, logique=True)
