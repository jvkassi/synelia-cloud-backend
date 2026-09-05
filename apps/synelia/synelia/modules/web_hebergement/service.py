from __future__ import annotations

from typing import Any

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel import erreurs
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import jeton_opaque, nouvel_id
from synelia_openstack import fournisseur
from synelia_openstack.compute import ComputeOpenStack, ComputeSimule
from synelia_openstack.identite import IdentiteOpenStack, IdentiteSimule
from synelia_openstack.network import NetworkOpenStack, NetworkSimule
from synelia_openstack.ssh import SshReel, SshSimule

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


def amont_ssh() -> SshSimule:
    """SSH vers une VM d'hébergement déjà en service — installation d'une application
    supplémentaire après coup (`router_sites`), pas à la création de la VM elle-même."""
    return fournisseur(SshSimule, SshReel)


def amont_identite() -> IdentiteSimule:
    """Keystone/Neutron admin — IP flottante **dédiée à l'accès SSH backend** d'une VM
    d'hébergement. Le réseau privé de la zone VPS (`vps-zone-net`, 10.90.0.0/16) n'est
    routable que depuis l'intérieur du lab OpenStack : le backend (hors du lab) ne peut
    joindre une VM que par une IP flottante. Le trafic HTTP public, lui, ne passe jamais par
    cette IP : uniquement par le load balancer partagé (`amont_network()`), c'est pour ça que
    `web_hebergement` n'avait jusqu'ici jamais eu besoin d'IP flottante par VM."""
    return fournisseur(IdentiteSimule, IdentiteOpenStack)


NOM_KEYPAIR_ZONE = "synelia-hebergement"


async def assurer_cle_ssh_zone(ctx: Contexte) -> dict[str, str]:
    """Clé SSH unique de la zone VPS, générée une fois puis réutilisée par toutes les VM
    d'hébergement : la clé privée est stockée dans les secrets de l'Espace Cloud de la zone
    (comme `lb_id`, `reseau_id`…), la clé publique est enregistrée comme keypair Nova
    (`assurer_keypair`, idempotent) et injectée dans le cloud-init de chaque nouvelle VM
    (`construire_cloud_init`). Les VM déjà créées avant ce câblage ne l'ont pas : le
    cloud-init ne s'exécute qu'au premier démarrage, on ne peut pas les retrofit."""
    from synelia_kernel.config import reglages

    from synelia.modules.espaces.service import depot as depot_espaces

    zone = await zone_vps_secrets(ctx)
    if zone.get("ssh_prive") and zone.get("ssh_publique"):
        # Clé déjà générée : on réenregistre quand même le keypair Nova (idempotent, un
        # `find_keypair` avant tout `create_keypair`) plutôt que de faire confiance à sa
        # seule présence dans les secrets — un keypair Nova peut disparaître (recréation du
        # projet, erreur d'appel initiale) sans que les secrets ne bougent.
        nom = zone.get("ssh_cle_nom") or NOM_KEYPAIR_ZONE
        amont().assurer_keypair(nom, zone["ssh_publique"], identifiants=zone)
        return {"ssh_prive": zone["ssh_prive"], "ssh_publique": zone["ssh_publique"], "ssh_cle_nom": nom}
    r = reglages()
    if not r.vps_zone_espace_id:
        return {}
    cle = amont_ssh().generer_cle()
    amont().assurer_keypair(NOM_KEYPAIR_ZONE, cle["publique"], identifiants=zone)
    secrets = {
        "ssh_cle_nom": NOM_KEYPAIR_ZONE,
        "ssh_prive": cle["prive"],
        "ssh_publique": cle["publique"],
    }
    await depot_espaces.definir_secrets(
        ctx, r.vps_zone_espace_id, secrets, org_id=r.vps_zone_org_id
    )
    return secrets


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


def construire_cloud_init(domaine: str, version_php: str, cle_publique: str | None = None) -> str:
    """`#cloud-config` : Docker + Traefik (reverse-proxy HTTP sur :80) et un conteneur PHP pour
    `domaine`, routé par son `Host()`. Nextcloud (« Drive ») est ajouté plus tard au même
    `docker-compose.yml`, sur cette même VM, quand `web_drive` est activé pour l'organisation
    (voir `web_drive.service`) — un Traefik par VM d'hébergement, tout le reste en conteneurs
    Docker derrière lui.

    Traefik route via son *provider fichier* (config statique dans `traefik-dynamic/`), pas le
    provider Docker : le Docker Engine récent (>= API 1.44, cf. `docker.io` sur Ubuntu 24.04)
    rejette le client Docker vendorisé par Traefik (bloqué sur l'API 1.24, y compris en v3.5) —
    `Error response from daemon: client version 1.24 is too old`. Bug de compatibilité amont
    réel, constaté en direct (VM de debug jetable + SSH), pas un problème de labels. Le provider
    fichier n'a pas besoin du socket Docker : chaque service se route par son nom de conteneur
    sur le réseau `synelia` (résolution DNS interne de Compose)."""
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

  site:
    image: php:{version_php}-apache
    restart: unless-stopped
    volumes:
      - {_RACINE_DOCKER}/www:/var/www/html:ro
    networks:
      - synelia

