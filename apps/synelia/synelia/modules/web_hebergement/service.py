from __future__ import annotations

from typing import Any

from synelia_contract import modeles as m
from synelia_db.modeles import Travail
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id
from synelia_openstack import fournisseur
from synelia_openstack.plesk import PleskOpenStack, PleskSimule

from synelia.depot import Depot
from synelia.deps.contexte import Contexte
from synelia.travaux import Executeur, executeur

depot = Depot(
    "web_hebergement",
    m.Hebergement,
    libelle="Hébergement",
    champ_statut="statut",
    champ_nom="domaineProvisoire",
)
depot_sites = Depot(
    "web_site", m.SiteWeb, libelle="Site Web", champ_statut="statut", champ_nom="hote"
)
depot_bases = Depot("web_serveur_bases", m.ServeurBases, libelle="Serveur de bases")
depot_comptes = Depot(
    "web_compte_fichiers", m.CompteFichiers, libelle="Compte fichiers", champ_statut="statut"
)
depot_taches = Depot(
    "web_tache", m.TachePlanifieeWeb, libelle="Tâche planifiée", champ_statut="statut"
)
depot_domaines = Depot("web_domaine", m.Domaine, libelle="Domaine", champ_nom="nom")

VERSIONS_PHP = ["8.1", "8.2", "8.3", "8.4"]

METRIQUES = [
    ("cpu", "%", "Utilisation CPU"),
    ("ram", "%", "Utilisation RAM"),
    ("stockage", "%", "Stockage"),
    ("requetes", "req/min", "Requêtes HTTP"),
    ("trafique", "Mo/s", "Trafic réseau"),
    ("bases", "nb", "Bases de données"),
]


def metriques(fenetre: str) -> dict[str, Any]:
    from datetime import timedelta

    from synelia_kernel.dates import iso

    nb_points = {"24h": 24, "7j": 7, "30j": 30}[fenetre]
    pas = {"24h": timedelta(hours=1), "7j": timedelta(days=1), "30j": timedelta(days=1)}
    origine = maintenant() - pas[fenetre] * (nb_points - 1)
    series = [
        m.Serie(
            metrique=metrique,
            unite=unite,
            fenetre=fenetre,  # type: ignore[arg-type]
            points=[
                m.PointSerie(ts=origine + pas[fenetre] * i, valeur=0.0) for i in range(nb_points)
            ],
        )
        for metrique, unite, _libelle in METRIQUES
    ]
    return {
        "tuiles": [],
        "series": [s for s in series],
        "liens": m.LiensSortie(
            centreon=f"https://monitoring.synelia.cloud/{iso(maintenant())}",
        ),
    }


def traduire_cron(expression: str) -> str:
    parts = expression.split()
    if len(parts) == 5:
        minutes, heures, _jours_mois, _mois, _jours_semaine = parts
        if minutes == "0" and heures.isdigit():
            return f"Tous les jours à {int(heures):02d}:00."
        if minutes == "*/5":
            return "Toutes les 5 minutes."
    return f"Planification : {expression}."


def amont() -> PleskSimule:
    return fournisseur(PleskSimule, PleskOpenStack)


def construire_hebergement(ctx: Contexte, corps: m.HebergementCreation) -> m.Hebergement:
    hid = nouvel_id()
    return m.Hebergement(
        id=hid,
        orgId=ctx.org_id,
        domaine=corps.domaine,
        domaineProvisoire=f"h-{hid[:8]}.synelia.cloud",
        palier=corps.palier,
        serveur=m.Serveur(
            nom=f"srv-{hid[:8]}",
            vcpu={"starter": 1, "pro": 2, "business": 4, "enterprise": 8}.get(corps.palier, 2),
            ramGo={"starter": 2, "pro": 4, "business": 8, "enterprise": 16}.get(corps.palier, 4),
            diskGo={"starter": 40, "pro": 80, "business": 160, "enterprise": 320}.get(
                corps.palier, 80
            ),
            ip=f"192.168.{hash(hid) % 250}.10",
            site=corps.site,
            os="Debian 12",
            serveurWeb="Nginx 1.26",
            statut="en_ligne",
            chargeCpuPct=12.0,
        ),
        php=m.Php(
            versionDefaut=corps.versionPhp or "8.2",
            versionsDisponibles=list(VERSIONS_PHP),
            extensions=[
                m.Extension(nom=e, active=True)
                for e in ["curl", "mbstring", "xml", "mysqli", "gd", "opcache"]
            ],
            limites=m.Limites(memoryLimitMo=256, uploadMaxMo=64, maxExecutionS=30, opcache=True),
        ),
        acces=m.Acces(ftp=True, sftp=True, ftps=False, ssh=False, portSsh=22),
        espaceUtiliseGo=0.0,
        espaceTotalGo=float(
            {"starter": 40, "pro": 80, "business": 160, "enterprise": 320}.get(corps.palier, 80)
        ),
        sauvegarde=m.Sauvegarde(
            frequence="quotidienne",
            heure="02:00",
            retentionJours=14,
            destination="Object Storage — région ABJ",
            immuable=True,
            statut="en_cours",
        ),
        statut="maintenance",
        cree=maintenant(),
    )


def construire_serveur_bases(ctx: Contexte, hebergement_id: str) -> m.ServeurBases:
    return m.ServeurBases(
        id=nouvel_id(),
        hebergementId=hebergement_id,
        serveur=f"db-{hebergement_id[:8]}",
        moteur="mariadb",
        version="MariaDB 10.11",
        actif=True,
        hoteInterne="localhost",
        port=3306,
        bases=[],
        utilisateurs=[],
        quotaMo=1024.0,
        utiliseMo=0.0,
        connexions=m.Connexions1(actives=0, max=20),
        sauvegarde=m.Sauvegarde1(frequence="quotidienne", derniere=maintenant(), retentionJours=7),
        prixMensuel=5000,
    )


