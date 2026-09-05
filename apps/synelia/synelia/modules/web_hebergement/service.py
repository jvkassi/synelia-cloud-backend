from __future__ import annotations

from typing import Any

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id
from synelia_openstack import fournisseur
from synelia_openstack.compute import ComputeOpenStack, ComputeSimule
from synelia_openstack.network import NetworkOpenStack, NetworkSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot(
    "web_hebergement",
    m.Hebergement,
    libelle="Hébergement",
    champ_statut="statut",
    champ_nom="domaineProvisoire",
)
depot_sites = Depot(
    "web_site", m.SiteWeb, libelle="Site Web", champ_statut="statut", champ_nom="hote"
)
depot_bases = Depot("web_serveur_bases", m.ServeurBases, libelle="Serveur de bases")
depot_comptes = Depot(
    "web_compte_fichiers", m.CompteFichiers, libelle="Compte fichiers", champ_statut="statut"
)
depot_taches = Depot(
    "web_tache", m.TachePlanifieeWeb, libelle="Tâche planifiée", champ_statut="statut"
)
depot_domaines = Depot("web_domaine", m.Domaine, libelle="Domaine", champ_nom="nom")

VERSIONS_PHP = ["8.1", "8.2", "8.3", "8.4"]

METRIQUES = [
    ("cpu", "%", "Utilisation CPU"),
    ("ram", "%", "Utilisation RAM"),
    ("stockage", "%", "Stockage"),
    ("requetes", "req/min", "Requêtes HTTP"),
    ("trafique", "Mo/s", "Trafic réseau"),
    ("bases", "nb", "Bases de données"),
]


def metriques(fenetre: str) -> dict[str, Any]:
    from datetime import timedelta

    from synelia_kernel.dates import iso

    nb_points = {"24h": 24, "7j": 7, "30j": 30}[fenetre]
    pas = {"24h": timedelta(hours=1), "7j": timedelta(days=1), "30j": timedelta(days=1)}
    origine = maintenant() - pas[fenetre] * (nb_points - 1)
    series = [
        m.Serie(
            metrique=metrique,
            unite=unite,
            fenetre=fenetre,  # type: ignore[arg-type]
            points=[
                m.PointSerie(ts=origine + pas[fenetre] * i, valeur=0.0) for i in range(nb_points)
            ],
        )
        for metrique, unite, _libelle in METRIQUES
    ]
    return {
        "tuiles": [],
        "series": [s for s in series],
        "liens": m.LiensSortie(
            centreon=f"https://monitoring.synelia.cloud/{iso(maintenant())}",
        ),
    }


def traduire_cron(expression: str) -> str:
    parts = expression.split()
    if len(parts) == 5:
        minutes, heures, _jours_mois, _mois, _jours_semaine = parts
        if minutes == "0" and heures.isdigit():
            return f"Tous les jours à {int(heures):02d}:00."
        if minutes == "*/5":
            return "Toutes les 5 minutes."
    return f"Planification : {expression}."


def amont() -> ComputeSimule:
    return fournisseur(ComputeSimule, ComputeOpenStack)


def amont_network() -> NetworkSimule:
    """Neutron/Octavia — gestion du load balancer partagé de la zone VPS (pools, membres,
    règles L7 par hébergement)."""
    return fournisseur(NetworkSimule, NetworkOpenStack)


async def zone_vps_secrets(ctx: Contexte) -> dict[str, Any]:
    """Secrets de la zone VPS partagée : un unique Espace Cloud admin (réseau privé + load
    balancer Octavia public), configuré une fois (bootstrap manuel, voir docs/runbooks) et
    référencé par `SYNELIA_VPS_ZONE_ESPACE_ID`. Toutes les VM d'hébergement sont créées sur
    ce même réseau et projet OpenStack (jamais celui de l'organisation cliente) — seul le
    load balancer partagé les expose, chacune isolée par son `Host()` Traefik et sa policy
    L7 dédiée ; `SYNELIA_VPS_ZONE_ORG_ID` permet de lire ces secrets depuis le contexte de
    n'importe quelle organisation cliente (l'Espace appartient à l'organisation admin)."""
    from synelia_kernel.config import reglages

    from synelia.modules.espaces.service import depot as depot_espaces

    r = reglages()
    if not r.vps_zone_espace_id:
        return {}
    return await depot_espaces.secrets(ctx, r.vps_zone_espace_id, org_id=r.vps_zone_org_id)


