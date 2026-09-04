"""Parcours de formation, bac à sable, sections de documentation, progression."""

from __future__ import annotations

from typing import Any

from synelia_contract import modeles as m
from synelia_db.modeles import Travail

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

detenteur_bac = Depot("bac_a_sable", m.BacASable, libelle="Bac à sable", champ_nom="statut")
detenteur_progression = Depot(
    "docs_progression",
    m.ProgressionFormation,
    libelle="Progression de formation",
    champ_nom="parcoursSlug",
)


@executeur("docs.bac_a_sable")
class ExecuteurBacASable(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await detenteur_bac.definir_statut(ctx, travail.cible_id or "", "actif")


PARCOURS: list[dict[str, Any]] = [
    {
        "slug": "decouverte",
        "titre": "Découverte de la plateforme",
        "description": "Prenez en main le portail, votre premier Espace Cloud et vos premières VMs.",
        "niveau": "debutant",
        "publicVise": ["org_admin", "espace_admin"],
        "dureeMinutes": 120,
        "certifiant": True,
        "modules": [
            {
                "slug": "mod-premiers-pas",
                "titre": "Premiers pas",
                "format": "article",
                "dureeMinutes": 15,
                "articleId": "kb-01",
                "bacASableRequis": True,
            },
            {
                "slug": "mod-espace",
                "titre": "Créer un Espace Cloud",
                "format": "atelier",
                "dureeMinutes": 30,
                "articleId": "kb-01",
                "bacASableRequis": True,
            },
            {
                "slug": "mod-vm",
                "titre": "Lancer une VM",
                "format": "atelier",
                "dureeMinutes": 30,
                "articleId": "kb-02",
                "bacASableRequis": True,
            },
            {
                "slug": "mod-securite",
                "titre": "Sécurité et MFA",
                "format": "quiz",
                "dureeMinutes": 15,
                "articleId": "kb-04",
            },
            {"slug": "mod-quiz-final", "titre": "Quiz final", "format": "quiz", "dureeMinutes": 30},
        ],
    },
    {
        "slug": "administration",
        "titre": "Administrer son organisation",
        "description": "Gérez les membres, les rôles, la facturation et la supervision.",
        "niveau": "intermediaire",
        "publicVise": ["org_admin", "super_admin"],
        "dureeMinutes": 180,
        "certifiant": True,
        "modules": [
            {
                "slug": "mod-membres",
                "titre": "Inviter et gérer les membres",
                "format": "article",
                "dureeMinutes": 25,
            },
            {
                "slug": "mod-facturation",
                "titre": "Facturation et devis",
                "format": "article",
                "dureeMinutes": 25,
                "articleId": "kb-03",
            },
            {
                "slug": "mod-escalade",
                "titre": "Gérer le support et l'escalade",
                "format": "atelier",
                "dureeMinutes": 20,
            },
            {
                "slug": "mod-quiz",
                "titre": "Quiz de validation",
                "format": "quiz",
                "dureeMinutes": 20,
            },
        ],
    },
    {
        "slug": "services-manages",
        "titre": "Exploiter les services managés",
        "description": "Drive, E-mail, sites web : provisionner et administrer les services managés.",
        "niveau": "avance",
        "publicVise": ["service_admin", "project_owner"],
        "dureeMinutes": 150,
        "certifiant": False,
        "modules": [
            {
                "slug": "mod-drive",
                "titre": "Drive souverain",
                "format": "article",
                "dureeMinutes": 20,
            },
            {
                "slug": "mod-email",
                "titre": "Messagerie professionnelle",
                "format": "article",
                "dureeMinutes": 20,
            },
            {
                "slug": "mod-web",
                "titre": "Hébergement web",
                "format": "atelier",
                "dureeMinutes": 25,
            },
        ],
    },
]

SECTIONS: list[dict[str, Any]] = [
    {
        "titre": "Prise en main",
        "articles": ["Créer un Espace Cloud", "Lancer une VM", "Bac à sable"],
    },
    {"titre": "Administration", "articles": ["Gérer les membres", "Facturation", "Support"]},
    {"titre": "Sécurité", "articles": ["Second facteur", "Clés SSH", "Sauvegardes"]},
    {"titre": "Services managés", "articles": ["Drive", "E-mail", "Hébergement web"]},
]
