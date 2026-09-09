"""Paiement Paystack (sandbox) : carte et mobile money (Orange Money, MTN MoMo, Wave).

Deux chemins mènent au même paiement, et c'est volontaire : le webhook Paystack peut ne
jamais atteindre dev01 (URL de labo, pas de domaine public stable garanti), donc le callback
du popup Inline.js appelle aussi `/verifier/{reference}` côté serveur (qui revérifie auprès de
Paystack avec la clé secrète, jamais en faisant confiance au client) — la démo marche même si
le webhook n'arrive jamais. Idempotent des deux côtés : une facture déjà `payee` ne l'est pas
deux fois.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from synelia_contract import modeles as m
from synelia_db import rls
from synelia_db.session import fabrique
from synelia_kernel.config import reglages
from synelia_kernel.journal import journal

from synelia.audit import journaliser
from synelia.depot import Depot
from synelia.deps.contexte import Principal
from synelia.modules.facturation.service import crediter

log = journal("paystack")

_SEPARATEUR = "--"
_PREFIXE = "SYN"


def cle_secrete() -> str | None:
    return os.environ.get("PAYSTACK_SECRET_KEY")


def verifier_signature(corps_brut: bytes, signature: str | None) -> bool:
    secret = cle_secrete()
    if not secret or not signature:
        return False
    attendu = hmac.new(secret.encode(), corps_brut, hashlib.sha512).hexdigest()
    return hmac.compare_digest(attendu, signature)


def generer_reference(org_id: str, facture_id: str) -> str:
    # Séparateur double tiret : les identifiants (org-…, fa-…) n'en contiennent
    # jamais, ce qui permet de les retrouver sans ambiguïté au retour.
    # token_hex, pas token_urlsafe : ce dernier peut produire un `-`, ce qui casserait le
    # découpage sur `--` au retour.
    return _SEPARATEUR.join([_PREFIXE, org_id, facture_id, secrets.token_hex(6)])


def _decoder_reference(reference: str) -> tuple[str, str] | None:
    morceaux = reference.split(_SEPARATEUR)
    if len(morceaux) != 4 or morceaux[0] != _PREFIXE:
        return None
    return morceaux[1], morceaux[2]


@dataclass
class _ContexteService:
    """Contexte minimal pour un traitement hors requête HTTP (webhook, tâche planifiée) :
    seuls `session`, `reglages` et `principal.org_id` sont lus par `Depot`/`crediter`."""

    session: Any
    reglages: Any
    org_id_force: str

    request: Any = None
    correlation_id: str = "paystack"
    langue: str = "fr"

    def __post_init__(self) -> None:
        self.principal = Principal(
            utilisateur_id=None,
            email="paystack@synelia.cloud",
            nom="Paystack",
            org_id=self.org_id_force,
            role="systeme",
            equipe=True,
            role_equipe="operateur",
        )

    @property
    def org_id(self) -> str:
        return self.org_id_force


async def confirmer_paiement(
    org_id: str, facture_id: str, *, montant_paye: int, moyen: str, reference: str
) -> bool:
    """Idempotent. Renvoie True si la facture vient d'être marquée payée, False si elle
    l'était déjà ou si son montant ne correspond pas (Paystack sandbox permet de fabriquer
    des événements arbitraires — on ne crédite jamais sans vérifier le montant)."""
    jeton = rls.org_id_transaction.set(org_id)
    try:
        async with fabrique()() as session:
            ctx = _ContexteService(session=session, reglages=reglages(), org_id_force=org_id)
            depot: Depot[m.Facture] = Depot("facture", m.Facture)
            facture = await depot.obtenir(ctx, facture_id)
            if facture.statut == "payee":
                log.info("paystack.deja_payee", facture_id=facture_id, reference=reference)
                return False
            if montant_paye != facture.total:
                log.warning(
                    "paystack.montant_incoherent",
                    facture_id=facture_id,
                    attendu=facture.total,
                    recu=montant_paye,
                )
                return False
            await crediter(ctx, org_id, f"Paiement Paystack facture {facture.numero}", facture.total)
            await depot.definir_statut(ctx, facture_id, "payee", moyen=moyen)
            await journaliser(
                ctx,
                action="facture.paiement",
                cible_type="facture",
                cible_id=facture_id,
                details={"fournisseur": "paystack", "reference": reference, "moyen": moyen},
            )
            await session.commit()
            log.info("paystack.paiement_confirme", facture_id=facture_id, reference=reference)
            return True
    finally:
        rls.org_id_transaction.reset(jeton)


_MOYEN_PAR_CANAL = {
    "card": "carte",
    "mobile_money": "orange_money",  # canal générique Paystack ; l'opérateur exact
    "bank_transfer": "virement",  # (Orange/MTN/Wave) n'est pas distingué par l'API.
}


async def traiter_evenement_charge_reussie(donnees: dict[str, Any]) -> bool:
    reference = donnees.get("reference", "")
    decode = _decoder_reference(reference)
    if decode is None:
        log.warning("paystack.reference_inconnue", reference=reference)
        return False
    org_id, facture_id = decode
    if donnees.get("status") != "success":
        return False
    canal = donnees.get("channel", "card")
    return await confirmer_paiement(
        org_id,
        facture_id,
        montant_paye=int(donnees.get("amount", 0)) // 100,
        moyen=_MOYEN_PAR_CANAL.get(canal, "carte"),
        reference=reference,
    )


async def verifier_aupres_de_paystack(reference: str) -> dict[str, Any] | None:
    """Rappelle Paystack avec la clé secrète plutôt que de faire confiance au popup côté
    client — c'est ce qui rend `/verifier/{reference}` sûr à exposer sans signature."""
    secret = cle_secrete()
    if not secret:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        rep = await client.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {secret}"},
        )
    if rep.status_code != 200:
        return None
    corps = rep.json()
    if not corps.get("status"):
        return None
    return corps.get("data")


def horodatage_utc() -> str:
    return datetime.now(UTC).isoformat()