# Le lab ne possède aujourd'hui que deux gabarits Nova réels — taillés pour Kubernetes,
# pas de petit gabarit dédié à l'hébergement web. On rattache les paliers les plus légers
# à `k8s.worker` et les autres à `k8s.master` ; c'est une limitation connue de capacité,
# pas un choix définitif (`enterprise` obtient donc les mêmes ressources que `business`).
_GABARIT_NOM_PAR_PALIER = {
    "starter": "k8s.worker",
    "pro": "k8s.worker",
    "business": "k8s.master",
    "enterprise": "k8s.master",
}
# Repli en mode simulé (catalogue de démo sans `k8s.*`) : le plus proche du palier.
_GABARIT_SIMULE_PAR_PALIER = {
    "starter": "s1.small",
    "pro": "g1.medium",
    "business": "g1.large",
    "enterprise": "g1.xlarge",
}


def gabarit_pour_palier(palier: str) -> str:
    nom = _GABARIT_NOM_PAR_PALIER.get(palier, "k8s.worker")
    g = next((f for f in amont().gabarits() if f["nom"] == nom), None)
    if g:
        return str(g["id"])
    return _GABARIT_SIMULE_PAR_PALIER.get(palier, "g1.medium")


def image_ubuntu() -> str:
    """Image système du serveur d'hébergement : Ubuntu 24.04, ou la plus proche disponible."""
    images = amont().images()
    img = next((i for i in images if i["id"] == "ubuntu-24.04"), None)
    if img is None:
        img = next((i for i in images if "ubuntu" in i["nom"].lower()), None)
    if img is None:
        img = images[0] if images else None
    return str(img["id"]) if img else "ubuntu-24.04"


_RACINE_DOCKER = "/srv/synelia"


def _indenter(bloc: str, colonnes: int) -> str:
    prefixe = " " * colonnes
    return "\n".join(f"{prefixe}{ligne}" for ligne in bloc.splitlines())


def construire_cloud_init(domaine: str, version_php: str) -> str:
    """`#cloud-config` : Docker + Traefik (reverse-proxy HTTP sur :80, provider Docker piloté
    par labels) et un conteneur PHP pour `domaine`, routé par son `Host()`. Nextcloud
    (« Drive ») est ajouté plus tard au même `docker-compose.yml`, sur cette même VM, quand
    `web_drive` est activé pour l'organisation (voir `web_drive.service`) — un Traefik par VM
    d'hébergement, tout le reste en conteneurs Docker derrière lui."""
    compose = f"""services:
  traefik:
    image: traefik:v3.1
    restart: unless-stopped
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
    ports:
      - "80:80"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - synelia

  site:
    image: php:{version_php}-apache
    restart: unless-stopped
    volumes:
      - {_RACINE_DOCKER}/www:/var/www/html:ro
    labels:
      - traefik.enable=true
      - traefik.http.routers.site.rule=Host(`{domaine}`)
      - traefik.http.routers.site.entrypoints=web
      - traefik.http.services.site.loadbalancer.server.port=80
    networks:
      - synelia

networks:
  synelia:
    name: synelia
"""
    index_php = (
        "<?php\n"
        f'echo "<h1>{domaine}</h1><p>Synelia Web Hebergement -- PHP " . phpversion() . "</p>";\n'
    )
    return (
        "#cloud-config\n"
        "package_update: true\n"
        "packages:\n"
        "  - docker.io\n"
        "  - docker-compose-v2\n"
        "write_files:\n"
        f"  - path: {_RACINE_DOCKER}/docker-compose.yml\n"
        "    content: |\n" + _indenter(compose, 6) + "\n"
        f"  - path: {_RACINE_DOCKER}/www/index.php\n"
        "    content: |\n" + _indenter(index_php, 6) + "\n"
        "runcmd:\n"
        "  - systemctl enable --now docker\n"
        f"  - [sh, -c, 'cd {_RACINE_DOCKER} && docker compose up -d']\n"
    )


