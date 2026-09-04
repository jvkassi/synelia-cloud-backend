"""Règles sauvegarde (Web Cloud) : dépôt, exécuteurs, donnée de démo."""

from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Ressource, Travail
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id

from synelia.demo import peupleur
from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot(
    "web_sauvegarde",
    m.SauvegardeWeb,
    libelle="Sauvegarde",
    champ_nom="nomServi",
    champ_statut="actif",
    champs_recherche=("nomServi", "serveur", "hebergementId"),
)


def point(nombre: str = "1.2 Go", contenu: list[str] | None = None) -> m.ExecutionSauvegarde:
    return m.ExecutionSauvegarde(
        id=nouvel_id(),
        ts=maintenant(),
        statut="ok",
        taille=nombre,
        dureeMin=5,
        contenu=contenu or ["Site", "Base de données"],
        immuableJusqua=None,
        message=None,
    )


@executeur("web.backup.run")
class ExecuteurSauvegardeRun(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot.obtenir(ctx, travail.cible_id or "")
        executions = [*s.executions, point()]
        await depot.modifier(
            ctx, s.id, {"executions": [e.model_dump(mode="json") for e in executions]}
        )


@executeur("web.backup.testrestauration")
class ExecuteurSauvegardeTestRestauration(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot.obtenir(ctx, travail.cible_id or "")
        await depot.modifier(
            ctx,
            s.id,
            {
                "dernierTestRestauration": {
                    "date": maintenant().date().isoformat(),
                    "resultat": "ok",
                    "dureeMin": 3,
                }
            },
        )


ETAPES_TEST_RESTAURATION = [
    {"nom": "Vérifier l'intégrité du dépôt", "dureeS": 8},
    {"nom": "Restaurer sur un environnement isolé", "dureeS": 60},
    {"nom": "Comparer les contenus", "dureeS": 15},
    {"nom": "Supprimer l'environnement de test", "dureeS": 6},
]


@peupleur
async def demo(session, org, admin) -> None:  # type: ignore[no-untyped-def]
    sd = m.SauvegardeWeb(
        id=nouvel_id(),
        hebergementId="hebergement-demo",
        serveur="srv-web-01",
        nomServi=org.nom,
        actif=True,
        frequence="quotidienne",
        heure="02:30",
        retentionJours=14,
        destination="backup.s3.synelia.cloud",
        site="ABJ",
        immuable=False,
        perimetre=m.Perimetre(fichiers=True, bases=True, configuration=True, messagerie=False),
        executions=[],
        espaceOccupeGo=0.0,
        dernierTestRestauration=None,
    )
    session.add(
        Ressource(
            id=sd.id,
            org_id=org.id,
            type="web_sauvegarde",
            nom=sd.nomServi,
            statut=str(sd.actif),
            donnees=sd.model_dump(mode="json"),
        )
    )
