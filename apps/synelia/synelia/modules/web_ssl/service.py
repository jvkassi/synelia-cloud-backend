"""Règles SSL (Web Cloud) : offre, dépôt, exécuteurs, amont ACME."""

from __future__ import annotations

from datetime import date, timedelta

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_openstack import acme

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot(
    "web_certificat",
    m.Certificat,
    libelle="Certificat",
    champ_nom="hote",
    champ_statut="etat",
    champs_recherche=("hote", "hebergementId"),
)

DEFAULT_EMETTEUR = "Sectigo"
ALTERNATE_EMETTEUR = "Let's Encrypt"

OFFRES = [
    {
        "type": "letsencrypt",
        "nom": "DV — Let's Encrypt",
        "emetteur": ALTERNATE_EMETTEUR,
        "prixAnnuel": 0,
        "delaiEmission": "~ 3 min",
        "garantie": "Sans garantie commerciale",
        "caracteristiques": [
            "Validation DNS ou HTTP",
            "Durée 90 jours, renouvellement automatique",
            "Un hôte",
        ],
    },
    {
        "type": "dv",
        "nom": "DV — Validation de domaine",
        "emetteur": DEFAULT_EMETTEUR,
        "prixAnnuel": 35000,
        "delaiEmission": "~ 30 min",
        "garantie": "500 000 FCFA",
        "caracteristiques": ["Validation par email, DNS ou HTTP", "Durée 1 an", "Un hôte"],
    },
    {
        "type": "wildcard",
        "nom": "Wildcard — *.<domaine>",
        "emetteur": DEFAULT_EMETTEUR,
        "prixAnnuel": 75000,
        "delaiEmission": "~ 2 h",
        "garantie": "500 000 FCFA",
        "caracteristiques": ["Sous-domaines illimités", "Validation DNS", "Durée 1 an"],
    },
    {
        "type": "ov",
        "nom": "OV — Validation d'organisation",
        "emetteur": DEFAULT_EMETTEUR,
        "prixAnnuel": 150000,
        "delaiEmission": "1 à 3 jours",
        "garantie": "1 250 000 FCFA",
        "caracteristiques": ["Validation de l'organisation", "Durée 1 an", "Jusqu'à 3 hôtes"],
    },
    {
        "type": "ev",
        "nom": "EV — Validation étendue",
        "emetteur": DEFAULT_EMETTEUR,
        "prixAnnuel": 350000,
        "delaiEmission": "2 à 5 jours",
        "garantie": "1 750 000 FCFA",
        "caracteristiques": [
            "Barre d'adresse verte",
            "Validation étendue d'organisation",
            "Durée 1 an",
        ],
    },
]


def amont() -> acme.AcmeSimule:
    return acme.choisir_acme()


def offre(type_: str) -> dict:
    return next((o for o in OFFRES if o["type"] == type_), OFFRES[0])


def duree_jours(type_: str, duree_annees: int | None) -> int:
    if type_ == "letsencrypt":
        return 90
    return 365 * (duree_annees or 1)


def nova_expiration(type_: str, duree_annees: int | None) -> date:
    return date.today() + timedelta(days=duree_jours(type_, duree_annees))


@executeur("web.ssl.renew")
class ExecuteurCertificatRenew(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        c = await depot.obtenir(ctx, travail.cible_id or "")
        duree = travail.contexte.get("duree_jours", duree_jours(c.type, None))
        await depot.modifier(
            ctx,
            c.id,
            {
                "etat": "actif",
                "emisLe": date.today(),
                "expire": date.today() + timedelta(days=duree),
            },
        )


@executeur("web.ssl.commande")
class ExecuteurCertificatCommande(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        c = await depot.obtenir(ctx, travail.cible_id or "")
        duree = travail.contexte.get("duree_jours", duree_jours(c.type, None))
        await depot.modifier(
            ctx,
            c.id,
            {
                "etat": "actif",
                "emisLe": date.today(),
                "expire": date.today() + timedelta(days=duree),
            },
        )


ETAPES_COMMANDE = [
    {"nom": "Publier la demande de signature", "dureeS": 5},
    {"nom": "Soumettre à l'autorité de certification", "dureeS": 12},
    {"nom": "Émettre le certificat", "dureeS": 22},
    {"nom": "Installer et recharger le serveur", "dureeS": 8},
]