def ip_privee(hebergement_id: str) -> str:
    return f"10.{hash(hebergement_id) % 250}.0.{hash('web') % 250 + 2}"


async def serveur_id(ctx: Contexte, hebergement_id: str, travail: Travail | None = None) -> str:
    """Identifiant Nova du serveur : dans les secrets (posé à la création), sinon le travail."""
    if travail and travail.contexte.get("serveur_id"):
        return str(travail.contexte["serveur_id"])
    try:
        sec = await depot.secrets(ctx, hebergement_id)
    except Exception:  # noqa: BLE001
        sec = {}
    return str(sec.get("serveur_id") or hebergement_id)


def construire_hebergement(ctx: Contexte, corps: m.HebergementCreation) -> m.Hebergement:
    hid = nouvel_id()
    return m.Hebergement(
        id=hid,
        orgId=ctx.org_id,
        domaine=corps.domaine,
        domaineProvisoire=f"h-{hid[:8]}.cloud.dev01.ovh.smile.ci",
        palier=corps.palier,
        serveur=m.Serveur(
            nom=f"srv-{hid[:8]}",
            vcpu={"starter": 1, "pro": 2, "business": 4, "enterprise": 8}.get(corps.palier, 2),
            ramGo={"starter": 2, "pro": 4, "business": 8, "enterprise": 16}.get(corps.palier, 4),
            diskGo={"starter": 40, "pro": 80, "business": 160, "enterprise": 320}.get(
                corps.palier, 80
            ),
            ip="",
            site=corps.site,
            os="Ubuntu 24.04 LTS",
            serveurWeb="Nginx",
            statut="maintenance",
            chargeCpuPct=0.0,
        ),
        php=m.Php(
            versionDefaut=corps.versionPhp or "8.2",
            versionsDisponibles=list(VERSIONS_PHP),
            extensions=[
                m.Extension(nom=e, active=True)
                for e in ["curl", "mbstring", "xml", "mysqli", "gd", "opcache"]
            ],
            limites=m.Limites(memoryLimitMo=256, uploadMaxMo=64, maxExecutionS=30, opcache=True),
        ),
        acces=m.Acces(ftp=True, sftp=True, ftps=False, ssh=False, portSsh=22),
        espaceUtiliseGo=0.0,
        espaceTotalGo=float(
            {"starter": 40, "pro": 80, "business": 160, "enterprise": 320}.get(corps.palier, 80)
        ),
        sauvegarde=m.Sauvegarde(
            frequence="quotidienne",
            heure="02:00",
            retentionJours=14,
            destination="Object Storage — région ABJ",
            immuable=True,
            statut="en_cours",
        ),
        statut="maintenance",
        cree=maintenant(),
    )


def construire_serveur_bases(ctx: Contexte, hebergement_id: str) -> m.ServeurBases:
    return m.ServeurBases(
        id=nouvel_id(),
        hebergementId=hebergement_id,
        serveur=f"db-{hebergement_id[:8]}",
        moteur="mariadb",
        version="MariaDB 10.11",
        actif=True,
        hoteInterne="localhost",
        port=3306,
        bases=[],
        utilisateurs=[],
        quotaMo=1024.0,
        utiliseMo=0.0,
        connexions=m.Connexions1(actives=0, max=20),
        sauvegarde=m.Sauvegarde1(frequence="quotidienne", derniere=maintenant(), retentionJours=7),
        prixMensuel=5000,
    )


