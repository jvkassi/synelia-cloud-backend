from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from synelia_contract import modeles as m
from synelia_kernel import erreurs
from synelia_kernel.ids import nouvel_id

from synelia.audit import journaliser
from synelia.deps import Contexte, Page, exige, exiger_confirmation
from synelia.modules.web_hebergement.service import depot, depot_bases
from synelia.travaux import demarrer_travail

router = APIRouter(prefix="/web/bases", tags=["Web Cloud — bases"])


@router.get("", response_model=m.WebBasesGetResponse, response_model_exclude_none=True)
async def lister_serveurs_bases(
    page: Page,
    hebergementId: str | None = None,
    moteur: str | None = None,
    actif: bool | None = None,
    ctx: Contexte = Depends(exige(None)),
) -> Any:  # noqa: N803, PLR0917
    return await depot_bases.lister(
        ctx,
        page,
        filtre=lambda s: (
            (not hebergementId or s.hebergementId == hebergementId)
            and (not moteur or s.moteur == moteur)
            and (actif is None or s.actif == actif)
        ),
        tri_defaut="serveur",
    )


@router.get("/{serveurId}", response_model=m.ServeurBases, response_model_exclude_none=True)
async def obtenir_serveur_bases(serveurId: str, ctx: Contexte = Depends(exige(None))) -> Any:  # noqa: N803
    await depot.obtenir(ctx, (await depot_bases.obtenir(ctx, serveurId)).hebergementId)
    return await depot_bases.obtenir(ctx, serveurId)


