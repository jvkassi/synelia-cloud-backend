"""Facturation : estimation, consommation, factures, paiement, prépayé, SLA, souscriptions, devis."""


async def test_estimation(client):
    r = await client.post(
        "/v1/facturation/estimation",
        json={"type": "vm", "quantite": 1, "specification": {"vcpu": 2, "ramGo": 4, "diskGo": 40}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["devise"] == "XOF" and body["totalMensuel"] > 0


async def test_consommation(client):
    r = await client.get("/v1/facturation/consommation?periode=2026-08")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "periode" in body and "jours" in body


async def test_consommation_export(client):
    r = await client.post(
        "/v1/facturation/consommation/export", json={"periode": "2026-08", "format": "csv"}
    )
    assert r.status_code == 202, r.text
    assert "url" in r.json()


async def test_factures(client):
    r = await client.get("/v1/facturation/factures")
    assert r.status_code == 200, r.text
    factures = r.json()["donnees"]
    assert len(factures) == 1 and factures[0]["statut"] == "emise"
    fid = factures[0]["id"]

    r = await client.get(f"/v1/facturation/factures/{fid}")
    assert r.status_code == 200 and r.json()["numero"] == "SYN-2026-000001"

    r = await client.get(f"/v1/facturation/factures/{fid}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")

    r = await client.post(f"/v1/facturation/factures/{fid}/paiement", json={"moyenId": "moyen-x"})
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "payee"

    r = await client.post(f"/v1/facturation/factures/{fid}/paiement", json={"moyenId": "moyen-x"})
    assert r.status_code == 409 and r.json()["erreur"]["code"] == "facture_deja_payee"


async def test_moyens_paiement(client):
    r = await client.post(
        "/v1/facturation/moyens-paiement",
        json={"type": "carte", "numero": "4242424242424242", "defaut": True},
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r = await client.get("/v1/facturation/moyens-paiement")
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.patch(f"/v1/facturation/moyens-paiement/{mid}", json={"libelle": "Visa Pro"})
    assert r.status_code == 200 and r.json()["libelle"] == "Visa Pro"
    r = await client.delete(f"/v1/facturation/moyens-paiement/{mid}")
    assert r.status_code == 204


async def test_prepaye_rechargement(client):
    r = await client.post(
        "/v1/facturation/prepaye/rechargement", json={"montant": 25000, "moyenId": "moyen-x"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "credite" and r.json()["solde"] == 25000


async def test_sla(client):
    r = await client.get("/v1/facturation/sla")
    assert r.status_code == 200 and len(r.json()["engagements"]) == 3
    r = await client.post(
        "/v1/facturation/sla/reclamations",
        json={"periode": "2026-08", "composant": "compute", "motif": "Coupure 2h"},
    )
    assert r.status_code == 201 and "reference" in r.json()


async def test_souscriptions(client):
    r = await client.get("/v1/facturation/souscriptions")
    assert r.status_code == 200


async def test_devis_acceptation(client):
    # créer un devis via le dépôt n'est pas exposé ; on teste la route lister
    r = await client.get("/v1/facturation/devis")
    assert r.status_code == 200


async def test_ventilation(client):
    r = await client.get("/v1/facturation/ventilation?axe=espace")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "lignes" in body and body["total"] >= 0
