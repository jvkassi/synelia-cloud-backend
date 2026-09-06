"""Projets applicatifs : projets, services, domaines, routage et zone applicative."""

from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_openstack.k8s_workload import obtenir as k8s

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot_projet = Depot(
    "projet",
    m.Projet,
    libelle="Projet applicatif",
    champ_nom="nom",
    champs_recherche=("nom", "description"),
)
depot_service = Depot(
    "projet_service",
    m.ServiceProjet,
    libelle="Service de projet",
    champ_nom="nom",
    champs_recherche=("nom",),
)
depot_domaine = Depot(
    "domaine_applicatif",
    m.DomaineApplicatif,
    libelle="Domaine applicatif",
    champ_nom="hote",
    champs_recherche=("hote", "chemin"),
)

ZONE = "apps.synelia.cloud"
INGRESS = [
    m.Ingres(site="ABJ", ip="196.201.103.10", ipv6="2c0f:f4c0:1000::10"),
    m.Ingres(site="GBM", ip="197.243.40.10", ipv6="2c0f:f4c1:1000::10"),
]


def hote_interne(service: m.ServiceProjet, projet: m.Projet) -> str:
    return f"{service.nom}.{projet.nom}.svc.cluster.local"


def namespace_projet(projet: m.Projet) -> str:
    """Un projet applicatif = un namespace Kubernetes, 1:1, sur le cluster PaaS."""
    return f"projet-{projet.id}"


def nom_k8s_service(service: m.ServiceProjet) -> str:
    """Nom du Deployment/Service Kubernetes pour ce service.

    `service.id` (UUIDv7) commence souvent par un chiffre : valide pour un nom de
    Deployment (DNS-1123) mais pas pour un `Service`, qui exige DNS-1035 (débute par
    une lettre) — vérifié en direct : `01a0771...` fait échouer la création du
    `Service` avec 422. Le préfixe `svc-` couvre les deux.
    """
    return f"svc-{service.id}"


PORT_DEFAUT_SERVICE = 8080

# Image Docker officielle par moteur de base managée — utilisée quand un service
# `base` n'a pas de `source` explicite (c'est le cas normal : une base se choisit par
# moteur/version, pas par image). `clickhouse` n'a pas d'image `clickhouse` officielle
# sous ce nom, elle vit sous `clickhouse/clickhouse-server`.
MOTEUR_IMAGE: dict[str, str] = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "mongodb": "mongo",
    "redis": "redis",
    "clickhouse": "clickhouse/clickhouse-server",
}

# Port d'écoute d'usage de chaque moteur — même mapping que le front (`PORT_MOTEUR` de
# `nouveau-service`/`projets/[projet]/vue.tsx`), pour que le port réellement exposé par
# le conteneur corresponde à ce que la fiche du service annonce.
MOTEUR_PORT: dict[str, int] = {
    "postgresql": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "mongodb": 27017,
    "redis": 6379,
    "clickhouse": 9000,
}


def image_service(service: m.ServiceProjet) -> str | None:
    """L'image réelle à déployer pour ce service, ou `None` s'il n'y a rien à exécuter.

    Deux cas donnent une image réelle : une `source` explicite de type `image` (le
    flux « Modèle du catalogue », ou un appel direct de l'API qui la fournit), ou un
    service `base` dont le `moteur` se traduit en image officielle. Une `source` de
    type `git` (pas de pipeline de build ici) ou l'absence totale de source (coquille
    créée par le flux nom+description seul) ne donnent délibérément aucune image : on
    ne invente pas un déploiement là où le produit n'en promet pas.
    """
    if service.source and service.source.type == "image" and service.source.ref:
        return service.source.ref
    if service.type == "base" and service.moteur:
        image = MOTEUR_IMAGE.get(service.moteur)
        if image:
            return f"{image}:{service.version or 'latest'}"
    return None


