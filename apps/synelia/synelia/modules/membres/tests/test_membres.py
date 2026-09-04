"""Membres & invitations : ajout, retrait (avec confirmation), relance, révocation.

Le client est l'admin plateforme (super_admin) : on crée une organisation puis on y
travaille via `X-Organisation-Id` pour sceller les opérations sur les membres de celle-ci."""

ORG_NOM = "Membre Org"


async def _creer_org(client) -> tuple[str, str]:
    r = await client.post(
        "/v1/organisations",
        json={
            "nom": ORG_NOM,
            "pays": "CI",
            "administrateur": {"nom": "Kouassi Y.", "email": "kouassi@membre.ci"},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], "kouassi@membre.ci"


def _headers(org_id: str) -> dict[str, str]:
    return {"X-Organisation-Id": org_id}


async def test_cycle_membre(client):
    oid, email = await _creer_org(client)

    r = await client.get("/v1/membres", headers=_headers(oid))
    assert r.status_code == 200
    membres = r.json()["donnees"]
    assert any(mm["role"] == "org_admin" for mm in membres)
    mem = membres[0]
    memId = mem["id"]

    r = await client.get(f"/v1/membres/{memId}", headers=_headers(oid))
    assert r.status_code == 200 and r.json()["userId"] == mem["userId"]

    r = await client.patch(
        f"/v1/membres/{memId}", json={"role": "read_only"}, headers=_headers(oid)
    )
    assert r.status_code == 200 and r.json()["role"] == "read_only"

    r = await client.delete(
        f"/v1/membres/{memId}", params={"confirmation": "mauvais"}, headers=_headers(oid)
    )
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "confirmation_invalide"

    r = await client.delete(
        f"/v1/membres/{memId}", params={"confirmation": email}, headers=_headers(oid)
    )
    assert r.status_code == 204


async def test_cycle_invitation(client):
    oid, _ = await _creer_org(client)

    r = await client.post(
        "/v1/invitations",
        json={"email": "nov@invite.ci", "role": "operator", "scopeType": "org"},
        headers=_headers(oid),
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["statut"] == "en_attente" and inv["email"] == "nov@invite.ci"
    iid = inv["id"]

    r = await client.post(
        "/v1/invitations",
        json={"email": "nov@invite.ci", "role": "operator", "scopeType": "org"},
        headers=_headers(oid),
    )
    assert r.status_code == 409 and r.json()["erreur"]["code"] == "invitation_existante"

    r = await client.get("/v1/invitations", headers=_headers(oid))
    assert r.status_code == 200 and any(i["id"] == iid for i in r.json()["donnees"])

    r = await client.post(f"/v1/invitations/{iid}/relance", headers=_headers(oid))
    assert r.status_code == 200 and r.json()["statut"] == "en_attente"

    r = await client.delete(f"/v1/invitations/{iid}", headers=_headers(oid))
    assert r.status_code == 204
