"""Secrets en base : AES-256-GCM avec clé d'enveloppe dérivée de la clé maître."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from synelia_kernel.config import reglages


def _cle() -> bytes:
    r = reglages()
    if r.cle_maitre:
        return base64.b64decode(r.cle_maitre)
    return hashlib.sha256(f"synelia-cle-maitre:{r.secret}".encode()).digest()


def chiffrer(clair: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_cle()).encrypt(nonce, clair.encode(), b"synelia")
    return "v1:" + base64.urlsafe_b64encode(nonce + ct).decode()


def dechiffrer(chiffre: str) -> str:
    if not chiffre.startswith("v1:"):
        raise ValueError("format de secret inconnu")
    brut = base64.urlsafe_b64decode(chiffre[3:])
    return AESGCM(_cle()).decrypt(brut[:12], brut[12:], b"synelia").decode()


def empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode()).hexdigest()