networks:
  synelia:
    name: synelia
"""
    routage = f"""http:
  routers:
    site:
      rule: "Host(`{domaine}`)"
      entryPoints:
        - web
      service: site
  services:
    site:
      loadBalancer:
        servers:
          - url: "http://site:80"
"""
    index_php = (
        "<?php\n"
        f'echo "<h1>{domaine}</h1><p>Synelia Web Hebergement -- PHP " . phpversion() . "</p>";\n'
    )
    # Clé SSH backend (`assurer_cle_ssh_zone`) : injectée pour root — c'est elle qui permet
    # à `router_sites` d'installer une application supplémentaire après coup, sur une VM
    # déjà en service (cloud-init ne s'exécute qu'au premier démarrage, on ne peut pas
    # revenir en arrière sur une VM déjà créée sans cette clé).
    acces_ssh = (
        f"disable_root: false\nssh_authorized_keys:\n  - {cle_publique}\n" if cle_publique else ""
    )
    return (
        "#cloud-config\n"
        "package_update: true\n"
        f"{acces_ssh}"
        "packages:\n"
        "  - docker.io\n"
        "  - docker-compose-v2\n"
        "write_files:\n"
        f"  - path: {_RACINE_DOCKER}/docker-compose.yml\n"
        "    content: |\n" + _indenter(compose, 6) + "\n"
        f"  - path: {_RACINE_DOCKER}/traefik-dynamic/site.yml\n"
        "    content: |\n" + _indenter(routage, 6) + "\n"
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


async def ip_gestion_hebergement(ctx: Contexte, hebergement: m.Hebergement) -> str | None:
    """Adresse à laquelle SSH peut joindre la VM d'hébergement : l'IP flottante de gestion
    (`ssh_fip_id`/`ssh_ip`, posée à la création — voir `amont_identite()`), sinon l'IP privée
    en mode simulé (jamais reproché : aucun appel réseau n'y est réellement fait). Une VM créée
    avant ce câblage n'a ni l'une ni l'autre utilisable en réel : `None`."""
    try:
        secrets = await depot.secrets(ctx, hebergement.id)
    except Exception:  # noqa: BLE001
        secrets = {}
    return secrets.get("ssh_ip") or hebergement.serveur.ip or None


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
        statut="installation",
    )


def _version_defaut(type_: str) -> str | None:
    return {"wordpress": "6.7", "prestashop": "8.2", "laravel": "11", "php": "8.2"}.get(type_)


# `SiteWeb.type` (contrat) ne distingue que 5 valeurs (`wordpress`, `prestashop`, `php`,
# `statique`, `laravel`) : Ghost et Dolibarr sont posés côté catalogue frontend sous
# `type: 'php'`, comme Joomla l'était avant eux. Plutôt qu'étendre le contrat pour un simple
# discriminant, on retrouve l'application réelle depuis le premier label du nom d'hôte — le
# catalogue de `/app/web/applications` nomme déjà ses hôtes `ghost.<domaine>`, `dolibarr.
# <domaine>`… Une installation « PHP générique » depuis le formulaire libre (hôte quelconque)
# retombe sur `php`, ce qui est le bon défaut.
_APPLICATIONS_PHP = {"ghost", "dolibarr"}


def application_pour_site(site_type: str, hote: str) -> str:
    if site_type in {"wordpress", "prestashop", "statique"}:
        return site_type
    label = hote.split(".", 1)[0].lower()
    if site_type == "php" and label in _APPLICATIONS_PHP:
        return label
    return "php"


def _slug_site(site_id: str) -> str:
    return site_id[:8]


