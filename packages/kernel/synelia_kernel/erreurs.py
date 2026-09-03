"""Erreurs applicatives, dans la forme unique du contrat : `{ erreur: { code, message, correlationId } }`."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Une erreur que l'API sait renvoyer : code stable, statut HTTP, message affichable."""

    def __init__(
        self,
        code: str,
        statut: int,
        message: str,
        *,
        detail: str | None = None,
        champs: dict[str, str] | None = None,
        roles_requis: list[str] | None = None,
        integration: str | None = None,
        donnees_partielles: Any | None = None,
        date_donnees: str | None = None,
        documentation_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.statut = statut
        self.message = message
        self.detail = detail
        self.champs = champs
        self.roles_requis = roles_requis
        self.integration = integration
        self.donnees_partielles = donnees_partielles
        self.date_donnees = date_donnees
        self.documentation_url = documentation_url

    def corps(self, correlation_id: str) -> dict[str, Any]:
        erreur: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "correlationId": correlation_id,
        }
        if self.detail:
            erreur["detail"] = self.detail
        if self.documentation_url:
            erreur["documentationUrl"] = self.documentation_url
        corps: dict[str, Any] = {"erreur": erreur}
        if self.champs is not None:
            corps["champs"] = self.champs
        if self.roles_requis is not None:
            corps["rolesRequis"] = self.roles_requis
        if self.integration is not None:
            corps["integration"] = self.integration
            corps["donneesPartielles"] = self.donnees_partielles
            if self.date_donnees:
                corps["dateDonnees"] = self.date_donnees
        return corps


def invalide(message: str = "Requête mal formée.", detail: str | None = None) -> AppError:
    return AppError("requete_invalide", 400, message, detail=detail)


def non_authentifie(message: str = "Jeton absent, expiré ou révoqué.") -> AppError:
    return AppError("non_authentifie", 401, message)


def quota_depasse(message: str = "Quota dépassé.", detail: str | None = None) -> AppError:
    return AppError("quota_depasse", 402, message, detail=detail)


def interdit(message: str, roles_requis: list[str] | None = None, code: str = "interdit") -> AppError:
    return AppError(code, 403, message, roles_requis=roles_requis or [])


def introuvable(ressource: str = "Ressource", identifiant: str | None = None) -> AppError:
    suffixe = f" « {identifiant} »" if identifiant else ""
    return AppError("introuvable", 404, f"{ressource}{suffixe} introuvable.")


def conflit(message: str, code: str = "conflit") -> AppError:
    return AppError(code, 409, message)


def nom_deja_pris(nom: str) -> AppError:
    return AppError("nom_deja_pris", 409, f"Le nom « {nom} » est déjà utilisé.")


def validation(message: str, champs: dict[str, str] | None = None, code: str = "validation") -> AppError:
    return AppError(code, 422, message, champs=champs or {})


def confirmation_invalide(attendu: str) -> AppError:
    return AppError(
        "confirmation_invalide",
        422,
        "La confirmation doit reprendre exactement le nom de la ressource.",
        champs={"confirmation": f"Attendu : {attendu}"},
    )


def non_porte(message: str) -> AppError:
    """Ce que l'amont ne porte pas : un `422` qui dit pourquoi, jamais un `200` creux."""
    return AppError("non_porte", 422, message)


def amont_indisponible(
    integration: str,
    message: str | None = None,
    donnees_partielles: Any | None = None,
    date_donnees: str | None = None,
) -> AppError:
    return AppError(
        "amont_indisponible",
        424,
        message or f"L'intégration « {integration} » ne répond pas.",
        integration=integration,
        donnees_partielles=donnees_partielles,
        date_donnees=date_donnees,
    )


def trop_de_requetes() -> AppError:
    return AppError("trop_de_requetes", 429, "Trop de requêtes, réessayez dans un instant.")


def interne(detail: str | None = None) -> AppError:
    return AppError("erreur_interne", 500, "Erreur interne. Citez le correlationId dans votre ticket.", detail=detail)
