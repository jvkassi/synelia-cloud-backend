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


@executeur("projet_service.create")
class ExecuteurServiceCreate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_service.definir_statut(ctx, travail.cible_id or "", "running")


@executeur("projet_service.stopped")
class ExecuteurServiceStopped(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_service.definir_statut(ctx, travail.cible_id or "", "stopped")


@executeur("projet_service.delete")
class ExecuteurServiceDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
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
