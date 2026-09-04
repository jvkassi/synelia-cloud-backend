"""Le socle : santé, erreurs au format du contrat, connexion, RBAC, travaux."""


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json()["statut"] == "ok"


async def test_erreur_404_au_format_contrat(client):
    r = await client.get("/v1/chemin-inconnu")
    assert r.status_code == 404
    corps = r.json()
    assert corps["erreur"]["code"] == "introuvable" and corps["erreur"]["correlationId"]


async def test_non_authentifie(client):
    r = await client.get("/v1/moi", headers={"Authorization": ""})
    assert r.status_code == 401 and r.json()["erreur"]["code"] == "non_authentifie"


async def test_connexion_et_moi(client):
    assert client.jeton
    r = await client.get("/v1/moi")
    assert r.status_code == 200
    assert r.json()["utilisateur"]["email"] == "admin@synelia.cloud"


async def test_rafraichissement_rotatif(client):
    r = await client.post(
        "/v1/auth/connexion", json={"email": "admin@synelia.cloud", "motDePasse": "Synelia!2026"}
    )
    refresh = r.json()["refreshToken"]
    r2 = await client.post("/v1/auth/rafraichir", json={"refreshToken": refresh})
    assert r2.status_code == 200 and r2.json()["accessToken"]
    r3 = await client.post("/v1/auth/rafraichir", json={"refreshToken": refresh})
    assert r3.status_code == 401  # réutilisation détectée


async def test_validation_422_avec_champs(client):
    r = await client.post("/v1/auth/connexion", json={"email": "pas-un-email"})
    assert r.status_code == 422
    assert "champs" in r.json()


async def test_matrice_rbac(client):
    r = await client.get("/v1/rbac/matrice")
    assert r.status_code == 200 and len(r.json()) == 38
