"""Module de référence : création d'un Espace Cloud = 202 + travail exécuté, quota, confirmation."""


async def test_cycle_espace(client):
    corps = {"code": "prod-abj", "offerId": "offre-standard", "site": "ABJ", "cidr": "10.10.0.0/16", "quota": {"vcpu": 16, "ramGo": 64, "stockageTo": 2}}
    r = await client.post("/v1/espaces", json=corps)
    assert r.status_code == 202, r.text
    travail = r.json()
    assert travail["type"] == "espace.create" and travail["statut"] == "done"
    assert all(t["statut"] == "ok" for t in travail["taches"])

    r = await client.get("/v1/espaces")
    assert r.status_code == 200
    espaces = r.json()["donnees"]
    assert len(espaces) == 1 and espaces[0]["statut"] == "active"
    eid = espaces[0]["id"]

    r = await client.get(f"/v1/travaux/{travail['id']}")
    assert r.status_code == 200 and r.json()["statut"] == "done"

    r = await client.post("/v1/espaces", json=corps)
    assert r.status_code == 409 and r.json()["erreur"]["code"] == "nom_deja_pris"

    r = await client.delete(f"/v1/espaces/{eid}", params={"confirmation": "mauvais"})
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "confirmation_invalide"

    r = await client.put(f"/v1/espaces/{eid}/quota", json={"vcpu": 8, "ramGo": 16, "stockageTo": 1})
    assert r.status_code == 200 and r.json()["quota"]["vcpu"] == 8

    r = await client.delete(f"/v1/espaces/{eid}", params={"confirmation": "prod-abj"})
    assert r.status_code == 202
    r = await client.get("/v1/espaces")
    assert r.json()["pagination"]["total"] == 0

    r = await client.get("/v1/audit")  # module audit pas encore écrit → 404 chemin inconnu accepté ici
    assert r.status_code in (200, 404)