def construire_site(
    ctx: Contexte, hebergement_id: str, creation: m.SiteWebCreation, preprod: bool = False
) -> m.SiteWeb:
    return m.SiteWeb(
        id=nouvel_id(),
        hebergementId=hebergement_id,
        hote=creation.hote,
        racine=creation.racine or f"/var/www/{creation.hote}",
        type=creation.type,
        version=creation.version or _version_defaut(creation.type),
        phpVersion=creation.phpVersion or "8.2",
        baseId=None,
        ssl=m.Ssl(
            etat="en_emission" if creation.ssl else "actif",
            emetteur="Let's Encrypt" if creation.ssl else None,
        ),
        espaceMo=0.0,
        visitesMois=0,
        preproduction=m.Preproduction(actif=True, hote=f"preprod.{creation.hote}")
        if preprod
        else None,
        majEnAttente=0,
        securite=m.Securite(waf=False, bruteForce=True, scanMalware=True),
        statut="en_ligne",
    )


def _version_defaut(type_: str) -> str | None:
    return {"wordpress": "6.7", "prestashop": "8.2", "laravel": "11", "php": "8.2"}.get(type_)


SERVICES_PARTAGES = [
    m.ServicePartage(
        id=str(i),
        hebergementId="",
        slug=slug,
        nom=nom,
        solution=solution,
        hote=hote,
        usage=m.Usage1(libelle=libelle, utilise=utilise, total=total, unite=unite),
        version=version,
        sante="ok",
        urlOuverture=f"https://{hote}/",
        actif=True,
    )
    for i, (slug, nom, solution, hote, libelle, utilise, total, unite, version) in enumerate(
        [
            (
                "messagerie",
                "Messagerie",
                "Stalwart",
                "mail.synelia.cloud",
                "Boîtes",
                0,
                10,
                "boîtes",
                "2.5",
            ),
            (
                "drive",
                "Drive",
                "Nextcloud",
                "drive.synelia.cloud",
                "Stockage",
                0,
                100,
                "Go",
                "29.0",
            ),
            (
                "statistiques",
                "Statistiques de visite",
                "Matomo",
                "stats.synelia.cloud",
                "Sites suivis",
                0,
                3,
                "sites",
                "5.2",
            ),
        ]
    )
]


@executeur("hebergement.creer")
class ExecuteurHebergementCreer(Executeur):
    compensable = True

    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        base = await depot_bases.creer(
            ctx, construire_serveur_bases(ctx, travail.cible_id or ""), parent_id=travail.cible_id
        )
        travail.contexte = {**travail.contexte, "serveur_bases_id": base.id}
        await depot.definir_statut(ctx, travail.cible_id or "", "en_ligne")

    async def compenser(self, ctx: Contexte, travail: Travail, index_echoue: int) -> None:
        await depot.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("hebergement.supprimer")
class ExecuteurHebergementSupprimer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_enfants(ctx, travail.cible_id or "")
        await depot.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("hebergement.redemarrer")
class ExecuteurHebergementRedemarrer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot.definir_statut(ctx, travail.cible_id or "", "en_ligne")


@executeur("site.installer")
class ExecuteurSiteInstaller(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_sites.definir_statut(ctx, travail.cible_id or "", "en_ligne")


@executeur("site.supprimer")
class ExecuteurSiteSupprimer(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        await depot_sites.supprimer(ctx, travail.cible_id or "", logique=True)


@executeur("site.analyse_securite")
class ExecuteurSiteAnalyse(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(
            ctx,
            s.id,
            s.model_copy(
                update={"securite": m.Securite(waf=True, bruteForce=True, scanMalware=True)}
            ),
        )


@executeur("site.preproduction")
class ExecuteurSitePreproduction(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(
            ctx,
            s.id,
            s.model_copy(
                update={
                    "preproduction": m.Preproduction(
                        actif=True, hote=f"preprod.{s.hote}", derniereSync=maintenant()
                    ),
                    "statut": "en_ligne",
                }
            ),
        )


@executeur("site.mise_en_production")
class ExecuteurSiteMiseEnProduction(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(
            ctx, s.id, s.model_copy(update={"preproduction": None, "statut": "en_ligne"})
        )


@executeur("site.mise_a_jour")
class ExecuteurSiteMiseAJour(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        s = await depot_sites.obtenir(ctx, travail.cible_id or "")
        await depot_sites.remplacer(ctx, s.id, s.model_copy(update={"majEnAttente": 0}))


@executeur("base.export")
class ExecuteurBaseExport(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        return None


@executeur("base.import")
class ExecuteurBaseImport(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        return None


@executeur("tache.execution")
class ExecuteurTacheExecution(Executeur):
    async def terminer(self, ctx: Contexte, travail: Travail) -> None:
        t = await depot_taches.obtenir(ctx, travail.cible_id or "")
        await depot_taches.remplacer(
            ctx,
            t.id,
            t.model_copy(update={"derniereExecution": maintenant(), "statut": "ok", "dureeS": 3}),
        )


async def depot_enfants(ctx: Contexte, hebergement_id: str) -> None:
    await depot_comptes.supprimer_enfants(ctx, hebergement_id)
    await depot_taches.supprimer_enfants(ctx, hebergement_id)
    for s in await depot_sites.tous(ctx, filtre=lambda x: x.hebergementId == hebergement_id):
        await depot_sites.supprimer(ctx, s.id, logique=True)
