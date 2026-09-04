"""Règles messagerie (Web Cloud) : dépôt, exécuteur d'activation, amont Stalwart."""

from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_openstack import stalwart

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot(
    "web_messagerie",
    m.Messagerie,
    libelle="Messagerie",
    champ_nom="domaine",
    champ_statut="actif",
    champs_recherche=("domaine",),
)

PALIERS = {
    "starter": {"boites": 5, "prixSiege": 1000},
    "pro": {"boites": 25, "prixSiege": 800},
    "business": {"boites": 100, "prixSiege": 700},
}

DMARC = "v=DMARC1; p=none; rua=mailto:dmarc@synelia.cloud"


def amont() -> stalwart.StalwartSimule:
    return stalwart.choisir_stalwart()


def palier(cle: str) -> dict:
    return PALIERS.get(cle, PALIERS["starter"])


@executeur("web.email.activate")
class ExecuteurMessagerieActivate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        mess = await depot.obtenir(ctx, travail.cible_id or "")
        await depot.modifier(
            ctx,
            mess.id,
            {
                "actif": True,
                "authentification": {"spf": "valide", "dkim": "valide", "dmarc": DMARC},
            },
        )
