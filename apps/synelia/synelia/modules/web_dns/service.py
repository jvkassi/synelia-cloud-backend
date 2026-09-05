from __future__ import annotations

from synelia_contract import modeles as m
from synelia_kernel import erreurs
from synelia_kernel.ids import nouvel_id

from synelia.depot import Depot
from synelia.deps.contexte import Contexte

depot = Depot("dns_zone", m.ZoneDns, libelle="Zone DNS", champ_nom="domaine")

NS_DEFAUTS = ["ns1.synelia.cloud", "ns2.synelia.cloud"]

MODELES_DNS = [
    m.ModeleDns(
        id="courrier",
        nom="Courrier (MX + SPF + DKIM)",
        description="Ajoute les enregistrements de messagerie indispensables à votre domaine.",
        enregistrements=[
            m.EnregistrementDnsCreation(
                type="MX", nom="@", valeur="mail.synelia.cloud", ttl=3600, priorite=10
            ),
            m.EnregistrementDnsCreation(
                type="TXT", nom="@", valeur="v=spf1 include:spf.synelia.cloud ~all", ttl=3600
            ),
            m.EnregistrementDnsCreation(
                type="CNAME", nom="mail", valeur="mail.synelia.cloud", ttl=3600
            ),
        ],
        remplaceExistants=True,
    ),
    m.ModeleDns(
        id="dmarc",
        nom="DMARC",
        description="Stratégie DMARC de base pour protéger le domaine contre l'usurpation.",
        enregistrements=[
            m.EnregistrementDnsCreation(
                type="TXT",
                nom="_dmarc",
                valeur="v=DMARC1; p=none; rua=mailto:dmarc@synelia.cloud",
                ttl=3600,
            ),
        ],
    ),
    m.ModeleDns(
        id="sous-domaine-www",
        nom="Sous-domaine www",
        description="Redirige www vers le domaine racine.",
        enregistrements=[
            m.EnregistrementDnsCreation(type="CNAME", nom="www", valeur="@", ttl=3600)
        ],
    ),
]


async def creer_zone(ctx: Contexte, domaine: str) -> m.ZoneDns:
    zone = m.ZoneDns(
        id=nouvel_id(),
        orgId=ctx.org_id,
        domaine=domaine,
        dnssec=False,
        ns=list(NS_DEFAUTS),
        enregistrements=[],
    )
    await depot.creer(ctx, zone)
    return await depot.obtenir(ctx, zone.id)


def enregistrement_vers(
    zone: m.ZoneDns, e: m.EnregistrementDnsCreation, id_: str | None = None
) -> m.EnregistrementDns:
    return m.EnregistrementDns(
        id=id_ or nouvel_id(),
        type=e.type,
        nom=e.nom,
        valeur=e.valeur,
        ttl=e.ttl or 3600,
        priorite=e.priorite,
    )


async def appliquer_enregistrements(
    ctx: Contexte,
    zone_id: str,
    enregistrements: list[m.EnregistrementDnsCreation],
    remplacer: bool = False,
) -> m.ZoneDns:
    zone = await depot.obtenir(ctx, zone_id)
    nouveaux = [enregistrement_vers(zone, e) for e in enregistrements]
    liste = nouveaux if remplacer else [*zone.enregistrements, *nouveaux]
    await depot.remplacer(ctx, zone_id, zone.model_copy(update={"enregistrements": liste}))
    return await depot.obtenir(ctx, zone_id)


def verifier_non_duplique(zone: m.ZoneDns, e: m.EnregistrementDnsCreation) -> None:
    if any(r.nom == e.nom and r.type == e.type for r in zone.enregistrements):
        raise erreurs.conflit(
            "Cet enregistrement existe déjà sur la zone.", code="enregistrement_deja_present"
        )
