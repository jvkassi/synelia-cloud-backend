from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_openstack import fournisseur
from synelia_openstack.plateforme_k8s import ArgoReel, ArgoSimule, DepotsReel, DepotsSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot_app = Depot(
    "application", m.ApplicationPaas, champ_nom="nom", champs_recherche=("nom", "domainePrincipal")
)
depot_env = Depot("environnement", m.Environnement, champ_nom="nom")
depot_comp = Depot("composant", m.Composant, champ_nom="nom")


def argo() -> ArgoSimule:
    return fournisseur(ArgoSimule, ArgoReel)


def depots() -> DepotsSimule:
    return fournisseur(DepotsSimule, DepotsReel)


SANTE_NULLE = m.Sante(cpu=0.0, ram=0.0, latenceMs=0.0, erreursPct=0.0)


def analyser(ctx: Contexte, corps: m.ApplicationsAnalyseDepotPostRequest) -> m.AnalyseDepot:
    d = depots().analyser(corps.provider, corps.url, corps.branche)
    return m.AnalyseDepot(
        depot=corps.url,
        branche=corps.branche or "main",
        commit=None,
        constats=[
            m.Constat(
                fichier=".<racine>",
                constat=f"Framework pressenti : {d['framework'] or 'inconnu'}.",
                niveau="info",
            )
        ],
        builderPropose=d["builder"],
        ciblePropose=d["cible"],
        servicesDetectes=None,
        variablesRequises=None,
    )


# ── travaux applicatifs ────────────────────────────────────────────────
@executeur("application.create")
class ExecuteurAppCreate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        app = await depot_app.obtenir(ctx, travail.cible_id or "")
        a = argo()
        a.creer_application(app.nom, (app.repo.url if app.repo else ""), ".", "default")
        await depot_app.modifier(
            ctx, app.id, {"sante": "sain", "environnements": app.environnements}
        )


@executeur("application.delete")
class ExecuteurAppDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        app = await depot_app.obtenir(ctx, travail.cible_id or "")
        argo().supprimer_application(app.nom)
        await depot_app.supprimer(ctx, app.id, logique=True)


@executeur("environnement.delete")
class ExecuteurEnvDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_env.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("composant.creer")
class ExecuteurComposantCreer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_comp.definir_statut(ctx, travail.cible_id or "", "deployed")
        await depot_env.definir_statut(ctx, travail.contexte.get("env_id") or "", "running")


@executeur("composant.modifier")
class ExecuteurComposantModifier(Executeur):
    compensable = True


@executeur("composant.supprimer")
class ExecuteurComposantSupprimer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_comp.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("composant.arret")
class ExecuteurComposantArret(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_comp.definir_statut(ctx, travail.cible_id or "", "stopped")


@executeur("composant.redemarrage")
class ExecuteurComposantRedemarrage(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_comp.definir_statut(ctx, travail.cible_id or "", "deployed")


@executeur("composant.dimensionnement")
class ExecuteurComposantDimensionnement(Executeur):
    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        c = await depot_comp.obtenir(ctx, travail.cible_id or "")
        demandes = dict(travail.contexte).get("demandes", {})
        if index == 0:
            return f"Redimensionnement de {c.nom} vers {demandes.get('replicas', '—')} réplica(s)"
        if index == 1:
            return f"Application cpu={demandes.get('cpu')} · ram={demandes.get('ramMo')} Mo · disk={demandes.get('diskGo')} Go"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        demandes = dict(travail.contexte).get("demandes", {})
        c = await depot_comp.obtenir(ctx, travail.cible_id or "")
        ressources = c.ressources.model_copy(
            update={
                "cpu": demandes.get("cpu", c.ressources.cpu),
                "ramMo": demandes.get("ramMo", c.ressources.ramMo),
                "diskGo": demandes.get("diskGo", c.ressources.diskGo),
            }
        )
        await depot_comp.modifier(ctx, c.id, {"ressources": ressources.model_dump()})
        await depot_comp.definir_statut(ctx, c.id, "deployed")