def construire_site_stack(
    application: str, hote: str, php_version: str, mot_de_passe: str, site_id: str
) -> tuple[str, str, dict[str, str]]:
    """`docker-compose.yml` + route Traefik + fichiers additionnels pour installer
    `application` sur une VM d'hébergement **déjà en service**, à côté d'autres sites : chaque
    service est nommé par le short id du site (jamais par son rôle générique `app`/`db`) pour
    ne jamais entrer en collision avec un autre site installé sur la même VM, tous rattachés
    au même réseau Docker externe `synelia` créé par le compose principal de la VM
    (`construire_cloud_init`)."""
    sid = _slug_site(site_id)
    app_svc = f"app-{sid}"
    db_svc = f"db-{sid}"
    racine = f"{_RACINE_DOCKER}/sites/{site_id}"
    fichiers: dict[str, str] = {}
    port = 80
    if application == "wordpress":
        services = f"""  {db_svc}:
    image: mariadb:11
    restart: unless-stopped
    environment:
      - MARIADB_ROOT_PASSWORD={mot_de_passe}
      - MARIADB_DATABASE=wordpress
      - MARIADB_USER=wordpress
      - MARIADB_PASSWORD={mot_de_passe}
    volumes:
      - {racine}/db:/var/lib/mysql
    networks:
      - synelia

  {app_svc}:
    image: wordpress:php{php_version}-apache
    restart: unless-stopped
    depends_on:
      - {db_svc}
    environment:
      - WORDPRESS_DB_HOST={db_svc}
      - WORDPRESS_DB_NAME=wordpress
      - WORDPRESS_DB_USER=wordpress
      - WORDPRESS_DB_PASSWORD={mot_de_passe}
    volumes:
      - {racine}/www:/var/www/html
    networks:
      - synelia
"""
    elif application == "prestashop":
        services = f"""  {db_svc}:
    image: mariadb:11
    restart: unless-stopped
    environment:
      - MARIADB_ROOT_PASSWORD={mot_de_passe}
      - MARIADB_DATABASE=prestashop
      - MARIADB_USER=prestashop
      - MARIADB_PASSWORD={mot_de_passe}
    volumes:
      - {racine}/db:/var/lib/mysql
    networks:
      - synelia

  {app_svc}:
    image: prestashop/prestashop:8-apache
    restart: unless-stopped
    depends_on:
      - {db_svc}
    environment:
      - DB_SERVER={db_svc}
      - DB_NAME=prestashop
      - DB_USER=prestashop
      - DB_PASSWD={mot_de_passe}
      - PS_INSTALL_AUTO=1
      - PS_DOMAIN={hote}
      - ADMIN_MAIL=admin@{hote}
      - ADMIN_PASSWD={mot_de_passe}
    volumes:
      - {racine}/www:/var/www/html
    networks:
      - synelia
"""
    elif application == "ghost":
        port = 2368
        services = f"""  {app_svc}:
    image: ghost:5-alpine
    restart: unless-stopped
    environment:
      - url=http://{hote}
      - database__client=sqlite3
      - database__connection__filename=/var/lib/ghost/content/data/ghost.db
      - database__useNullAsDefault=true
    volumes:
      - {racine}/content:/var/lib/ghost/content
    networks:
      - synelia
"""
    elif application == "dolibarr":
        services = f"""  {db_svc}:
    image: mariadb:11
    restart: unless-stopped
    environment:
      - MARIADB_ROOT_PASSWORD={mot_de_passe}
      - MARIADB_DATABASE=dolibarr
      - MARIADB_USER=dolibarr
      - MARIADB_PASSWORD={mot_de_passe}
    volumes:
      - {racine}/db:/var/lib/mysql
    networks:
      - synelia

  {app_svc}:
    image: dolibarr/dolibarr:latest
    restart: unless-stopped
    depends_on:
      - {db_svc}
    environment:
      - DOLI_DB_HOST={db_svc}
      - DOLI_DB_USER=dolibarr
      - DOLI_DB_PASSWORD={mot_de_passe}
      - DOLI_DB_NAME=dolibarr
      - DOLI_URL_ROOT=http://{hote}
      - DOLI_ADMIN_LOGIN=admin
      - DOLI_ADMIN_PASSWORD={mot_de_passe}
      - DOLI_INSTALL_AUTO=1
    volumes:
      - {racine}/html:/var/www/html
      - {racine}/doc:/var/www/documents
    networks:
      - synelia
"""
    elif application == "statique":
        fichiers[f"{racine}/www/index.html"] = (
            f"<!doctype html><html><head><title>{hote}</title></head><body>"
            f"<h1>{hote}</h1><p>Synelia Web Cloud — site statique.</p></body></html>\n"
        )
        services = f"""  {app_svc}:
    image: nginx:alpine
    restart: unless-stopped
    volumes:
      - {racine}/www:/usr/share/nginx/html:ro
    networks:
      - synelia
"""
    else:  # `php` générique et `laravel` : même patron que le site par défaut de la VM
        fichiers[f"{racine}/www/index.php"] = (
            "<?php\n"
            f'echo "<h1>{hote}</h1><p>Synelia Web Cloud -- PHP " . phpversion() . "</p>";\n'
        )
        services = f"""  {app_svc}:
    image: php:{php_version}-apache
    restart: unless-stopped
    volumes:
      - {racine}/www:/var/www/html:ro
    networks:
      - synelia
"""
    compose = f"services:\n{services}\nnetworks:\n  synelia:\n    external: true\n    name: synelia\n"
    routage = f"""http:
  routers:
    {app_svc}:
      rule: "Host(`{hote}`)"
      entryPoints:
        - web
      service: {app_svc}
  services:
    {app_svc}:
      loadBalancer:
        servers:
          - url: "http://{app_svc}:{port}"
"""
    return compose, routage, fichiers


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
            cle = await assurer_cle_ssh_zone(ctx)
            srv = amont().creer_serveur(
                nom=h.serveur.nom,
                image_id=image_ubuntu(),
                gabarit_id=gabarit_pour_palier(h.palier),
                reseau_id=zone.get("reseau_id"),
                identifiants=zone,
                org_id=ctx.org_id_ou_none,
                espace_id=None,
                cle_ssh=cle.get("ssh_cle_nom"),
                cloud_init=construire_cloud_init(
                    h.domaineProvisoire, h.php.versionDefaut, cle.get("ssh_publique")
                ),
            )
            c = dict(travail.contexte)
            c["serveur_id"] = srv["id"]
            await depot.definir_secrets(ctx, h.id, {"serveur_id": srv["id"]})
            c["ip_privee"] = srv.get("ip_privee") or ip_privee(h.id)
            travail.contexte = c
            # IP flottante dédiée à l'accès SSH backend (jamais au trafic HTTP public, qui ne
            # passe que par le load balancer partagé) : sans elle, `router_sites` ne peut pas
            # joindre cette VM après coup pour y installer une application supplémentaire —
            # le réseau privé de la zone VPS n'est routable que depuis l'intérieur du lab.
            fip = amont_identite().creer_ip_flottante(zone.get("projet_id"))
            ip_gestion = amont_identite().associer_ip_flottante(fip.get("id"), srv["id"])
            amont_network().assurer_regle_ssh(srv["id"])
            c["ssh_fip_id"] = fip.get("id")
            c["ssh_ip"] = ip_gestion or fip.get("adresse")
            travail.contexte = c
            await depot.definir_secrets(
                ctx, h.id, {"ssh_fip_id": fip.get("id") or "", "ssh_ip": c["ssh_ip"] or ""}
            )
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
        fip_id = travail.contexte.get("ssh_fip_id")
        if fip_id:
            amont_identite().supprimer_ip_flottante(fip_id)
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
        try:
            secrets_avant = await depot.secrets(ctx, travail.cible_id or "")
        except Exception:  # noqa: BLE001
            secrets_avant = {}
        fip_id = secrets_avant.get("ssh_fip_id")
        if fip_id:
            amont_identite().supprimer_ip_flottante(fip_id)
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
    """Installe une application Docker supplémentaire sur une VM d'hébergement **déjà en
    service**, par SSH (`amont_ssh()`, clé de la zone VPS posée par `assurer_cle_ssh_zone`
    à la création de la VM) : écrit un `docker-compose.yml` dédié sous
    `_RACINE_DOCKER/sites/<siteId>/`, une route Traefik de plus (le provider fichier la
    reprend seul, sans redémarrage — `--providers.file.watch=true`), démarre les conteneurs,
    puis ajoute une règle L7 de plus sur le pool **déjà existant** de l'hébergement (même VM,
    même membre : inutile d'en recréer un, contrairement à `web_hebergement`/`web_drive` qui
    provisionnent chacun leur propre VM)."""

    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        site = await depot_sites.obtenir(ctx, travail.cible_id or "")
        if index == 0:
            hebergement = await depot.obtenir(ctx, site.hebergementId)
            zone = await zone_vps_secrets(ctx)
            cle_privee = zone.get("ssh_prive")
            ip = await ip_gestion_hebergement(ctx, hebergement)
            if not cle_privee or not ip:
                raise erreurs.amont_indisponible(
                    "hébergement (SSH)",
                    "Aucune IP de gestion SSH backend disponible pour cette VM : soit la "
                    "zone VPS n'est pas encore initialisée, soit cette VM a été créée avant "
                    "le câblage SSH/IP flottante (non rattrapable a posteriori).",
                )
            application = application_pour_site(site.type, site.hote)
            mdp = jeton_opaque(16)
            compose, routage, fichiers = construire_site_stack(
                application, site.hote, site.phpVersion, mdp, site.id
            )
            ssh = amont_ssh()
            racine = f"{_RACINE_DOCKER}/sites/{site.id}"
            ssh.ecrire_fichier(ip, cle_privee, f"{racine}/docker-compose.yml", compose)
            for chemin, contenu in fichiers.items():
                ssh.ecrire_fichier(ip, cle_privee, chemin, contenu)
            ssh.ecrire_fichier(
                ip, cle_privee, f"{_RACINE_DOCKER}/traefik-dynamic/site-{site.id}.yml", routage
            )
            # MariaDB (le cas échéant) est créée par ce même `docker compose up -d`, avec
            # l'application : pas d'étape séparée à distinguer côté SSH.
            ssh.executer(ip, cle_privee, f"cd {racine} && docker compose up -d")
            await depot_sites.definir_secrets(
                ctx, site.id, {"application": application, "mot_de_passe": mdp}
            )
            c = dict(travail.contexte)
            c["application"] = application
            travail.contexte = c
            return f"{application} installé sur {hebergement.domaineProvisoire}"
        if index == 2:
            hebergement = await depot.obtenir(ctx, site.hebergementId)
            heb_secrets = await depot.secrets(ctx, hebergement.id)
            zone = await zone_vps_secrets(ctx)
            regle = amont_network().ajouter_regle_hote(
                listener_id=zone.get("lb_listener_id"),
                loadbalancer_id=zone.get("lb_id"),
                pool_id=heb_secrets.get("lb_pool_id"),
                hote=site.hote,
            )
            await depot_sites.definir_secrets(ctx, site.id, {"lb_policy_id": regle["policy_id"]})
            c = dict(travail.contexte)
            c["lb_policy_id"] = regle["policy_id"]
            travail.contexte = c
            return f"Domaine {site.hote} routé sur le load balancer partagé"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_sites.definir_statut(ctx, travail.cible_id or "", "en_ligne")

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        site = await depot_sites.obtenir(ctx, travail.cible_id or "")
        try:
            secrets = await depot_sites.secrets(ctx, site.id)
        except Exception:  # noqa: BLE001
            secrets = {}
        zone = await zone_vps_secrets(ctx)
        policy_id = travail.contexte.get("lb_policy_id") or secrets.get("lb_policy_id")
        if policy_id:
            amont_network().supprimer_regle_hote(policy_id, loadbalancer_id=zone.get("lb_id"))
        hebergement = await depot.trouver(ctx, site.hebergementId)
        cle_privee = zone.get("ssh_prive")
        ip = hebergement and await ip_gestion_hebergement(ctx, hebergement)
        if hebergement and cle_privee and ip:
            racine = f"{_RACINE_DOCKER}/sites/{site.id}"
            amont_ssh().executer(
                ip,
                cle_privee,
                f"cd {racine} && docker compose down -v; rm -rf {racine} "
                f"{_RACINE_DOCKER}/traefik-dynamic/site-{site.id}.yml",
            )
        await depot_sites.definir_statut(ctx, site.id, "suspendu")


@executeur("site.supprimer")
class ExecuteurSiteSupprimer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        site = await depot_sites.obtenir(ctx, travail.cible_id or "")
        try:
            secrets = await depot_sites.secrets(ctx, site.id)
        except Exception:  # noqa: BLE001
            secrets = {}
        zone = await zone_vps_secrets(ctx)
        policy_id = secrets.get("lb_policy_id")
        if policy_id:
            amont_network().supprimer_regle_hote(policy_id, loadbalancer_id=zone.get("lb_id"))
        hebergement = await depot.trouver(ctx, site.hebergementId)
        cle_privee = zone.get("ssh_prive")
        ip = hebergement and await ip_gestion_hebergement(ctx, hebergement)
        if hebergement and cle_privee and ip:
            racine = f"{_RACINE_DOCKER}/sites/{site.id}"
            amont_ssh().executer(
                ip,
                cle_privee,
                f"cd {racine} && docker compose down -v; rm -rf {racine} "
                f"{_RACINE_DOCKER}/traefik-dynamic/site-{site.id}.yml",
            )
        await depot_sites.supprimer(ctx, site.id, logique=True)


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
