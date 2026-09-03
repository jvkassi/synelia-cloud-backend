"""Métrologie : usage horaire → consommation journalière → montant FCFA. Version minimale : à partir des ressources vivantes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from synelia_contract import modeles as m

from synelia.depot import Depot
from synelia.deps.contexte import Contexte

PRIX = {"vcpu_heure": 25, "ram_go_heure": 12, "stockage_to_jour": 1500, "ip_publique_jour": 300}


async def consommation(ctx: Contexte, periode: str, espace_id: str | None = None) -> dict[str, Any]:
    annee, mois = (int(x) for x in periode.split("-")[:2])
    debut = date(annee, mois, 1)
    fin = (debut.replace(day=28) + timedelta(days=4)).replace(day=1)
    aujourdhui = date.today()
    vms = await Depot("vm", m.Vm).tous(ctx, filtre=lambda v: espace_id is None or v.espaceId == espace_id)
    vcpu = sum(v.vcpu for v in vms)
    ram = sum(v.ramGo for v in vms)
    to = sum(v.diskGo for v in vms) / 1024
    ips = sum(1 for v in vms for ip in v.ips if ip.type == "publique")
    jours = []
    j = debut
    while j < fin and j <= aujourdhui:
        montant = vcpu * 24 * PRIX["vcpu_heure"] + ram * 24 * PRIX["ram_go_heure"] + int(to * PRIX["stockage_to_jour"]) + ips * PRIX["ip_publique_jour"]
        jours.append({"date": j, "vcpuHeures": vcpu * 24, "ramGoHeures": ram * 24, "stockageToJour": round(to, 3), "egressGo": 0, "montant": montant})
        j += timedelta(days=1)
    total = sum(x["montant"] for x in jours)
    nb = max(1, len(jours))
    prevision = int(total / nb * (fin - debut).days)
    return {"periode": periode, "jours": jours, "total": total, "prevision": prevision, "totalMoisPrecedent": 0}
