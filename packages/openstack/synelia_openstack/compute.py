"""Nova + Glance : gabarits, images, serveurs."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import nouvel_id

GABARITS = [
    {
        "id": "s1.small",
        "nom": "S1 Small",
        "vcpu": 1,
        "ramGo": 2,
        "diskGo": 20,
        "famille": "economique",
        "prixMensuel": 9000,
        "sitesDisponibles": ["ABJ", "GBM"],
    },
    {
        "id": "g1.medium",
        "nom": "G1 Medium",
        "vcpu": 2,
        "ramGo": 4,
        "diskGo": 40,
        "famille": "generique",
        "prixMensuel": 19000,
        "sitesDisponibles": ["ABJ", "GBM"],
    },
    {
        "id": "g1.large",
        "nom": "G1 Large",
        "vcpu": 4,
        "ramGo": 8,
        "diskGo": 80,
        "famille": "generique",
        "prixMensuel": 38000,
        "sitesDisponibles": ["ABJ", "GBM"],
    },
    {
        "id": "g1.xlarge",
        "nom": "G1 XLarge",
        "vcpu": 8,
        "ramGo": 16,
        "diskGo": 160,
        "famille": "generique",
        "prixMensuel": 76000,
        "sitesDisponibles": ["ABJ"],
    },
    {
        "id": "c1.large",
        "nom": "C1 Calcul",
        "vcpu": 8,
        "ramGo": 8,
        "diskGo": 80,
        "famille": "calcul",
        "prixMensuel": 64000,
        "sitesDisponibles": ["ABJ"],
    },
    {
        "id": "m1.large",
        "nom": "M1 Mémoire",
        "vcpu": 4,
        "ramGo": 32,
        "diskGo": 80,
        "famille": "memoire",
        "prixMensuel": 72000,
        "sitesDisponibles": ["ABJ"],
    },
    {
        "id": "gpu1.a10",
        "nom": "GPU A10",
        "vcpu": 8,
        "ramGo": 32,
        "diskGo": 200,
        "famille": "gpu",
        "prixMensuel": 420000,
        "sitesDisponibles": ["ABJ"],
    },
]
IMAGES = [
    {
        "id": "ubuntu-24.04",
        "nom": "Ubuntu Server",
        "famille": "linux",
        "version": "24.04 LTS",
        "architecture": "x86_64",
        "tailleGo": 3,
        "sitesDisponibles": ["ABJ", "GBM"],
        "logicielsPreinstallables": ["docker", "nginx", "postgresql"],
    },
    {
        "id": "debian-12",
        "nom": "Debian",
        "famille": "linux",
        "version": "12",
        "architecture": "x86_64",
        "tailleGo": 2,
        "sitesDisponibles": ["ABJ", "GBM"],
    },
    {
        "id": "rocky-9",
        "nom": "Rocky Linux",
        "famille": "linux",
        "version": "9",
        "architecture": "x86_64",
        "tailleGo": 2,
        "sitesDisponibles": ["ABJ", "GBM"],
    },
    {
        "id": "alma-9",
        "nom": "AlmaLinux",
        "famille": "linux",
        "version": "9",
        "architecture": "x86_64",
        "tailleGo": 2,
        "sitesDisponibles": ["ABJ"],
    },
    {
        "id": "windows-2022",
        "nom": "Windows Server",
        "famille": "windows",
        "version": "2022",
        "architecture": "x86_64",
        "tailleGo": 12,
        "licencePayante": True,
        "coutLicenceMensuel": 25000,
        "sitesDisponibles": ["ABJ"],
    },
    {
        "id": "freebsd-14",
        "nom": "FreeBSD",
        "famille": "bsd",
        "version": "14",
        "architecture": "x86_64",
        "tailleGo": 2,
        "sitesDisponibles": ["ABJ"],
    },
]


class ComputeSimule:
    def gabarits(self) -> list[dict[str, Any]]:
        return GABARITS

    def images(self) -> list[dict[str, Any]]:
        return IMAGES

    def creer_serveur(self, **kw: Any) -> dict[str, Any]:
        return {
            "id": f"srv-{nouvel_id()[:8]}",
            "statut": "ACTIVE",
            "ip_privee": f"10.{hash(kw.get('nom', '')) % 250}.0.{hash(kw.get('image_id', '')) % 250 + 2}",
        }

    def action(self, serveur_id: str, action: str) -> None:
        return None

    def supprimer_serveur(self, serveur_id: str) -> None:
        return None

    def redimensionner(self, serveur_id: str, gabarit_id: str) -> None:
        return None

    def instantane(self, serveur_id: str, nom: str) -> str:
        return f"img-{nouvel_id()[:8]}"

    def console(self, serveur_id: str) -> str:
        return f"https://console.synelia.cloud/novnc/{serveur_id}?token={nouvel_id()}"

    def journaux(self, serveur_id: str, lignes: int = 20) -> list[str]:
        return [f"[cloud-init] ligne {i} — démarrage nominal" for i in range(1, lignes + 1)]


class ComputeOpenStack(ComputeSimule):
    def _c(self):  # type: ignore[no-untyped-def]
        from synelia_openstack.fabrique import connexion

        return connexion()

    def gabarits(self) -> list[dict[str, Any]]:
        out = []
        for f in self._c().compute.flavors():
            if not f.is_public:
                # Gabarits privés (ex. l'amphora Octavia) : pas accessibles depuis le
                # projet tenant, Nova rejette la création de serveur avec ce flavor.
                continue
            extra = f.extra_specs or {}
            out.append(
                {
                    "id": f.id,
                    "nom": f.name,
                    "vcpu": f.vcpus,
                    "ramGo": max(1, f.ram // 1024),
                    "diskGo": f.disk,
                    "famille": extra.get("synelia:famille", "generique"),
                    "prixMensuel": int(extra.get("synelia:prix", f.vcpus * 9500)),
                    "sitesDisponibles": ["ABJ"],
                }
            )
        return out

    def images(self) -> list[dict[str, Any]]:
        out = []
        for i in self._c().image.images(visibility="public"):
            out.append(
                {
                    "id": i.id,
                    "nom": i.name,
                    "famille": "windows"
                    if "windows" in (i.os_distro or i.name).lower()
                    else "linux",
                    "version": i.os_version or "",
                    "architecture": i.architecture or "x86_64",
                    "tailleGo": max(1, (i.size or 0) // 2**30),
                    "sitesDisponibles": ["ABJ"],
                }
            )
        return out

    def creer_serveur(self, **kw: Any) -> dict[str, Any]:
        ident = kw.get("identifiants") or {}
        if ident.get("application_credential_id"):
            from synelia_openstack.fabrique import connexion_avec

            c = connexion_avec(ident["application_credential_id"], ident["application_credential_secret"])
        else:
            c = self._c()
        params: dict[str, Any] = {
            "name": kw["nom"],
            "image_id": kw["image_id"],
            "flavor_id": kw["gabarit_id"],
            "networks": [{"uuid": kw["reseau_id"]}] if kw.get("reseau_id") else "auto",
            "metadata": {"synelia_org": str(kw.get("org_id") or ""), "synelia_espace": str(kw.get("espace_id") or "")},
        }
        if kw.get("cle_ssh"):
            params["key_name"] = kw["cle_ssh"]
        if kw.get("cloud_init"):
            # Nova exige que `user_data` soit du Base64 côté client (openstacksdk ne l'encode
            # pas lui-même, contrairement au CLI `openstack server create --user-data`) : sans
            # cet encodage la valeur est silencieusement perdue (aucune erreur, mais l'instance
            # démarre sans cloud-init).
            import base64

            params["user_data"] = base64.b64encode(kw["cloud_init"].encode()).decode()
        s = c.compute.create_server(**params)
        s = c.compute.wait_for_server(s, wait=600)
        ip = next((a["addr"] for nets in (s.addresses or {}).values() for a in nets if a.get("version") == 4), None)
        return {"id": s.id, "statut": s.status, "ip_privee": ip}

    def action(self, serveur_id: str, action: str) -> None:
        from synelia_openstack.erreurs import traduire

        try:
            c = self._c()
            if action == "arret":
                c.compute.stop_server(serveur_id)
                c.compute.wait_for_server(
                    c.compute.get_server(serveur_id), status="SHUTOFF", wait=300
                )
            elif action == "demarrage":
                c.compute.start_server(serveur_id)
                c.compute.wait_for_server(
                    c.compute.get_server(serveur_id), status="ACTIVE", wait=300
                )
            elif action == "redemarrage":
                c.compute.reboot_server(serveur_id, "SOFT")
                c.compute.wait_for_server(
                    c.compute.get_server(serveur_id), status="ACTIVE", wait=300
                )
            else:
                msg = f"Action inconnue : {action}."
                raise ValueError(msg)
        except Exception as exc:
            from synelia_kernel import erreurs as _e

            if isinstance(exc, _e.AppError):
                raise
            raise traduire(exc, "Machine virtuelle") from None

    def supprimer_serveur(self, serveur_id: str) -> None:
        self._c().compute.delete_server(serveur_id, ignore_missing=True)

    def redimensionner(self, serveur_id: str, gabarit_id: str) -> None:
        c = self._c()
        c.compute.resize_server(serveur_id, gabarit_id)
        c.compute.wait_for_server(
            c.compute.get_server(serveur_id), status="VERIFY_RESIZE", wait=600
        )
        c.compute.confirm_server_resize(serveur_id)

    def instantane(self, serveur_id: str, nom: str) -> str:
        return self._c().compute.create_server_image(serveur_id, nom, wait=True).id

    def console(self, serveur_id: str) -> str:
        return self._c().compute.create_console(serveur_id, console_type="novnc")["url"]

    def journaux(self, serveur_id: str, lignes: int = 20) -> list[str]:
        from synelia_openstack.erreurs import traduire

        try:
            sortie = self._c().compute.get_server_console_output(serveur_id, length=lignes)
        except Exception as exc:
            from synelia_kernel import erreurs as _e

            if isinstance(exc, _e.AppError):
                raise
            raise traduire(exc, "Machine virtuelle") from None
        return ((sortie or {}).get("output") or "").splitlines()
