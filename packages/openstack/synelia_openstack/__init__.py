"""Amont infrastructure : connexion openstacksdk (réel) ou simulation locale.

Ce paquet ne connaît ni la base ni le contrat : il parle l'amont, les `mappers.py`
des modules traduisent. Chaque domaine expose une paire `XxxSimule` / `XxxOpenStack`
et le module obtient l'implémentation par `fournisseur(XxxSimule, XxxOpenStack)`."""

from synelia_openstack.fabrique import connexion, fournisseur

__all__ = ["connexion", "fournisseur"]
