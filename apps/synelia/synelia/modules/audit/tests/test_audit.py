"""Audit : journalisation des événements, filtres, export."""


async def test_lister_audit(client):
    # créer une ressource pour générer des événements
    r = await client.post(
        "/v1/organisations",
        json={"nom": "Audit Org", "pays": "CI"},
    )
    assert r.status_code == 201

    r = await client.get("/v1/audit")
    assert r.status_code == 200
    corps = r.json()
    assert corps["pagination"]["total"] >= 1
    ev = corps["donnees"][0]
    assert ev["actor"]["type"] == "user"
    assert ev["result"] in ("ok", "refuse", "erreur")
    assert ev["scope"]["type"] == "org"

    r = await client.get("/v1/audit", params={"action": "organisation.creation"})
    assert r.status_code == 200
    assert any(e["action"] == "organisation.creation" for e in r.json()["donnees"])


async def test_export_audit(client):
    r = await client.post(
        "/v1/audit/export",
        json={"depuis": "2024-01-01T00:00:00Z", "jusqua": "2026-12-31T23:59:59Z", "format": "csv"},
    )
    assert r.status_code == 202, r.text
    corps = r.json()
    assert corps["travailId"]
    assert corps["urlTelechargement"]
    assert corps["expire"]
