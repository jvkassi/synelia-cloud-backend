"""Web Cloud — DNS : zones, enregistrements, DNSSEC, modèles."""


async def test_modeles(client):
    r = await client.get("/v1/web/dns/modeles")
    assert r.status_code == 200
    modeles = r.json()
    assert len(modeles) >= 3 and any(m["id"] == "courrier" for m in modeles)


async def test_cycle_zone_dns(client):
    r = await client.post("/v1/web/dns", json={"domaine": "demo-dns.com"})
    assert r.status_code == 201, r.text
    zone = r.json()
    assert zone["domaine"] == "demo-dns.com" and zone["dnssec"] is False
    zid = zone["id"]

    r = await client.post("/v1/web/dns", json={"domaine": "demo-dns.com"})
    assert r.status_code == 409

    r = await client.get("/v1/web/dns")
    assert r.status_code == 200 and any(z["domaine"] == "demo-dns.com" for z in r.json()["donnees"])

    r = await client.get(f"/v1/web/dns/{zid}")
    assert r.status_code == 200

    r = await client.post(
        f"/v1/web/dns/{zid}/enregistrements",
        json={"type": "A", "nom": "@", "valeur": "192.168.0.10", "ttl": 3600},
    )
    assert r.status_code == 201, r.text
    assert any(e["type"] == "A" for e in r.json()["enregistrements"])

    r = await client.post(
        f"/v1/web/dns/{zid}/enregistrements",
        json={"type": "A", "nom": "@", "valeur": "192.168.0.11", "ttl": 3600},
    )
    assert r.status_code == 409

    r = await client.put(
        f"/v1/web/dns/{zid}/enregistrements",
        json={"enregistrements": [{"type": "TXT", "nom": "@", "valeur": "v=spf1 -all"}]},
    )
    assert r.status_code == 200
    enregs = r.json()["enregistrements"]
    assert len(enregs) == 1 and enregs[0]["type"] == "TXT"
    eid = enregs[0]["id"]

    r = await client.patch(
        f"/v1/web/dns/{zid}/enregistrements/{eid}",
        json={"type": "TXT", "nom": "@", "valeur": "v=spf1 ~all", "ttl": 1800},
    )
    assert r.status_code == 200 and r.json()["enregistrements"][0]["valeur"] == "v=spf1 ~all"

    r = await client.delete(f"/v1/web/dns/{zid}/enregistrements/{eid}")
    assert r.status_code == 204
    r = await client.get(f"/v1/web/dns/{zid}")
    assert r.json()["enregistrements"] == []

    r = await client.put(f"/v1/web/dns/{zid}/dnssec", json={"actif": True})
    assert r.status_code == 200 and r.json()["dnssec"] is True

    r = await client.put(f"/v1/web/dns/{zid}/dnssec", json={"actif": True})
    assert r.status_code == 409

    r = await client.post(f"/v1/web/dns/{zid}/modeles/courrier", json={"remplacerExistants": False})
    assert r.status_code == 200
    assert any(e["type"] == "MX" for e in r.json()["enregistrements"])

    r = await client.delete(f"/v1/web/dns/{zid}", params={"confirmation": "mauvais"})
    assert r.status_code == 422

    r = await client.delete(f"/v1/web/dns/{zid}", params={"confirmation": "demo-dns.com"})
    assert r.status_code == 204

    r = await client.get("/v1/web/dns")
    assert r.status_code == 200 and all(z["id"] != zid for z in r.json()["donnees"])
