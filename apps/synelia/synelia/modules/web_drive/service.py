"""Règles drive (Web Cloud) : dépôt, exécuteur d'activation, amont Nextcloud."""

from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_openstack import nextcloud

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
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


def amont() -> nextcloud.NextcloudSimule:
    return nextcloud.choisir_nextcloud()


def palier(cle: str) -> dict:
    return PALIERS.get(cle, PALIERS["starter"])


@executeur("web.drive.activate")
class ExecuteurDriveActivate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        drive = await depot.obtenir(ctx, travail.cible_id or "")
        await depot.modifier(ctx, drive.id, {"actif": True})
