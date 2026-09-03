"""Le contexte d'une requête : session base, principal, organisation active, corrélation.

`Ctx` = authentifié (jeton ou clé d'API) ; `CtxPublic` = vitrine sans authentification."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from synelia_contract.rbac import ROLES_EQUIPE
from synelia_db import rls
from synelia_db.modeles import CleApi, Membership, SessionAuth, Utilisateur
from synelia_db.session import fabrique
from synelia_kernel import erreurs
from synelia_kernel.config import Reglages, reglages
from synelia_kernel.dates import maintenant
from synelia_kernel.journal import org_id_courant, utilisateur_id_courant

from synelia.deps import limitation
from synelia.securite import hacher_jeton, lire_acces


@dataclass
class Principal:
    utilisateur_id: str | None
    email: str
    nom: str
    org_id: str | None
    role: str
    session_id: str | None = None
    cle_api_id: str | None = None
    portee: list[str] = field(default_factory=list)
    emprunt: bool = False
    equipe: bool = False  # membre de l'équipe Synelia (super admin / opérateur)
    role_equipe: str | None = None
    roles_par_org: dict[str, str] = field(default_factory=dict)

    @property
    def est_admin_plateforme(self) -> bool:
        return self.equipe and (self.role_equipe in ROLES_EQUIPE)


@dataclass
class Contexte:
    request: Request
    session: AsyncSession
    reglages: Reglages
    correlation_id: str
    principal: Principal | None = None
    langue: str = "fr"

    @property
    def org_id(self) -> str:
        if self.principal is None or not self.principal.org_id:
            raise erreurs.AppError("organisation_requise", 400, "Aucune organisation active pour cette session.")
        return self.principal.org_id

    @property
    def org_id_ou_none(self) -> str | None:
        return self.principal.org_id if self.principal else None

    @property
    def role(self) -> str:
        return self.principal.role if self.principal else "anonyme"

    @property
    def utilisateur_id(self) -> str | None:
        return self.principal.utilisateur_id if self.principal else None

    @property
    def ip(self) -> str | None:
        return self.request.client.host if self.request.client else None

    def entete(self, nom: str) -> str | None:
        return self.request.headers.get(nom)


async def _session() -> AsyncIterator[AsyncSession]:
    async with fabrique()() as s:
        try:
            yield s
            if s.in_transaction():
                await s.commit()
        except Exception:
            if s.in_transaction():
                await s.rollback()
            raise


async def contexte_public(
    request: Request,
    session: Annotated[AsyncSession, Depends(_session)],
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> Contexte:
    limitation.verifier(request)
    return Contexte(
        request=request,
        session=session,
        reglages=reglages(),
        correlation_id=getattr(request.state, "correlation_id", "-"),
        langue=(accept_language or "fr")[:2],
    )


async def _principal_depuis_jeton(session: AsyncSession, jeton: str) -> Principal:
    claims = lire_acces(jeton)
    sid = claims.get("sid")
    if sid:
        s = await session.get(SessionAuth, sid)
        if s is None or s.revoquee_le is not None or s.expire_le < maintenant():
            raise erreurs.non_authentifie("Session révoquée ou expirée.")
        if not s.mfa_validee:
            raise erreurs.non_authentifie("Second facteur requis.")
        s.derniere_activite_le = maintenant()
    u = await session.get(Utilisateur, claims["sub"])
    if u is None or u.statut == "suspendu":
        raise erreurs.non_authentifie("Compte inconnu ou suspendu.")
    membres = (await session.execute(select(Membership).where(Membership.utilisateur_id == u.id))).scalars().all()
    roles = {m.org_id: m.role for m in membres if m.scope_type == "org"}
    equipe = u.equipe or {}
    return Principal(
        utilisateur_id=u.id,
        email=u.email,
        nom=u.nom,
        org_id=claims.get("org"),
        role=claims.get("role") or "read_only",
        session_id=sid,
        emprunt=bool(claims.get("emprunt")),
        equipe=bool(equipe),
        role_equipe=equipe.get("role"),
        roles_par_org=roles,
    )


async def _principal_depuis_cle(session: AsyncSession, cle: str) -> Principal:
    ligne = (
        await session.execute(select(CleApi).where(CleApi.secret_hash == hacher_jeton(cle), CleApi.revoquee_le.is_(None)))
    ).scalar_one_or_none()
    if ligne is None or (ligne.expire_le and ligne.expire_le < maintenant()):
        raise erreurs.non_authentifie("Clé d'API inconnue, révoquée ou expirée.")
    ligne.derniere_utilisation_le = maintenant()
    ligne.utilisations = (ligne.utilisations or 0) + 1
    return Principal(
        utilisateur_id=None,
        email=f"cle:{ligne.prefixe}",
        nom=ligne.nom,
        org_id=ligne.org_id,
        role=ligne.role_emetteur,
        cle_api_id=ligne.id,
        portee=list(ligne.portee or []),
    )


async def contexte(
    request: Request,
    session: Annotated[AsyncSession, Depends(_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
    x_organisation_id: Annotated[str | None, Header(alias="X-Organisation-Id")] = None,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> Contexte:
    limitation.verifier(request)
    if authorization and authorization.lower().startswith("bearer "):
        principal = await _principal_depuis_jeton(session, authorization[7:].strip())
    elif x_api_key:
        principal = await _principal_depuis_cle(session, x_api_key)
    else:
        raise erreurs.non_authentifie()

    if x_organisation_id and x_organisation_id != principal.org_id:
        if principal.est_admin_plateforme:
            principal.org_id = x_organisation_id
            principal.role = principal.role_equipe or principal.role
        elif x_organisation_id in principal.roles_par_org:
            principal.org_id = x_organisation_id
            principal.role = principal.roles_par_org[x_organisation_id]
        else:
            raise erreurs.interdit("Vous n'appartenez pas à cette organisation.", code="organisation_interdite")

    rls.org_id_transaction.set(principal.org_id)
    org_id_courant.set(principal.org_id)
    utilisateur_id_courant.set(principal.utilisateur_id)
    request.state.principal = principal
    return Contexte(
        request=request,
        session=session,
        reglages=reglages(),
        correlation_id=getattr(request.state, "correlation_id", "-"),
        principal=principal,
        langue=(accept_language or "fr")[:2],
    )


Ctx = Annotated[Contexte, Depends(contexte)]
CtxPublic = Annotated[Contexte, Depends(contexte_public)]


def dict_sans_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
