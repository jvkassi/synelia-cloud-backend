"""Courriels transactionnels (réinitialisation de mot de passe, invitations, MFA) : envoyés
via le compte SMTP administratif réel (`SYNELIA_SMTP_ADMIN_*`), pas le relais SMTP produit
(`relais_smtp.py`, qui sert les organisations clientes). Sans configuration, l'envoi est un
no-op silencieux et l'appelant garde son repli de journalisation dev existant."""

from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
from email.message import EmailMessage

ENV_HOTE = "SYNELIA_SMTP_ADMIN_HOTE"
ENV_UTILISATEUR = "SYNELIA_SMTP_ADMIN_UTILISATEUR"
ENV_MOT_DE_PASSE = "SYNELIA_SMTP_ADMIN_MOT_DE_PASSE"


def configure() -> bool:
    return bool(os.environ.get(ENV_HOTE) and os.environ.get(ENV_UTILISATEUR))


def _envoyer_bloquant(destinataire: str, sujet: str, corps: str) -> None:
    hote = os.environ[ENV_HOTE]
    utilisateur = os.environ[ENV_UTILISATEUR]
    mot_de_passe = os.environ.get(ENV_MOT_DE_PASSE, "")
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = utilisateur
    msg["To"] = destinataire
    msg.set_content(corps)
    with smtplib.SMTP(hote, 587, timeout=15) as client:
        client.ehlo()
        if client.has_extn("STARTTLS"):
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if mot_de_passe:
            client.login(utilisateur, mot_de_passe)
        client.send_message(msg)


async def envoyer(destinataire: str, sujet: str, corps: str) -> None:
    """Best-effort : une panne d'envoi ne doit jamais faire échouer le flux appelant
    (mot de passe oublié, invitation) — seulement être journalisée en amont_indisponible
    si l'appelant choisit de la relever."""
    if not configure():
        return
    await asyncio.to_thread(_envoyer_bloquant, destinataire, sujet, corps)