def construire_site(
    ctx: Contexte, hebergement_id: str, creation: m.SiteWebCreation, preprod: bool = False
) -> m.SiteWeb:
    return m.SiteWeb(
        id=nouvel_id(),
        hebergementId=hebergement_id,
        hote=creation.hote,
        racine=creation.racine or f"/var/www/{creation.hote}",
        type=creation.type,
        version=creation.version or _version_defaut(creation.type),
        phpVersion=creation.phpVersion or "8.2",
        baseId=None,
        ssl=m.Ssl(
            etat="en_emission" if creation.ssl else "actif",
            emetteur="Let's Encrypt" if creation.ssl else None,
        ),
        espaceMo=0.0,
        visitesMois=0,
        preproduction=m.Preproduction(actif=True, hote=f"preprod.{creation.hote}")
        if preprod
        else None,
        majEnAttente=0,
        securite=m.Securite(waf=False, bruteForce=True, scanMalware=True),
        statut="en_ligne",
    )


def _version_defaut(type_: str) -> str | None:
    return {"wordpress": "6.7", "prestashop": "8.2", "laravel": "11", "php": "8.2"}.get(type_)


SERVICES_PARTAGES = [
    m.ServicePartage(
        id=str(i),
        hebergementId="",
        slug=slug,
        nom=nom,
        solution=solution,
        hote=hote,
        usage=m.Usage1(libelle=libelle, utilise=utilise, total=total, unite=unite),
        version=version,
        sante="ok",
        urlOuverture=f"https://{hote}/",
        actif=True,
    )
    for i, (slug, nom, solution, hote, libelle, utilise, total, unite, version) in enumerate(
        [
            (
                "messagerie",
                "Messagerie",
                "Stalwart",
                "mail.synelia.cloud",
                "Boîtes",
                0,
                10,
                "boîtes",
                "2.5",
            ),
            (
                "drive",
                "Drive",
                "Nextcloud",
                "drive.synelia.cloud",
                "Stockage",
                0,
                100,
                "Go",
                "29.0",
            ),
            (
                "statistiques",
                "Statistiques de visite",
                "Matomo",
                "stats.synelia.cloud",
                "Sites suivis",
                0,
                3,
                "sites",
                "5.2",
            ),
        ]
    )
]


@executeur("hebergement.creer")
class ExecuteurHebergementCreer(Executeur):
    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 1:
            h = await depot.obtenir(ctx, travail.cible_id or "")
            zone = await zone_vps_secrets(ctx)
            srv = amont().creer_serveur(
                nom=h.serveur.nom,
                image_id=image_ubuntu(),
                gabarit_id=gabarit_pour_palier(h.palier),
                reseau_id=zone.get("reseau_id"),
                identifiants=zone,
                org_id=ctx.org_id_ou_none,
                espace_id=None,
                cloud_init=construire_cloud_init(h.domaineProvisoire, h.php.versionDefaut),
            )
            c = dict(travail.contexte)
            c["serveur_id"] = srv["id"]
            await depot.definir_secrets(ctx, h.id, {"serveur_id": srv["id"]})
            c["ip_privee"] = srv.get("ip_privee") or ip_privee(h.id)
            travail.contexte = c
            return f"Serveur amont {srv['id']} créé"
        if index == 2:
            # Routage L7 sur le load balancer partagé de la zone VPS (un pool + une policy
            # `Host()` par hébergement) au lieu d'une IP flottante dédiée : toutes les VM
            # d'hébergement partagent le même réseau et le même point d'entrée public.
            hid = travail.cible_id or ""
            h = await depot.obtenir(ctx, hid)
            c = dict(travail.contexte)
            zone = await zone_vps_secrets(ctx)
            lb_id = zone.get("lb_id")
            n = amont_network()
            pool = n.creer_pool(loadbalancer_id=lb_id, nom=f"pool-{hid[:8]}")
            await depot.definir_secrets(ctx, hid, {"lb_pool_id": pool["id"]})
            c["lb_pool_id"] = pool["id"]
            # `travail.contexte` est réassigné après chaque effet de bord (pas seulement à la
            # fin) : si l'étape échoue en cours de route, `compenser` doit voir exactement ce
            # qui a déjà été créé côté amont pour pouvoir le défaire.
            travail.contexte = c
            membre = n.ajouter_membre(
                pool_id=pool["id"],
                adresse=c["ip_privee"],
                port=80,
                subnet_id=zone.get("sous_reseau_id"),
                loadbalancer_id=lb_id,
            )
            await depot.definir_secrets(ctx, hid, {"lb_membre_id": membre["id"]})
            c["lb_membre_id"] = membre["id"]
            travail.contexte = c
            regle = n.ajouter_regle_hote(
                listener_id=zone.get("lb_listener_id"),
                loadbalancer_id=lb_id,
                pool_id=pool["id"],
                hote=h.domaineProvisoire,
            )
            await depot.definir_secrets(ctx, hid, {"lb_policy_id": regle["policy_id"]})
            c["lb_policy_id"] = regle["policy_id"]
            travail.contexte = c
            return f"Domaine {h.domaineProvisoire} routé sur le load balancer partagé"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        h = await depot.obtenir(ctx, travail.cible_id or "")
        ip = travail.contexte.get("ip_privee") or ip_privee(h.id)
        serveur = h.serveur.model_copy(update={"ip": ip, "statut": "en_ligne", "chargeCpuPct": 12.0})
        await depot.modifier(ctx, h.id, {"serveur": serveur.model_dump(mode="json")})
        base = await depot_bases.creer(
            ctx, construire_serveur_bases(ctx, travail.cible_id or ""), parent_id=travail.cible_id
        )
        travail.contexte = {**travail.contexte, "serveur_bases_id": base.id}
        await depot.definir_statut(ctx, travail.cible_id or "", "en_ligne")

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
        await depot.definir_statut(ctx, travail.cible_id or "", "suspendu")


