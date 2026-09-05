from __future__ import annotations

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel.ids import nouvel_id
from synelia_openstack import fournisseur
from synelia_openstack.magnum import MagnumOpenStack, MagnumSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot_cluster = Depot("k8s_cluster", m.ClusterK8s)
depot_pool = Depot("k8s_pool", m.PoolWorkers)

MODULES = {
    "cni": "Réseaux de pods (Calico)",
    "ingress-nginx": "Contrôleur d'entrée HTTP",
    "monitoring": "Surveillance et alerting",
    "cert-manager": "Certificats TLS automatiques",
    "autoscaler": "Autoscaler horizontal de pods",
}


def amont() -> MagnumSimule:
    return fournisseur(MagnumSimule, MagnumOpenStack)


@executeur("k8s.create")
class ExecuteurK8sCreate(Executeur):
    compensable = True

    async def etape(self, ctx: Contexte, travail: Travail, index: int, nom: str) -> str | None:
        if index == 0:
            cluster = await depot_cluster.obtenir(ctx, travail.cible_id or "")
            entree = travail.entree or {}
            from synelia.modules.espaces.service import depot as depot_espaces

            secrets_espace = await depot_espaces.secrets(ctx, cluster.espaceId)
            cl = amont().creer_cluster(
                nom=cluster.nom,
                pools=entree.get("pools") or [],
                master_count=cluster.controlPlane.nodes,
                reseau_id=secrets_espace.get("reseau_id"),
            )
            await depot_cluster.definir_secrets(ctx, cluster.id, {"magnum_cluster_id": cl["id"]})
            c = dict(travail.contexte)
            c["statut_amont"] = cl["statut"]
            travail.contexte = c
            return f"Cluster Magnum soumis ({cl['id']}, {cl['statut']})"
        return None

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        # Le simulé renvoie CREATE_COMPLETE instantanément ; le réel (Heat/CAPI) prend bien
        # plus longtemps qu'une étape de travail, donc on ne bloque pas dessus et le cluster
        # reste `provisioning` côté plateforme tant qu'un réconciliateur (à écrire) n'a pas
        # confirmé CREATE_COMPLETE côté Magnum.
        statut_amont = str(travail.contexte.get("statut_amont", ""))
        statut = "running" if statut_amont.endswith("COMPLETE") else "provisioning"
        await depot_cluster.definir_statut(ctx, travail.cible_id or "", statut)

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        secrets = await depot_cluster.secrets(ctx, travail.cible_id or "")
        mid = secrets.get("magnum_cluster_id")
        if mid:
            amont().supprimer_cluster(mid)
        await depot_cluster.definir_statut(ctx, travail.cible_id or "", "erreur")


@executeur("k8s.delete")
class ExecuteurK8sDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        secrets = await depot_cluster.secrets(ctx, travail.cible_id or "")
        mid = secrets.get("magnum_cluster_id")
        if mid:
            amont().supprimer_cluster(mid)
        await depot_pool.supprimer_enfants(ctx, travail.cible_id or "")
        await depot_cluster.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("k8s.upgrade")
class ExecuteurK8sUpgrade(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        cluster = await depot_cluster.obtenir(ctx, travail.cible_id or "")
        await depot_cluster.remplacer(
            ctx,
            travail.cible_id or "",
            cluster.model_copy(
                update={
                    "version": travail.entree.get("version") or cluster.version,
                    "statut": "running",
                }
            ),
        )


@executeur("k8s.pool.create")
class ExecuteurK8sPoolCreate(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        pool = m.PoolWorkers.model_validate(travail.entree)
        await depot_pool.creer(ctx, pool, parent_id=travail.cible_id, id_=nouvel_id())


@executeur("k8s.pool.roll")
class ExecuteurK8sPoolRoll(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        nom = travail.contexte.get("nom", "")
        nouveau = m.PoolWorkers.model_validate(travail.entree)
        for r in await depot_pool.lignes(ctx, parent_id=travail.cible_id or ""):
            if (r.donnees or {}).get("nom") == nom:
                r.donnees = nouveau.model_dump(mode="json")
                await ctx.session.flush()
                break


@executeur("k8s.pool.delete")
class ExecuteurK8sPoolDelete(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        nom = travail.contexte.get("nom", "")
        for r in await depot_pool.lignes(ctx, parent_id=travail.cible_id or ""):
            if (r.donnees or {}).get("nom") == nom:
                await ctx.session.delete(r)
                await ctx.session.flush()
                break


@executeur("k8s.modules")
class ExecuteurK8sModules(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        cluster = await depot_cluster.obtenir(ctx, travail.cible_id or "")
        modules = travail.entree.get("modules") or cluster.modules
        await depot_cluster.remplacer(
            ctx,
            travail.cible_id or "",
            cluster.model_copy(update={"modules": modules, "statut": "running"}),
        )
