"""Plesk : serveur d'hébergement, bases, comptes fichiers, sites, PHP."""

from __future__ import annotations

from synelia_kernel.ids import nouvel_id


class PleskSimule:
    def creer_serveur(self, palier: str, site: str) -> str:
        return f"srv-{palier}-{nouvel_id()[:8]}"

    def supprimer_serveur(self, serveur: str) -> None:
        return None

    def redemarrer(self, serveur: str) -> None:
        return None

    def creer_compte_fichiers(self, serveur: str, utilisateur: str) -> None:
        return None

    def modifier_compte_fichiers(self, serveur: str, utilisateur: str) -> None:
        return None

    def supprimer_compte_fichiers(self, serveur: str, utilisateur: str) -> None:
        return None

    def creer_site(self, serveur: str, hote: str) -> None:
        return None

    def analyser_securite(self, serveur: str, hote: str) -> None:
        return None

    def creer_preproduction(self, serveur: str, hote: str) -> None:
        return None

    def publier_preproduction(self, serveur: str, hote: str) -> None:
        return None

    def creer_base(self, serveur: str, nom: str) -> None:
        return None

    def supprimer_base(self, serveur: str, nom: str) -> None:
        return None

    def creer_utilisateur_base(self, serveur: str, nom: str) -> None:
        return None

    def supprimer_utilisateur_base(self, serveur: str, nom: str) -> None:
        return None


class PleskOpenStack(PleskSimule):
    """Plesk via son API RPC HTTP (variable SYNELIA_PLESK_URL)."""