@executeur("hebergement.supprimer")
class ExecuteurHebergementSupprimer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        sid = await serveur_id(ctx, travail.cible_id or "", travail)
        if sid and sid != (travail.cible_id or ""):
            amont().supprimer_serveur(sid)
        secrets = await depot.secrets(ctx, travail.cible_id or "")
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
        await depot_enfants(ctx, travail.cible_id or "")
        await depot.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("hebergement.redemarrer")
class ExecuteurHebergementRedemarrer(Executeur):
    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 1:
            amont().action(await serveur_id(ctx, travail.cible_id or "", travail), "redemarrage")
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "en_ligne")


@executeur("site.installer")
class ExecuteurSiteInstaller(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_sites.definir_statut(ctx, travail.cible_id or "", "en_ligne")


@executeur("site.supprimer")
class ExecuteurSiteSupprimer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_sites.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("site.analyse_securite")
class ExecuteurSiteAnalyse(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(
            ctx,
            s.id,
            s.model_copy(
                update={"securite": m.Securite(waf=True, bruteForce=True, scanMalware=True)}
            ),
        )


@executeur("site.preproduction")
class ExecuteurSitePreproduction(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(
            ctx,
            s.id,
            s.model_copy(
                update={
                    "preproduction": m.Preproduction(
                        actif=True, hote=f"preprod.{s.hote}", derniereSync=maintenant()
                    ),
                    "statut": "en_ligne",
                }
            ),
        )


@executeur("site.mise_en_production")
class ExecuteurSiteMiseEnProduction(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(
            ctx, s.id, s.model_copy(update={"preproduction": None, "statut": "en_ligne"})
        )


@executeur("site.mise_a_jour")
class ExecuteurSiteMiseAJour(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(ctx, s.id, s.model_copy(update={"majEnAttente": 0}))


@executeur("base.export")
class ExecuteurBaseExport(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        return None


@executeur("base.import")
class ExecuteurBaseImport(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        return None


@executeur("tache.execution")
class ExecuteurTacheExecution(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        t = await depot_taches.obtenir(ctx, travail.cible_id or "")
        await depot_taches.remplacer(
            ctx,
            t.id,
            t.model_copy(update={"derniereExecution": maintenant(), "statut": "ok", "dureeS": 3}),
        )


async def depot_enfants(ctx: Contexte, hebergement_id: str) -> None:
    await depot_comptes.supprimer_enfants(ctx, hebergement_id)
    await depot_taches.supprimer_enfants(ctx, hebergement_id)
    for s in await depot_sites.tous(ctx, filtre=lambda x: x.hebergementId == hebergement_id):
        await depot_sites.supprimer(ctx, s.id, logique=True)
