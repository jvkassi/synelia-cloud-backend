"""Tarification : prix unitaires publics étendant la métrologie, estimation en FCFA entiers + TVA."""

from __future__ import annotations

from typing import Any

from synelia_kernel import argent

from synelia.modules.facturation import metrologie

PRIX_UNITAIRES = {
    **metrologie.PRIX,
    "vm_heure": 0,
    "k8s_req_heure": 15,
    "stockage_go_mois": 1500,
    "base_go_mois": 300,
    "bucket_go_mois": 100,
    "siege_mois": 5000,
    "certificat_an": 24000,
}

LITTERAUX_PERIODICITE = {"mensuelle": "Mensuel", "annuelle": "Annuel", None: "Ponctuel"}

HEURES_MOIS = 730


def _prix_ressource(type_: str, specification: dict[str, Any], quantite: int) -> int:
    q = max(1, quantite)
    if type_ == "vm":
        vcpu = int(specification.get("vcpu", 1))
        ram = int(specification.get("ramGo", 2))
        disk = int(specification.get("diskGo", 20))
        ht = int(
            vcpu * metrologie.PRIX["vcpu_heure"] * HEURES_MOIS
            + ram * metrologie.PRIX["ram_go_heure"] * HEURES_MOIS
            + disk * PRIX_UNITAIRES["stockage_go_mois"]
        )
        return ht * q
    if type_ == "volume":
        return int(specification.get("tailleGo", 10) * PRIX_UNITAIRES["stockage_go_mois"]) * q
    if type_ == "espace":
        vcpu = int((specification.get("quota") or {}).get("vcpu", 4))
        return int(vcpu * metrologie.PRIX["vcpu_heure"] * HEURES_MOIS) * q
    if type_ in ("base", "bucket"):
        go = int(specification.get("tailleGo", 10))
        return int(go * PRIX_UNITAIRES[f"{type_}_go_mois"]) * q
    if type_ in ("certificat", "domaine"):
        return int(PRIX_UNITAIRES.get(f"{type_}_an", 0)) * q
    if type_ == "siege":
        return int(PRIX_UNITAIRES["siege_mois"]) * q
    if type_ == "k8s":
        return (
            int(specification.get("requetes", 2) * PRIX_UNITAIRES["k8s_req_heure"] * HEURES_MOIS)
            * q
        )
    ht = PRIX_UNITAIRES.get(f"{type_}_heure", 0) * HEURES_MOIS * q
    return int(ht) if ht else int(PRIX_UNITAIRES.get(f"{type_}_mois", 0)) * q


def _prix_renomme(type_: str) -> str:
    return {
        "espace": "Espace Cloud",
        "vm": "Machine virtuelle",
        "k8s": "Cluster Kubernetes",
        "volume": "Volume",
        "bucket": "Seau objet",
        "base": "Base de données",
        "service_manage": "Service managé",
        "hebergement": "Hébergement",
        "certificat": "Certificat TLS",
        "siege": "Licence par siège",
    }.get(type_, type_.replace("_", " ").capitalize())


def estimer(demande: Any) -> dict[str, Any]:
    type_ = demande.type
    quantite = demande.quantite or 1
    specification = demande.specification or {}
    periodicite = demande.periodicite

    prix_unit_simple = _prix_ressource(type_, specification, 1)
    total_mensuel = argent.ttc(prix_unit_simple * quantite)
    total_periode = total_mensuel * (12 if periodicite == "annuelle" else 1)

    lignes = [
        {
            "libelle": f"{_prix_renomme(type_)} — {specification.get('nom', specification.get('code', ''))}",
            "quantite": float(quantite),
            "unite": LITTERAUX_PERIODICITE.get(periodicite),
            "prixUnitaire": prix_unit_simple,
            "total": total_periode,
        }
    ]
    return {
        "lignes": lignes,
        "totalMensuel": total_mensuel,
        "totalHoraire": float(prix_unit_simple / HEURES_MOIS) if type_ == "vm" else None,
        "proRataMoisCourant": int(total_periode * 0.5),
        "devise": "XOF",
        "engagement": None,
        "remisePct": None,
        "avertissements": [
            "Egress non couvert. Les licences tierces restent à la charge du client."
        ],
    }
