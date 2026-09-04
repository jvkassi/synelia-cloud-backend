"""Module /kubernetes : cycle de vie d'un cluster (création, kubeconfig, mise à jour, pools, modules, versions)."""


async def _espace_demo(client) -> str:
    r = await client.get("/v1/espaces")
    assert r.status_code == 200
    demo = next(e for e in r.json()["donnees"] if e["code"] == "demo-abj")
    return demo["id"]


def _corps_cluster(espace_id: str, nom: str = "k8s-test") -> dict:
    return {
        "espaceId": espace_id,
        "nom": nom,
        "version": "1.32.2",
        "site": "ABJ",
        "controlPlane": {"mode": "single"},
        "pools": [{"nom": "workers", "nodes": 2, "flavor": "m1.medium", "type": "standard"}],
        "modules": ["ingress-nginx", "cert-manager"],
    }


async def _creer_cluster(client, espace_id: str, nom: str = "k8s-test") -> str:
    r = await client.post("/v1/kubernetes", json=_corps_cluster(espace_id, nom))
    assert r.status_code == 202, r.text
    assert r.json()["statut"] == "done"
    r2 = await client.get("/v1/kubernetes")
    clusters = r2.json()["donnees"]
    cluster = next(c for c in clusters if c["nom"] == nom)
    assert cluster["statut"] == "running"
    return cluster["id"]


async def test_versions_et_modules(client):
    r = await client.get("/v1/kubernetes/versions")
    assert r.status_code == 200
    versions = r.json()
    assert ["1.31.4", "1.32.2", "1.33.0"] == [v["version"] for v in versions]
    assert any(v["statut"] == "recommandee" for v in versions)

    r = await client.get("/v1/kubernetes/modules")
    assert r.status_code == 200
    slugs = {item["slug"] for item in r.json()}
    assert {"cni", "ingress-nginx", "monitoring", "cert-manager", "autoscaler"} <= slugs


async def test_cycle_cluster(client):
    espace_id = await _espace_demo(client)
    cid = await _creer_cluster(client, espace_id, "k8s-prod")

    r = await client.get(f"/v1/kubernetes/{cid}")
    assert r.status_code == 200
    cluster = r.json()
    assert cluster["espaceId"] == espace_id
    assert cluster["version"] == "1.32.2"
    assert cluster["controlPlane"]["mode"] == "single"
    assert cluster["pools"][0]["nom"] == "workers"

    r = await client.get(f"/v1/kubernetes/{cid}/kubeconfig")
    assert r.status_code == 200
    kube = r.json()
    assert kube["utilisateur"] == "admin"
    assert f"https://{cid}.k8s.synelia.cloud:6443" in kube["contenu"]

    r = await client.post(f"/v1/kubernetes/{cid}/mise-a-jour", json={"version": "1.33.0"})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/kubernetes/{cid}")
    assert r.json()["version"] == "1.33.0"


async def test_creer_cluster_nom_deja_pris(client):
    espace_id = await _espace_demo(client)
    nom = "k8s-dup"
    await _creer_cluster(client, espace_id, nom)
    r = await client.post("/v1/kubernetes", json=_corps_cluster(espace_id, nom))
    assert r.status_code == 409 and r.json()["erreur"]["code"] == "nom_deja_pris"


async def test_pools_cycle(client):
    espace_id = await _espace_demo(client)
    cid = await _creer_cluster(client, espace_id, "k8s-pools")

    corps = {"nom": "gpu", "nodes": 1, "flavor": "g1.large", "type": "gpu"}
    r = await client.post(f"/v1/kubernetes/{cid}/pools", json=corps)
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/kubernetes/{cid}/pools")
    noms = [p["nom"] for p in r.json()]
    assert "gpu" in noms

    r = await client.patch(f"/v1/kubernetes/{cid}/pools/gpu", json={**corps, "nodes": 3})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/kubernetes/{cid}/pools")
    gpu = next(p for p in r.json() if p["nom"] == "gpu")
    assert gpu["nodes"] == 3

    r = await client.delete(f"/v1/kubernetes/{cid}/pools/gpu", params={"confirmation": "mauvais"})
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "confirmation_invalide"
    r = await client.delete(f"/v1/kubernetes/{cid}/pools/gpu", params={"confirmation": "gpu"})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/kubernetes/{cid}/pools")
    assert all(p["nom"] != "gpu" for p in r.json())


async def test_modules_cluster(client):
    espace_id = await _espace_demo(client)
    cid = await _creer_cluster(client, espace_id, "k8s-modules")
    r = await client.put(
        f"/v1/kubernetes/{cid}/modules", json={"modules": ["monitoring", "autoscaler"]}
    )
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/kubernetes/{cid}")
    assert set(r.json()["modules"]) == {"monitoring", "autoscaler"}


async def test_supprimer_cluster_confirmation(client):
    espace_id = await _espace_demo(client)
    cid = await _creer_cluster(client, espace_id, "k8s-a-supprimer")
    r = await client.delete(f"/v1/kubernetes/{cid}", params={"confirmation": "mauvais"})
    assert r.status_code == 422
    r = await client.delete(f"/v1/kubernetes/{cid}", params={"confirmation": "k8s-a-supprimer"})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get("/v1/kubernetes")
    assert all(c["nom"] != "k8s-a-supprimer" for c in r.json()["donnees"])


async def test_lister_filtres(client):
    espace_id = await _espace_demo(client)
    await _creer_cluster(client, espace_id, "k8s-filtre")
    r = await client.get("/v1/kubernetes", params={"espaceId": espace_id, "statut": "running"})
    assert r.status_code == 200
    assert any(c["nom"] == "k8s-filtre" for c in r.json()["donnees"])