def env_base(service: m.ServiceProjet, secrets: dict[str, str]) -> dict[str, str]:
    """Variables d'environnement d'amorçage de l'image officielle de `service.moteur`."""
    mdp = secrets.get("motDePasse", "")
    utilisateur = secrets.get("utilisateur") or f"{service.nom}_user"
    base = secrets.get("base") or service.nom
    if service.moteur == "postgresql":
        return {"POSTGRES_USER": utilisateur, "POSTGRES_PASSWORD": mdp, "POSTGRES_DB": base}
    if service.moteur == "mysql":
        return {
            "MYSQL_ROOT_PASSWORD": mdp,
            "MYSQL_DATABASE": base,
            "MYSQL_USER": utilisateur,
            "MYSQL_PASSWORD": mdp,
        }
    if service.moteur == "mariadb":
        return {
            "MARIADB_ROOT_PASSWORD": mdp,
            "MARIADB_DATABASE": base,
            "MARIADB_USER": utilisateur,
            "MARIADB_PASSWORD": mdp,
        }
    if service.moteur == "mongodb":
        return {
            "MONGO_INITDB_ROOT_USERNAME": utilisateur,
            "MONGO_INITDB_ROOT_PASSWORD": mdp,
            "MONGO_INITDB_DATABASE": base,
        }
    return {}


async def _appliquer_service_k8s(ctx: Contexte, service: m.ServiceProjet, projet: m.Projet) -> bool:
    """Déploie réellement `service` sur le cluster PaaS s'il a une image. Renvoie si
    quelque chose tourne vraiment (pour choisir le statut final : `running`/`stopped`)."""
    image = image_service(service)
    if not image:
        return False
    env = {}
    if service.type == "base" and service.moteur:
        secrets = await depot_service.secrets(ctx, service.id)
        env = env_base(service, secrets)
    port = service.portConteneur or (MOTEUR_PORT.get(service.moteur or "")) or PORT_DEFAUT_SERVICE
    k8s().creer_namespace(namespace_projet(projet))
    k8s().appliquer_deployment(
        namespace_projet(projet),
        nom_k8s_service(service),
        image,
        replicas=1,
        env=env,
        ports=[port],
        cpu=service.ressources.cpu,
        ram_mo=service.ressources.ramMo,
    )
    return True


@executeur("projet_service.create")
class ExecuteurServiceCreate(Executeur):
    """Sert aussi « démarrage » et « redémarrage » (même type de travail, cf. router)."""

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        service = await depot_service.obtenir(ctx, travail.cible_id or "")
        projet = await depot_projet.obtenir(ctx, service.projetId)
        tourne = await _appliquer_service_k8s(ctx, service, projet)
        await depot_service.definir_statut(ctx, service.id, "running" if tourne else "stopped")


@executeur("projet_service.stopped")
class ExecuteurServiceStopped(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        service = await depot_service.obtenir(ctx, travail.cible_id or "")
        projet = await depot_projet.obtenir(ctx, service.projetId)
        image = image_service(service)
        if image:
            # Ramène les réplicas à 0 plutôt que de supprimer le Deployment : un
            # redémarrage réapplique juste le même objet à 1 réplica, pas de
            # recréation de zéro (même motif que `ExecuteurComposantArret`).
            k8s().appliquer_deployment(
                namespace_projet(projet), nom_k8s_service(service), image, replicas=0
            )
        await depot_service.definir_statut(ctx, service.id, "stopped")


@executeur("projet_service.delete")
class ExecuteurServiceDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        service = await depot_service.obtenir(ctx, travail.cible_id or "")
        projet = await depot_projet.obtenir(ctx, service.projetId)
        k8s().supprimer_deployment(namespace_projet(projet), nom_k8s_service(service))
        await depot_service.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("projet.delete")
class ExecuteurProjetDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        projet = await depot_projet.obtenir(ctx, travail.cible_id or "")
        k8s().supprimer_namespace(namespace_projet(projet))
        await depot_projet.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("domaine_certificat.emission")
class ExecuteurCertificat(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_domaine.modifier(
            ctx,
            travail.cible_id or "",
            {
                "certificat": m.Certificat1(etat="actif", emetteur="Let's Encrypt").model_dump(
                    mode="json"
                )
            },
        )
