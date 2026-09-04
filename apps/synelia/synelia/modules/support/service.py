"""Base de connaissances et ticket support : dépôts et règles."""

from __future__ import annotations

from typing import Any

from synelia_contract import modeles as m

from synelia.depot import Depot

detenteur_tickets = Depot("ticket", m.Ticket, libelle="Ticket", champ_nom="sujet")
detenteur_pieces = Depot("ticket_piece", m.SupportPiecesPostResponse, libelle="Pièce jointe")

ARTICLES_KB: list[dict[str, Any]] = [
    {
        "id": "kb-01",
        "titre": "Créer son premier Espace Cloud",
        "categorie": "prise-en-main",
        "resume": "Les étapes pour provisionner votre premier Espace Cloud.",
        "contenuMarkdown": "# Créer un Espace Cloud\n\n1. Renseignez l'offre et le site.\n2. Choisissez le CIDR du réseau privé.\n3. Validez. Le provisioning prend quelques minutes.",
        "minutes": 5,
        "maj": "2026-01-15",
        "motsCles": ["espace", "provisioning", "creation"],
    },
    {
        "id": "kb-02",
        "titre": "Lancer une machine virtuelle",
        "categorie": "compute",
        "resume": "Choisir un gabarit, une image et démarrer une VM.",
        "contenuMarkdown": "# Lancer une VM\n\nSélectionnez un gabarit, une image, puis une clé SSH.",
        "minutes": 6,
        "maj": "2026-02-01",
        "motsCles": ["vm", "gabarit", "image"],
    },
    {
        "id": "kb-03",
        "titre": "Comprendre la facturation FCFA",
        "categorie": "facturation",
        "resume": "Comment sont calculés les coûts et la TVA.",
        "contenuMarkdown": "# Facturation\n\nLes montants sont en FCFA HT, la TVA ivoirienne (18 %) est ajoutée.",
        "minutes": 4,
        "maj": "2026-02-10",
        "motsCles": ["facturation", "tva", "prix"],
    },
    {
        "id": "kb-04",
        "titre": "Configurer le second facteur (MFA)",
        "categorie": "securite",
        "resume": "Activer l'authentification à deux facteurs sur votre compte.",
        "contenuMarkdown": "# MFA\n\nActivez le second facteur dans l'onglet Compte.",
        "minutes": 3,
        "maj": "2026-03-05",
        "motsCles": ["mfa", "securite", "2fa"],
    },
    {
        "id": "kb-05",
        "titre": "Téléverser une pièce jointe",
        "categorie": "support",
        "resume": "Ajouter un fichier (≤ 10 Mo) à un ticket.",
        "contenuMarkdown": "# Pièces jointes\n\nLes fichiers doivent être encodés en base64 et ne pas dépasser 10 Mo.",
        "minutes": 2,
        "maj": "2026-03-12",
        "motsCles": ["piece", "fichier", "ticket"],
    },
    {
        "id": "kb-06",
        "titre": "Demander une escalade",
        "categorie": "support",
        "resume": "Faire monter un ticket vers une équipe senior.",
        "contenuMarkdown": "# Escalade\n\nUtilisez l'action escalade avec un motif. L'escalade n'est possible qu'une fois.",
        "minutes": 2,
        "maj": "2026-04-01",
        "motsCles": ["escalade", "support"],
    },
]