@router.patch("/{serveurId}", response_model=m.ServeurBases, response_model_exclude_none=True)
async def modifier_serveur_bases(
    serveurId: str,
    corps: m.WebBasesServeurIdPatchRequest,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Any:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    await depot_bases.modifier(ctx, serveurId, corps)
    await journaliser(
        ctx,
        action="bases.modification",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return await depot_bases.obtenir(ctx, serveurId)


@router.post(
    "/{serveurId}/bases",
    response_model=m.BaseHebergement,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def creer_base_hebergement(
    serveurId: str,
    corps: m.BaseHebergementCreation,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Any:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    for b in s.bases:
        if b.nom == corps.nom:
            raise erreurs.nom_deja_pris(corps.nom)
    base = m.BaseHebergement(
        id=nouvel_id(),
        hebergementId=s.hebergementId,
        nom=corps.nom,
        moteur="mariadb" if s.moteur == "mariadb" else "postgresql",
        version=s.version,
        tailleMo=0.0,
        jeuCaracteres=corps.jeuCaracteres or "utf8mb4",
        utilisateurs=[
            m.UtilisateurInline(
                nom=corps.utilisateur.nom,
                droits=corps.utilisateur.droits or "tous",
                hote="localhost",
            )
        ]
        if corps.utilisateur
        else [],
        siteId=corps.siteId,
    )
    await depot_bases.remplacer(
        ctx,
        serveurId,
        s.model_copy(
            update={
                "bases": [*s.bases, m.Base(nom=base.nom, tailleMo=base.tailleMo, utilise="actif")],
                "connexions": m.Connexions1(
                    actives=(s.connexions.actives or 0) + 1,
                    max=(s.connexions.max if s.connexions else 20),
                ),
            }
        ),
    )
    await journaliser(
        ctx,
        action="bases.base.creation",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        cible=corps.nom,
        details={"base": base.nom},
    )
    return base


@router.delete("/{serveurId}/bases/{baseNom}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_base_hebergement(
    serveurId: str,
    baseNom: str,
    confirmation: str | None = None,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Response:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    exiger_confirmation(baseNom, confirmation)
    if not any(b.nom == baseNom for b in s.bases):
        raise erreurs.introuvable("Base", baseNom)
    reste = [b for b in s.bases if b.nom != baseNom]
    await depot_bases.remplacer(
        ctx,
        serveurId,
        s.model_copy(
            update={
                "bases": reste,
                "connexions": m.Connexions1(
                    actives=max(0, (s.connexions.actives or 0) - 1),
                    max=(s.connexions.max if s.connexions else 20),
                ),
            }
        ),
    )
    await journaliser(
        ctx,
        action="bases.base.suppression",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        cible=baseNom,
    )
    return Response(status_code=204)


@router.post(
    "/{serveurId}/bases/{baseNom}/export",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def exporter_base_hebergement(
    serveurId: str,
    baseNom: str,
    corps: m.WebBasesServeurIdBasesBaseNomExportPostRequest,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Any:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    if not any(b.nom == baseNom for b in s.bases):
        raise erreurs.introuvable("Base", baseNom)
    await journaliser(
        ctx,
        action="bases.base.export",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        cible=baseNom,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return await demarrer_travail(
        ctx,
        "base.export",
        baseNom,
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        etapes=[
            {"nom": "Dump de la base", "dureeS": 8},
            {"nom": "Compresser et archiver", "dureeS": 5},
            {"nom": "Déposer dans le stockage objet", "dureeS": 6},
        ],
    )


@router.post(
    "/{serveurId}/bases/{baseNom}/import",
    response_model=m.TravailProvisioning,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def importer_base_hebergement(
    serveurId: str,
    baseNom: str,
    corps: m.WebBasesServeurIdBasesBaseNomImportPostRequest,
    confirmation: str | None = None,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Any:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    exiger_confirmation(baseNom, confirmation)
    await journaliser(
        ctx,
        action="bases.base.import",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        cible=baseNom,
        details=corps.model_dump(mode="json"),
    )
    return await demarrer_travail(
        ctx,
        "base.import",
        baseNom,
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        etapes=[
            {"nom": "Télécharger l'archive", "dureeS": 6},
            {"nom": "Restaurer dans la base", "dureeS": 25},
            {"nom": "Vérifier l'intégrité", "dureeS": 5},
        ],
    )


@router.post(
    "/{serveurId}/utilisateurs",
    response_model=m.ServeurBases,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def creer_utilisateur_base_hebergement(
    serveurId: str,
    corps: m.WebBasesServeurIdUtilisateursPostRequest,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Any:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    if not any(b.nom == corps.base for b in s.bases):
        raise erreurs.introuvable("Base", corps.base)
    for u in s.utilisateurs:
        if u.nom == corps.nom:
            raise erreurs.nom_deja_pris(corps.nom)
    utilisateur = m.Utilisateur2(nom=corps.nom, droits=corps.droits, base=corps.base)
    maj = s.model_copy(update={"utilisateurs": [*s.utilisateurs, utilisateur]})
    await depot_bases.remplacer(ctx, serveurId, maj)
    await depot_bases.definir_secrets(
        ctx, serveurId, {f"utilisateur_{corps.nom}": corps.motDePasse}
    )
    await journaliser(
        ctx,
        action="bases.utilisateur.creation",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        cible=corps.nom,
    )
    return maj


@router.patch(
    "/{serveurId}/utilisateurs/{utilisateurNom}",
    response_model=m.ServeurBases,
    response_model_exclude_none=True,
)
async def modifier_utilisateur_base_hebergement(
    serveurId: str,
    utilisateurNom: str,
    corps: m.WebBasesServeurIdUtilisateursUtilisateurNomPatchRequest,
    ctx: Contexte = Depends(exige("service.admin")),
) -> Any:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    cible = next((u for u in s.utilisateurs if u.nom == utilisateurNom), None)
    if cible is None:
        raise erreurs.introuvable("Utilisateur", utilisateurNom)
    if corps.droits:
        cible = cible.model_copy(update={"droits": corps.droits})
    maj = s.model_copy(
        update={"utilisateurs": [cible if u.nom == utilisateurNom else u for u in s.utilisateurs]}
    )
    await depot_bases.remplacer(ctx, serveurId, maj)
    if corps.motDePasse:
        await depot_bases.definir_secrets(
            ctx, serveurId, {f"utilisateur_{utilisateurNom}": corps.motDePasse}
        )
    await journaliser(
        ctx,
        action="bases.utilisateur.modification",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        cible=utilisateurNom,
        details=corps.model_dump(mode="json", exclude_none=True),
    )
    return maj


@router.delete("/{serveurId}/utilisateurs/{utilisateurNom}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_utilisateur_base_hebergement(
    serveurId: str, utilisateurNom: str, ctx: Contexte = Depends(exige("service.admin"))
) -> Response:  # noqa: N803
    s = await depot_bases.obtenir(ctx, serveurId)
    await depot.obtenir(ctx, s.hebergementId)
    if not any(u.nom == utilisateurNom for u in s.utilisateurs):
        raise erreurs.introuvable("Utilisateur", utilisateurNom)
    maj = s.model_copy(
        update={"utilisateurs": [u for u in s.utilisateurs if u.nom != utilisateurNom]}
    )
    await depot_bases.remplacer(ctx, serveurId, maj)
    await journaliser(
        ctx,
        action="bases.utilisateur.suppression",
        cible_type="web_serveur_bases",
        cible_id=serveurId,
        cible=utilisateurNom,
    )
    return Response(status_code=204)
