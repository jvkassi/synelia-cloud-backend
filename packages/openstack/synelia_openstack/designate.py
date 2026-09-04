"""Designate : zones DNS et enregistrements."""

from __future__ import annotations

from typing import Any

from synelia_kernel.ids import nouvel_id

NS_DEFAUTS = ["ns1.synelia.cloud", "ns2.synelia.cloud"]


class DesignateSimule:
    def creer_zone(self, nom: str) -> dict[str, Any]:
        return {"id": f"zone-{nouvel_id()[:8]}", "ns": list(NS_DEFAUTS), "email": f"admin.{nom}"}

    def supprimer_zone(self, zone_id: str) -> None:
        return None

    def activer_dnssec(self, zone_id: str, actif: bool) -> None:
        return None


class DesignateOpenStack(DesignateSimule):
    def _c(self):  # type: ignore[no-untyped-def]
        from synelia_openstack.fabrique import connexion

        return connexion()

    def creer_zone(self, nom: str) -> dict[str, Any]:
        z = self._c().dns.create_zone(name=nom, email=f"admin.{nom}")
        z = self._c().dns.wait_for_zone(z)
        return {"id": z.id, "ns": list(z.nameservers or NS_DEFAUTS), "email": z.email}

    def supprimer_zone(self, zone_id: str) -> None:
        self._c().dns.delete_zone(zone_id, ignore_missing=True)

    def activer_dnssec(self, zone_id: str, actif: bool) -> None:
        self._c().dns.update_zone(zone_id, attributes={"dnssec": actif})
