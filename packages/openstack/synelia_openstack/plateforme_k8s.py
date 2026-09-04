"""Plateforme applicative K8s (Argo) et dépôts Git (GitHub) — amonts NON OpenStack.

Même motif que `identite.py` : une paire `XxxSimule` / `XxxReel` choisie par
`synelia_openstack.fabrique.fournisseur`. Le réel appelle l'amont via `httpx`
**seulement** si les variables d'environnement d'accès sont définies ; sinon le
simulé renvoie des valeurs plausibles instantanément (jamais de réseau en test).
"""

from __future__ import annotations

import os
import re
from typing import Any

from synelia_kernel import erreurs


def _amont_dispo(cle: str) -> bool:
    return bool(os.environ.get(cle))


class ArgoSimule:
    """Aucun Argo : simule les Applications Argo CD, instantanément."""

    def liste_applications(self, org_id: str | None = None) -> list[dict[str, Any]]:
        return []

    def creer_application(
        self, nom: str, repo_url: str, chemin: str, namespace: str, cible_revision: str = "HEAD"
    ) -> dict[str, Any]:
        return {
            "nom": nom,
            "namespace": namespace,
            "syncStatus": "OutOfSync",
            "healthStatus": "Progressing",
        }

    def statut_application(self, nom: str) -> dict[str, Any]:
        return {"nom": nom, "syncStatus": "Synced", "healthStatus": "Healthy"}

    def supprimer_application(self, nom: str) -> None:
        return None


class ArgoReel(ArgoSimule):
    """httpx vers l'API Argo CD quand `SYNELIA_ARGOCD_URL` est définie."""

    def _client(self):
        import httpx

        url = os.environ.get("SYNELIA_ARGOCD_URL")
        if not url:
            raise erreurs.amont_indisponible("argo", "Argo CD non configuré.")
        headers = {}
        if os.environ.get("SYNELIA_ARGOCD_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['SYNELIA_ARGOCD_TOKEN']}"
        return httpx.AsyncClient(base_url=url, headers=headers, timeout=15)

    def liste_applications(self, org_id: str | None = None) -> list[dict[str, Any]]:
        raise erreurs.amont_indisponible("argo", "Liste des Applications Argo.")

    def creer_application(
        self, nom: str, repo_url: str, chemin: str, namespace: str, cible_revision: str = "HEAD"
    ) -> dict[str, Any]:
        raise erreurs.amont_indisponible("argo", "Création d'Application Argo.")

    def statut_application(self, nom: str) -> dict[str, Any]:
        raise erreurs.amont_indisponible("argo", "Statut d'Application Argo.")

    def supprimer_application(self, nom: str) -> None:
        raise erreurs.amont_indisponible("argo", "Suppression d'Application Argo.")


class DepotsSimule:
    """Aucun GitHub : ne liste les branches que si `SYNELIA_GITHUB_TOKEN` est posé.

    Sans jeton, `branches` lève `amont_indisponible("github", donnees_partielles=[])`.
    """

    def listable(self) -> bool:
        return _amont_dispo("SYNELIA_GITHUB_TOKEN")

    def branches(self, provider: str, url: str) -> list[dict[str, Any]]:
        if not self.listable():
            raise erreurs.amont_indisponible(
                "github", "GitHub non configuré.", donnees_partielles=[]
            )
        raise erreurs.amont_indisponible("github", "Lecture des branches.")

    def analyser(self, provider: str, url: str, branche: str | None = None) -> dict[str, Any]:
        # Heuristique hors réseau : déduction du framework depuis l'URL.
        return {
            "builder": "nixpacks",
            "cible": "vm",
            "framework": _deviner_framework(url),
            "constats": [],
        }


def _deviner_framework(url: str) -> str | None:
    u = url.lower()
    for cle, nom in (
        ("next", "Next.js"),
        ("nuxt", "Nuxt"),
        ("react", "React"),
        ("vue", "Vue"),
        ("angular", "Angular"),
        ("svelte", "Svelte"),
        ("django", "Django"),
        ("flask", "Flask"),
        ("rails", "Rails"),
        ("laravel", "Laravel"),
        ("symfony", "Symfony"),
        ("fastapi", "FastAPI"),
        ("express", "Express"),
        ("nest", "NestJS"),
    ):
        if cle in u:
            return nom
    return None


class DepotsReel(DepotsSimule):
    """httpx vers l'API GitHub quand `SYNELIA_GITHUB_TOKEN` est définie."""

    def _delimiter(self, url: str) -> tuple[str, str]:
        # github → https://api.github.com/repos/{org}/{repo}
        if "github.com" in url or "github" == url:
            m = re.search(r"://[^/]+/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
            if not m:
                raise erreurs.validation("URL de dépôt GitHub invalide.", champs=["url"])
            return "github", f"{m.group(1)}/{m.group(2)}"
        if "gitlab" in url:
            m = re.search(r"://[^/]+/(.+?)(?:\.git)?/?$", url)
            if not m:
                raise erreurs.validation("URL de dépôt GitLab invalide.", champs=["url"])
            return "gitlab", m.group(1)
        raise erreurs.validation("Fournisseur de dépôt non pris en charge.", champs=["url"])

    def branches(self, provider: str, url: str) -> list[dict[str, Any]]:
        if not self.listable():
            raise erreurs.amont_indisponible(
                "github", "GitHub non configuré.", donnees_partielles=[]
            )
        base, chemin = self._delimiter(url)
        api = "https://api.github.com" if base == "github" else "https://gitlab.com/api/v4"
        import httpx

        headers = {"Authorization": f"Bearer {os.environ.get('SYNELIA_GITHUB_TOKEN')}"}
        if base == "github":
            r = httpx.get(f"{api}/repos/{chemin}/branches", headers=headers, timeout=15)
            r.raise_for_status()
            return [
                {
                    "nom": b["name"],
                    "defaut": False,
                    "dernierCommit": {
                        "sha": b["commit"]["sha"],
                        "message": "",
                        "auteur": None,
                        "date": None,
                    },
                }
                for b in r.json()
            ]
        raise erreurs.amont_indisponible("github", "GitLab non configuré.")
