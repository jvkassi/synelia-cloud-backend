"""Amorçage : équipe Synelia, organisation de démonstration, données plateforme (catalogue, référentiels).

Idempotent : ne recrée rien qui existe. Désactivable par SYNELIA_SEED_ADMIN_EMAIL vide."""

from __future__ import annotations

from sqlalchemy import select
from synelia_db.modeles import Membership, Organisation, Utilisateur
from synelia_db.session import fabrique
from synelia_kernel.config import reglages
from synelia_kernel.dates import maintenant
from synelia_kernel.journal import journal

from synelia.securite import hacher_mot_de_passe

log = journal("amorcage")

_AMORCE = False


async def amorcer() -> None:
    global _AMORCE
    if _AMORCE:
        return
    r = reglages()
    if not r.seed_admin_email or not r.seed_admin_mot_de_passe:
        return
    async with fabrique()() as s:
        admin = (
            await s.execute(select(Utilisateur).where(Utilisateur.email == r.seed_admin_email))
        ).scalar_one_or_none()
        if admin is None:
            org = Organisation(
                nom=r.seed_organisation,
                pays="CI",
                secteur="Cloud",
                statut="active",
                tenant_plan="entreprise",
                domaine="synelia.cloud",
            )
            s.add(org)
            await s.flush()
            admin = Utilisateur(
                email=r.seed_admin_email,
                nom="Administrateur Synelia",
                mot_de_passe_hash=hacher_mot_de_passe(r.seed_admin_mot_de_passe),
                idp_source="local",
                statut="actif",
                fonction="Super admin",
                org_active_id=org.id,
                equipe={"role": "super_admin", "depuis": maintenant().isoformat()},
            )
            s.add(admin)
            await s.flush()
            s.add(
                Membership(
                    utilisateur_id=admin.id, org_id=org.id, role="org_admin", scope_type="org"
                )
            )
            await s.commit()
            log.info("amorcage.admin_cree", email=r.seed_admin_email, organisation=org.nom)
            if r.seed_demo:
                from synelia.demo import peupler

                await peupler(s, org, admin)
                await s.commit()
        # Catalogue plateforme réel (Offres) : indépendant de SYNELIA_SEED_DEMO, rejoué à
        # chaque démarrage — idempotent, cf. `admin_catalogue.service.semer_catalogue_reel`.
        from synelia.modules.admin_catalogue.service import semer_catalogue_reel

        await semer_catalogue_reel(s)
        await s.commit()

        # Espace Cloud « plateforme » de la zone VPS partagée (réseau + LB Octavia public) :
        # même précédent, indépendant de SYNELIA_SEED_DEMO — cf. `espaces.service.semer_zone_vps`.
        from synelia.modules.espaces.service import semer_zone_vps

        await semer_zone_vps(s)
        await s.commit()
    _AMORCE = True
