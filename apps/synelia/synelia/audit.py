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
        await ctx.session.execute(select(Audit.hash).where(Audit.org_id == org).order_by(desc(Audit.date)).limit(1))
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
    charge = json.dumps(
        [precedent, org, iso(ligne.date), ligne.acteur, action, cible_type, cible_id, resultat, ligne.details],
        sort_keys=True,
        default=str,
    )
    ligne.hash = hashlib.sha256(charge.encode()).hexdigest()
    ctx.session.add(ligne)
    await ctx.session.flush()
    return ligne


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
        "hash": a.hash,
    }
