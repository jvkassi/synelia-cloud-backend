"""Journal d'audit : projection des lignes `Audit` vers `EvenementAudit` du contrat."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from synelia_contract.rbac import ROLES_ORDRE
from synelia_db.modeles import Audit, Utilisateur

from synelia.deps.contexte import Contexte

RESULTATS = {"succes": "ok", "ok": "ok", "refus": "refuse", "refuse": "refuse"}
RESULTATS_INVERSE = {"ok": ("succes", "ok"), "refuse": ("refus", "refuse")}


def resultat_contrat(r: str | None) -> str:
    return RESULTATS.get(r or "", "erreur")


def utc(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def vers_contrat(a: Audit, org_nom: str | None, noms: dict[str, str]) -> dict[str, Any]:
    details = a.details or {}
    acteur = a.acteur or "systeme"
    if acteur.startswith("cle:"):
        type_acteur = "api"
    elif a.acteur_id:
        type_acteur = "user"
    else:
        type_acteur = "systeme"
    role = details.get("role") if details.get("role") in ROLES_ORDRE else "org_admin"
    detail = details.get("message") or details.get("motif")
    if detail is None and details:
        detail = json.dumps(details, ensure_ascii=False, default=str)[:1000]
    return {
        "id": a.id,
        "ts": a.date,
        "orgId": a.org_id,
        "orgNom": org_nom,
        "actor": {"id": a.acteur_id or acteur, "nom": noms.get(a.acteur_id or "", acteur), "email": acteur if "@" in acteur else None, "type": type_acteur},
        "role": role,
        "scope": {"type": "org", "id": a.org_id, "label": org_nom or a.org_id or "plateforme"},
        "action": a.action,
        "target": a.cible or (f"{a.cible_type}:{a.cible_id}" if a.cible_type else a.action),
        "result": resultat_contrat(a.resultat),
        "detail": detail,
        "ip": a.ip,
        # champs de recherche (ignorés par le modèle de réponse)
        "acteur": acteur,
    }


async def noms_acteurs(ctx: Contexte, lignes: list[Audit]) -> dict[str, str]:
    ids = {a.acteur_id for a in lignes if a.acteur_id}
    if not ids:
        return {}
    return {u.id: u.nom for u in (await ctx.session.execute(select(Utilisateur).where(Utilisateur.id.in_(ids)))).scalars()}
