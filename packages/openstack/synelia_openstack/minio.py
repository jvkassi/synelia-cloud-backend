"""Amont stockage objet (S3-compatible) : MinIO, une instance unique partagée (comme AWS S3).

L'isolation par organisation se fait par le nommage des buckets (préfixés par l'organisation,
voir `synelia.modules.stockage.service.nom_reel_bucket`) et par des utilisateurs + policies IAM
scopés aux buckets demandés — pas par une instance MinIO dédiée par organisation.

Paire `MinioSimule` / `MinioReel`. Le réel n'est appelé que si `SYNELIA_MINIO_URL` est défini.
Le SDK officiel `minio` gère les buckets/objets (S3 API) ; il ne couvre pas l'administration
IAM (utilisateurs, policies), qui n'existe que dans l'API d'admin MinIO — on y accède via le
client `mc` (présent dans l'image `minio/minio` et installé dans l'image de l'API)."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import tempfile
from typing import Any

from synelia_kernel import erreurs
from synelia_kernel.ids import jeton_opaque, nouvel_id

ENV_URL = "SYNELIA_MINIO_URL"
ENV_ROOT_USER = "SYNELIA_MINIO_ROOT_USER"
ENV_ROOT_PASSWORD = "SYNELIA_MINIO_ROOT_PASSWORD"

_ALIAS = "synelia"

_ACTIONS_PAR_DROITS = {
    "lecture": ["s3:GetObject", "s3:ListBucket"],
    "ecriture": ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
    "lecture_ecriture": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
}


class MinioSimule:
    def creer_bucket(self, nom: str, region: str | None = None) -> dict[str, Any]:
        return {"id": nom, "taille_go": 0.0, "objets": 0}

    def supprimer_bucket(self, nom: str) -> None:
        return None

    def usage(self, nom: str) -> dict[str, Any]:
        return {"taille_go": 0.0, "objets": 0, "requetes": 0, "egress_go": 0.0}

    def creer_cle_s3(self, nom: str, buckets: list[str] | None, droits: str) -> dict[str, str]:
        return {
            "access_key_id": f"AKIA{nouvel_id()[:16].upper()}",
            "secret_access_key": jeton_opaque(32),
            "endpoint": "https://obj.synelia.cloud",
        }

    def revoquer_cle_s3(self, cle_id: str) -> None:
        return None


class MinioReel(MinioSimule):
    def __init__(self) -> None:
        self.url = os.environ[ENV_URL].rstrip("/")
        self.root_user = os.environ.get(ENV_ROOT_USER, "")
        self.root_password = os.environ.get(ENV_ROOT_PASSWORD, "")
        self._alias_pret = False

    # ── S3 (buckets, objets) via le SDK `minio` ───────────────────────────
    def _client(self):
        from minio import Minio  # import paresseux : dépendance non nécessaire en simulé

        endpoint = self.url.split("://", 1)[-1]
        return Minio(
            endpoint,
            access_key=self.root_user,
            secret_key=self.root_password,
            secure=self.url.startswith("https://"),
        )

    def creer_bucket(self, nom: str, region: str | None = None) -> dict[str, Any]:
        c = self._client()
        try:
            if not c.bucket_exists(nom):
                c.make_bucket(nom)
        except Exception as exc:  # noqa: BLE001
            raise erreurs.amont_indisponible("minio", str(exc)) from exc
        return {"id": nom, "taille_go": 0.0, "objets": 0}

    def supprimer_bucket(self, nom: str) -> None:
        c = self._client()
        try:
            if not c.bucket_exists(nom):
                return
            for o in c.list_objects(nom, recursive=True):
                c.remove_object(nom, o.object_name)
            c.remove_bucket(nom)
        except Exception as exc:  # noqa: BLE001
            raise erreurs.amont_indisponible("minio", str(exc)) from exc

    def usage(self, nom: str) -> dict[str, Any]:
        c = self._client()
        try:
            if not c.bucket_exists(nom):
                return {"taille_go": 0.0, "objets": 0, "requetes": 0, "egress_go": 0.0}
            objets = list(c.list_objects(nom, recursive=True))
        except Exception as exc:  # noqa: BLE001
            raise erreurs.amont_indisponible("minio", str(exc)) from exc
        total = sum((o.size or 0) for o in objets)
        return {
            "taille_go": round(total / 2**30, 3),
            "objets": len(objets),
            "requetes": 0,
            "egress_go": 0.0,
        }

    # ── IAM (utilisateurs, policies) via `mc admin` ───────────────────────
    def _config_dir(self) -> str:
        # `$HOME/.mc` par défaut, souvent en lecture seule dans le conteneur : on force un
        # répertoire de configuration inscriptible.
        chemin = os.path.join(tempfile.gettempdir(), "mc-synelia")
        os.makedirs(chemin, exist_ok=True)
        return chemin

    def _preparer_alias(self) -> None:
        if self._alias_pret:
            return
        subprocess.run(
            [
                "mc",
                "--config-dir",
                self._config_dir(),
                "alias",
                "set",
                _ALIAS,
                self.url,
                self.root_user,
                self.root_password,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self._alias_pret = True

    def _mc(self, *args: str) -> str:
        self._preparer_alias()
        try:
            r = subprocess.run(
                ["mc", "--config-dir", self._config_dir(), *args, "--json"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError as exc:
            raise erreurs.amont_indisponible("minio", "client `mc` introuvable") from exc
        if r.returncode != 0:
            raise erreurs.amont_indisponible("minio", (r.stderr or r.stdout).strip()[:300])
        return r.stdout

    def creer_cle_s3(self, nom: str, buckets: list[str] | None, droits: str) -> dict[str, str]:
        access_key_id = f"SYN{secrets.token_hex(8).upper()}"
        secret_access_key = jeton_opaque(32)
        self._mc("admin", "user", "add", _ALIAS, access_key_id, secret_access_key)
        actions = _ACTIONS_PAR_DROITS.get(droits, _ACTIONS_PAR_DROITS["lecture"])
        cibles = buckets or ["*"]
        ressources = []
        for b in cibles:
            ressources.append(f"arn:aws:s3:::{b}")
            ressources.append(f"arn:aws:s3:::{b}/*")
        politique = {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": actions, "Resource": ressources}],
        }
        nom_politique = f"pol-{access_key_id.lower()}"
        fd, chemin = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(politique, f)
            self._mc("admin", "policy", "create", _ALIAS, nom_politique, chemin)
        finally:
            os.unlink(chemin)
        self._mc("admin", "policy", "attach", _ALIAS, nom_politique, "--user", access_key_id)
        return {
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
            "endpoint": self.url,
        }

    def revoquer_cle_s3(self, cle_id: str) -> None:
        self._mc("admin", "user", "remove", _ALIAS, cle_id)


def choisir_minio() -> MinioSimule:
    if os.environ.get(ENV_URL):
        return MinioReel()
    return MinioSimule()
