"""Conformité : anomalies (tableau de bord), attestations, rapports (audit)."""

from __future__ import annotations

from typing import Any

from synelia_contract import modeles as m
from synelia_db.modeles import Ressource, Travail
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id

from synelia.demo import peupleur
from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

anomalies = Depot(
    "anomalie", m.Anomalie, libelle="Anomalie", champs_recherche=("titre", "constat", "consequence")
)
attestations = Depot(
    "attestation", m.Attestation, libelle="Attestation", champs_recherche=("titre", "type")
)
rapports = Depot(
    "rapport_conformite",
    m.ConformiteRapportsGetResponseItem,
    libelle="Rapport de conformité",
    champs_recherche=("titre", "referentiel"),
)

ETAPES_AUDIT = [
    {"nom": "Collecter les preuves", "dureeS": 10},
    {"nom": "Rédiger le document", "dureeS": 20},
    {"nom": "Signer et horodater", "dureeS": 5},
]


def _corriger_anomalie(anomalie: m.Anomalie, corps: m.DecisionAnomalie) -> dict[str, Any]:
    if corps.decision == "appliquer":
        return {"statut": "corrigee", "ignoreeJusquau": None}
    if corps.decision == "ignorer":
        return {"statut": "ignoree", "ignoreeJusquau": corps.jusquau}
    return {"statut": "ouverte", "ignoreeJusquau": None}


@executeur("conformite.correctif")
class ExecuteurCorrectif(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        anomalie_id = travail.cible_id or ""
        changements = dict(travail.contexte.get("changements") or {})
        await anomalies.modifier(ctx, anomalie_id, changements)


@executeur("attestation.generate")
class ExecuteurAttestation(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        attestation_id = travail.cible_id or ""
        await attestations.modifier(
            ctx,
            attestation_id,
            {"disponible": True, "genereLe": maintenant(), "empreinte": nouvel_id()},
        )


@executeur("conformite.rapport")
class ExecuteurRapport(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        referentiel = travail.entree.get("referentiel") or "3-2-1"
        periode = travail.entree.get("periode") or maintenant().strftime("%Y-%m")
        titre = f"Rapport de conformité {referentiel} — {periode}"
        await rapports.creer(
            ctx,
            m.ConformiteRapportsGetResponseItem(
                id=travail.cible_id or nouvel_id(),
                titre=titre,
                referentiel=referentiel,
                periode=periode,
                genereLe=maintenant(),
                url="/v1/conformite/rapports/telechargement",
            ),
        )


@peupleur
async def _peupler_anomalies(session, org, admin) -> None:  # type: ignore[no-untyped-def]
    for i, (gravite, constat) in enumerate(
        [
            (
                "critique",
                "Aucune sauvegarde sur ce serveur depuis 14 jours (0 point de restauration).",
            ),
            ("majeure", "Certificat TLS du domaine api.domaine.tld expire sous 12 jours."),
        ]
    ):
        anom_id = nouvel_id()
        session.add(
            Ressource(
                id=anom_id,
                org_id=org.id,
                type="anomalie",
                nom=f"anomalie-{i}",
                statut="ouverte",
                donnees=m.Anomalie(
                    id=anom_id,
                    detecteeLe=maintenant(),
                    gravite=gravite,  # type: ignore[arg-type]
                    portee=m.Portee(
                        type="ressource", id=f"res-{i}", libelle=f"Ressource de démo {i}"
                    ),
                    titre="Sauvegarde manquante" if i == 0 else "Certificat expirant",
                    constat=constat,
                    consequence="Perte de données en cas d'incident."
                    if i == 0
                    else "Service indisponible pour les visiteurs.",
                    correctif=m.Correctif(
                        libelle="Lancer une sauvegarde",
                        action="backup.run",
                        automatisable=True,
                        actionRbac="backup.plan.write",
                    )
                    if i == 0
                    else m.Correctif(
                        libelle="Renouveler le certificat",
                        action="web.ssl.renew",
                        automatisable=True,
                        actionRbac="web.ssl.manage",
                    ),
                    statut="ouverte",
                    ignoreeJusquau=None,
                ).model_dump(mode="json"),
            )
        )


@peupleur
async def _peupler_attestations(session, org, admin) -> None:  # type: ignore[no-untyped-def]
    for att_id, att_type, titre, description in [
        (
            "hebergement",
            "hebergement",
            "Attestation d'hébergement",
            "Localisation et continuité des services hébergés.",
        ),
        (
            "conformite_321",
            "conformite_321",
            "Attestation de conformité 3-2-1",
            "Respect de la règle de sauvegarde 3-2-1.",
        ),
    ]:
        session.add(
            Ressource(
                id=att_id,
                org_id=org.id,
                type="attestation",
                nom=att_id,
                statut="brouillon",
                donnees=m.Attestation(
                    id=att_id,
                    type=att_type,  # type: ignore[arg-type]
                    titre=titre,
                    description=description,
                    periode="2026-08",
                    disponible=False,
                ).model_dump(mode="json"),
            )
        )
