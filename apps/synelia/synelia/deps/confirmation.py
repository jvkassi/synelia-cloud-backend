from __future__ import annotations

from synelia_kernel import erreurs


def exiger_confirmation(attendu: str, confirmation: str | None) -> None:
    """Destructif = `confirmation` = nom exact, sinon `422` **avant** toute lecture amont."""
    if confirmation is None or confirmation.strip() != attendu:
        raise erreurs.confirmation_invalide(attendu)
