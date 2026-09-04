"""Sécurité & accès : clés d'API, politiques, sessions actives, SSO."""


async def test_cycle_cle_api(client):
    r = await client.post(
        "/v1/securite/cles-api", json={"nom": "ci-cd", "portee": ["vm.create_delete", "vm.power"]}
    )
    assert r.status_code == 201, r.text
    secret = r.json()["secret"]
    assert secret.startswith(r.json()["cle"]["prefixe"])
    cle = r.json()["cle"]
    assert cle["portee"] == ["vm.create_delete", "vm.power"]
    cid = cle["id"]

    r = await client.get("/v1/securite/cles-api")
    assert r.status_code == 200 and any(c["id"] == cid for c in r.json()["donnees"])

    r = await client.get(f"/v1/securite/cles-api/{cid}")
    assert r.status_code == 200 and r.json()["statut"] == "active"

    r = await client.patch(
        f"/v1/securite/cles-api/{cid}", json={"nom": "ci-cd-v2", "portee": ["vm.create_delete"]}
    )
    assert r.status_code == 200 and r.json()["nom"] == "ci-cd-v2"

    r = await client.post(f"/v1/securite/cles-api/{cid}/rotation", json={})
    assert r.status_code == 200
    assert r.json()["secret"] != secret and r.json()["secret"].startswith(
        r.json()["cle"]["prefixe"]
    )

    r = await client.delete(f"/v1/securite/cles-api/{cid}", params={"confirmation": "mauvais"})
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "confirmation_invalide"

    r = await client.delete(f"/v1/securite/cles-api/{cid}", params={"confirmation": "ci-cd-v2"})
    assert r.status_code == 204

    r = await client.get(f"/v1/securite/cles-api/{cid}")
    assert r.status_code == 200 and r.json()["statut"] == "revoquee"


async def test_cle_api_portee_invalide(client):
    r = await client.post(
        "/v1/securite/cles-api", json={"nom": "bad", "portee": ["audit.nonexistant"]}
    )
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "validation"


async def test_politiques(client):
    r = await client.get("/v1/securite/politiques")
    assert r.status_code == 200
    pol = r.json()
    assert pol["mfa"]["obligatoire"] is False
    assert pol["session"]["dureeMaxMin"] == 720

    r = await client.put(
        "/v1/securite/politiques",
        json={
            "mfa": {"obligatoire": True, "methodes": ["totp"]},
            "session": {"dureeMaxMin": 60, "inactiviteMin": 30},
            "restrictionIp": {"actif": False, "plages": []},
        },
    )
    assert r.status_code == 200
    assert r.json()["politiques"]["mfa"]["obligatoire"] is True
    assert r.json()["sessionsInvalidees"] == 1


async def test_sessions(client):
    r = await client.get("/v1/securite/sessions")
    assert r.status_code == 200
    donnees = r.json()["donnees"]
    assert len(donnees) >= 1
    assert any(s["courante"] for s in donnees)
    sid = donnees[0]["id"]

    r = await client.delete(f"/v1/securite/sessions/{sid}")
    assert r.status_code in (204, 409)

    r = await client.delete("/v1/securite/sessions", params={"confirmation": "mauvais"})
    assert r.status_code == 422


async def test_sso(client):
    r = await client.get("/v1/securite/sso")
    assert r.status_code == 200
    assert r.json()["actif"] is False

    r = await client.post("/v1/securite/sso/test")
    assert r.status_code == 200
    assert r.json()["succes"] is False
    assert r.json()["etapes"]

    r = await client.put(
        "/v1/securite/sso",
        json={
            "actif": True,
            "protocole": "oidc",
            "emetteur": "https://idp.example.com",
            "clientId": "syn-app",
        },
    )
    assert r.status_code == 200
    assert r.json()["actif"] is True
    assert r.json()["secretDefini"] is False

    r = await client.post("/v1/securite/sso/test")
    assert r.status_code == 200 and r.json()["succes"] is True
