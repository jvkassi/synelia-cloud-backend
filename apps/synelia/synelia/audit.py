"""Journal d'audit append-only, hash chaîné."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import desc, select
from synelia_db.modeles import Audit
from synelia_kernel.dates import iso, maintenant

if TYPE_CHECKING:
    from synelia.deps.contexte import Contexte


def empreinte(precedent: str | None, org: str | None, ligne: Audit) -> str:
    """Empreinte SHA-256 d'une ligne, chaînée à l'empreinte précédente. Utilisée à l'écriture
    (`journaliser`) comme à la vérification (`verifier_chaine`) : les deux doivent recalculer
    exactement le même hash à partir des mêmes champs pour que la chaîne ait un sens."""
    charge = json.dumps(
        [
            precedent,
            org,
            iso(ligne.date),
            ligne.acteur,
            ligne.action,
            ligne.cible_type,
            ligne.cible_id,
            ligne.resultat,
            ligne.details or {},
        ],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(charge.encode()).hexdigest()


async def journaliser(
    ctx: Contexte,
    *,
    action: str,
    cible_type: str | None = None,
    cible_id: str | None = None,
    cible: str | None = None,
    resultat: str = "succes",
    details: dict[str, Any] | None = None,
    org_id: str | None = None,
) -> Audit:
    p = ctx.principal
    org = org_id or (p.org_id if p else None)
    precedent = (
        await ctx.session.execute(
            select(Audit.hash).where(Audit.org_id == org).order_by(desc(Audit.date)).limit(1)
        )
    ).scalar_one_or_none()
    ligne = Audit(
        org_id=org,
        date=maintenant(),
        acteur_id=p.utilisateur_id if p else None,
        acteur=p.email if p else "systeme",
        action=action,
        cible_type=cible_type,
        cible_id=cible_id,
        cible=cible,
        resultat=resultat,
        ip=ctx.ip,
        correlation_id=ctx.correlation_id,
        details=details or {},
        hash_precedent=precedent,
    )
    ligne.hash = empreinte(precedent, org, ligne)
    ctx.session.add(ligne)
    await ctx.session.flush()
    return ligne


async def verifier_chaine(ctx: Contexte, org_id: str | None = None) -> dict[str, Any]:
    """Rejoue la chaîne de hachage d'une organisation (par date croissante) et recalcule chaque
    empreinte à partir des champs enregistrés : une ligne modifiée, supprimée ou insérée hors
    séquence casse la chaîne à partir de ce point, et c'est immédiatement détectable — c'est tout
    l'intérêt d'un hash chaîné plutôt qu'une simple empreinte par ligne."""
    p = ctx.principal
    org = org_id or (p.org_id if p else None)
    lignes = (
        (await ctx.session.execute(select(Audit).where(Audit.org_id == org).order_by(Audit.date)))
        .scalars()
        .all()
    )
    precedent: str | None = None
    for n, ligne in enumerate(lignes, start=1):
        if ligne.hash_precedent != precedent:
            return {
                "intacte": False,
                "entreesVerifiees": n - 1,
                "totalEntrees": len(lignes),
                "ruptureId": ligne.id,
                "ruptureDate": ligne.date,
                "raison": "hash_precedent ne correspond pas à l'empreinte de la ligne antérieure",
            }
        attendu = empreinte(precedent, org, ligne)
        if ligne.hash != attendu:
            return {
                "intacte": False,
                "entreesVerifiees": n - 1,
                "totalEntrees": len(lignes),
                "ruptureId": ligne.id,
                "ruptureDate": ligne.date,
                "raison": "empreinte recalculée différente de l'empreinte enregistrée",
            }
        precedent = ligne.hash
    return {
        "intacte": True,
        "entreesVerifiees": len(lignes),
        "totalEntrees": len(lignes),
        "ruptureId": None,
        "ruptureDate": None,
        "raison": None,
        "empreinteFinale": precedent,
    }


def vers_contrat(a: Audit) -> dict[str, Any]:
    return {
        "id": a.id,
        "orgId": a.org_id,
        "date": a.date,
        "acteur": a.acteur,
        "acteurId": a.acteur_id,
        "action": a.action,
        "cible": a.cible or (f"{a.cible_type}:{a.cible_id}" if a.cible_type else None),
        "cibleType": a.cible_type,
        "cibleId": a.cible_id,
        "resultat": a.resultat,
        "ip": a.ip,
        "correlationId": a.correlation_id,
        "details": a.details or {},
        "hashPrecedent": a.hash_precedent,
        "hash": a.hash,
    }
