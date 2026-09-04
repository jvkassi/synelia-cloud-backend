"""RBAC, référentiels, onboarding, recherche."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import or_, select
from synelia_contract import modeles as m
from synelia_contract import rbac
from synelia_db.modeles import Organisation, Ressource

from synelia.deps import Ctx, CtxPublic

router = APIRouter(tags=["Compte & organisation active"])

SITES = [
    {"code": "ABJ", "libelle": "Abidjan", "ville": "Abidjan"},
    {"code": "GBM", "libelle": "Grand-Bassam", "ville": "Grand-Bassam"},
]
SECTEURS = [
    "Banque & assurance",
    "Télécoms",
    "Administration",
    "Santé",
    "Éducation",
    "Commerce",
    "Industrie",
    "Technologie",
    "Médias",
    "Autre",
]
PAYS = [
    {"code": "CI", "nom": "Côte d'Ivoire", "indicatif": "+225"},
    {"code": "SN", "nom": "Sénégal", "indicatif": "+221"},
    {"code": "BF", "nom": "Burkina Faso", "indicatif": "+226"},
    {"code": "ML", "nom": "Mali", "indicatif": "+223"},
    {"code": "TG", "nom": "Togo", "indicatif": "+228"},
    {"code": "BJ", "nom": "Bénin", "indicatif": "+229"},
    {"code": "GN", "nom": "Guinée", "indicatif": "+224"},
    {"code": "CM", "nom": "Cameroun", "indicatif": "+237"},
    {"code": "FR", "nom": "France", "indicatif": "+33"},
]


@router.get("/rbac/matrice", response_model=list[m.ActionRbac])
async def obtenir_matrice_rbac(ctx: Ctx) -> Any:
    return rbac.matrice()


@router.get("/referentiels", response_model=m.Referentiels, response_model_exclude_none=True)
async def obtenir_referentiels(ctx: CtxPublic) -> Any:
    return {
        "pays": PAYS,
        "secteurs": SECTEURS,
        "taillesOrganisation": ["1-10", "11-50", "51-200", "201-1000", "1000+"],
        "sites": SITES,
        "devises": ["XOF", "EUR", "USD"],
        "roles": [{"code": r, "libelle": rbac.ROLE_LABEL[r]} for r in rbac.ROLES_CLIENT],
        "moyensPaiement": [
            {"code": "cinetpay", "libelle": "Mobile money & cartes (CinetPay)"},
            {"code": "stripe", "libelle": "Carte bancaire (EUR/USD)"},
            {"code": "virement", "libelle": "Virement bancaire"},
            {"code": "prepaye", "libelle": "Compte prépayé"},
        ],
    }


ETAPES_ONBOARDING = [
    ("organisation", "Compléter la fiche organisation", "/app/organisation", None, True),
    ("membres", "Inviter un premier membre", "/app/membres", "member.invite", False),
    ("espace", "Créer un Espace Cloud", "/app/espaces", "espace.create", True),
    ("vm", "Lancer une première machine", "/app/vms", "vm.create_delete", False),
    ("paiement", "Ajouter un moyen de paiement", "/app/facturation", "payment.update", True),
    ("mfa", "Activer le second facteur", "/app/compte", None, False),
]


async def _compter(ctx, type_: str) -> int:
    from synelia.depot import Depot

    return await Depot(type_, m.Vm).compter(ctx)


@router.get("/onboarding", response_model=m.Onboarding, response_model_exclude_none=True)
async def obtenir_onboarding(ctx: Ctx) -> Any:
    o = await ctx.session.get(Organisation, ctx.org_id)
    etat = (o.onboarding or {}) if o else {}
    faites = set(etat.get("faites", []))
    faites.add("organisation")
    if await _compter(ctx, "espace"):
        faites.add("espace")
    if await _compter(ctx, "vm"):
        faites.add("vm")
    if await _compter(ctx, "moyen_paiement"):
        faites.add("paiement")
    etapes = [
        {
            "cle": c,
            "libelle": lib,
            "faite": c in faites,
            "href": href,
            "actionRbac": act,
            "obligatoire": ob,
        }
        for c, lib, href, act, ob in ETAPES_ONBOARDING
    ]
    pct = round(100 * len([e for e in etapes if e["faite"]]) / len(etapes), 1)
    return {
        "termine": pct >= 100,
        "masque": bool(etat.get("masque")),
        "etapes": etapes,
        "pctComplete": pct,
    }


@router.patch("/onboarding", response_model=m.Onboarding, response_model_exclude_none=True)
async def modifier_onboarding(ctx: Ctx, corps: m.OnboardingPatchRequest) -> Any:
    o = await ctx.session.get(Organisation, ctx.org_id)
    assert o is not None
    etat = dict(o.onboarding or {})
    if corps.masque is not None:
        etat["masque"] = corps.masque
    if corps.etape:
        faites = set(etat.get("faites", []))
        (faites.add if corps.faite is not False else faites.discard)(corps.etape)
        etat["faites"] = sorted(faites)
    o.onboarding = etat
    return await obtenir_onboarding(ctx)


@router.get("/recherche", response_model=m.RechercheGetResponse, response_model_exclude_none=True)
async def rechercher(ctx: Ctx, q: str, types: str | None = None, limite: int = 20) -> Any:
    motif = f"%{q.lower()}%"
    req = select(Ressource).where(
        Ressource.org_id == ctx.org_id,
        Ressource.supprime_le.is_(None),
        or_(Ressource.nom.ilike(motif), Ressource.id == q),
    )
    if types:
        req = req.where(Ressource.type.in_(types.split(",")))
    lignes = list((await ctx.session.execute(req.limit(limite + 1))).scalars())
    champs = set(m.ResultatRecherche.model_fields)
    resultats = []
    for r in lignes[:limite]:
        d = {
            "id": r.id,
            "type": r.type,
            "libelle": r.nom or r.id,
            "href": f"/app/{r.type}s/{r.id}",
            "statut": r.statut,
        }
        resultats.append({k: v for k, v in d.items() if k in champs})
    return {"resultats": resultats, "tronque": len(lignes) > limite}
