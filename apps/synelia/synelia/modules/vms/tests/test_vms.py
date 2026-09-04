"""Modules /vms : cycle de vie d'une machine virtuelle, services amont, instantanés, lot."""


async def _espace_demo(client) -> str:
    r = await client.get("/v1/espaces")
    assert r.status_code == 200
    espaces = r.json()["donnees"]
    demo = next(e for e in espaces if e["code"] == "demo-abj")
    return demo["id"]


async def _creer_vm(client, espace_id: str, nom: str = "vm-test") -> str:
    corps = {"espaceId": espace_id, "nom": nom, "imageId": "ubuntu-24.04", "gabarit": "g1.medium"}
    r = await client.post("/v1/vms", json=corps)
    assert r.status_code == 202, r.text
    assert r.json()["statut"] == "done"
    r2 = await client.get("/v1/vms")
    vms = r2.json()["donnees"]
    vm = next(v for v in vms if v["nom"] == nom)
    assert vm["statut"] == "running"
    return vm["id"]


async def test_creer_et_lister_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "web-nouveau")
    r = await client.get(f"/v1/vms/{vid}")
    assert r.status_code == 200
    vm = r.json()
    assert vm["statut"] == "running"
    assert vm["espaceId"] == espace_id
    assert vm["vcpu"] == 2 and vm["ramGo"] == 4
    assert any(i["type"] == "privee" for i in vm["ips"])


async def test_creer_vm_explicite_et_image_inconnue(client):
    espace_id = await _espace_demo(client)
    r = await client.post(
        "/v1/vms",
        json={
            "espaceId": espace_id,
            "nom": "vm-specs",
            "imageId": "debian-12",
            "vcpu": 1,
            "ramGo": 2,
            "diskGo": 20,
        },
    )
    assert r.status_code == 202, r.text
    r = await client.post(
        "/v1/vms",
        json={
            "espaceId": espace_id,
            "nom": "vm-bad-img",
            "imageId": "inexistante",
            "vcpu": 1,
            "ramGo": 2,
            "diskGo": 20,
        },
    )
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "validation"
    r = await client.post(
        "/v1/vms", json={"espaceId": espace_id, "nom": "vm-rien", "imageId": "debian-12"}
    )
    assert r.status_code == 422


async def test_creer_vm_nom_deja_pris(client):
    espace_id = await _espace_demo(client)
    await _creer_vm(client, espace_id, "dup")
    r = await client.post(
        "/v1/vms",
        json={
            "espaceId": espace_id,
            "nom": "dup",
            "imageId": "ubuntu-24.04",
            "gabarit": "g1.medium",
        },
    )
    assert r.status_code == 409 and r.json()["erreur"]["code"] == "nom_deja_pris"


async def test_modifier_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "patch-me")
    r = await client.patch(f"/v1/vms/{vid}", json={"nom": "patch-me", "tags": ["web", "prod"]})
    assert r.status_code == 200
    assert set(r.json()["tags"]) == {"web", "prod"}
    await _creer_vm(client, espace_id, "autre")
    r = await client.patch(f"/v1/vms/{vid}", json={"nom": "autre"})
    assert r.status_code == 409 and r.json()["erreur"]["code"] == "nom_deja_pris"


async def test_supprimer_vm_confirmation(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "a-supprimer")
    r = await client.delete(f"/v1/vms/{vid}", params={"confirmation": "mauvais"})
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "confirmation_invalide"
    r = await client.delete(f"/v1/vms/{vid}", params={"confirmation": "a-supprimer"})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get("/v1/vms")
    assert all(v["nom"] != "a-supprimer" for v in r.json()["donnees"])


async def test_arret_demarrage_redemarrage(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "power")
    r = await client.post(f"/v1/vms/{vid}/arret", json={})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/vms/{vid}")
    assert r.json()["statut"] == "stopped"
    r = await client.post(f"/v1/vms/{vid}/arret", json={})
    assert r.status_code == 409 and r.json()["erreur"]["code"] == "etat_deja_atteint"
    r = await client.post(f"/v1/vms/{vid}/demarrage", json={})
    assert r.status_code == 202
    r = await client.get(f"/v1/vms/{vid}")
    assert r.json()["statut"] == "running"
    r = await client.post(f"/v1/vms/{vid}/demarrage", json={})
    assert r.status_code == 409
    r = await client.post(f"/v1/vms/{vid}/redemarrage", json={})
    assert r.status_code == 202 and r.json()["statut"] == "done"


async def test_console_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "console")
    r = await client.post(f"/v1/vms/{vid}/console")
    assert r.status_code == 201
    corps = r.json()
    assert corps["protocole"] == "vnc" and corps["url"]


async def test_journaux_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "journaux")
    r = await client.get(f"/v1/vms/{vid}/journaux")
    assert r.status_code == 200
    corps = r.json()
    assert corps["lignes"] and all(
        x["niveau"] in ("INFO", "WARN", "ERROR", "DEBUG") for x in corps["lignes"]
    )


async def test_materiel_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "materiel")
    corps = {"scsiControllers": 1, "nics": 2, "usb": True, "secureBoot": True}
    r = await client.put(f"/v1/vms/{vid}/materiel", json=corps)
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/vms/{vid}")
    assert r.json()["hardware"]["nics"] == 2 and r.json()["hardware"]["usb"] is True
    corps2 = {"scsiControllers": 2, "nics": 2, "usb": True, "secureBoot": True}
    r = await client.put(f"/v1/vms/{vid}/materiel", json=corps2)
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "non_porte"


async def test_metriques_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "metriques")
    r = await client.get(f"/v1/vms/{vid}/metriques", params={"fenetre": "7j"})
    assert r.status_code == 200
    corps = r.json()
    assert all(s["fenetre"] == "7j" for s in corps["series"])
    assert any(s["metrique"] == "cpu" for s in corps["series"])


async def test_migration_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "migrate")
    r = await client.post(f"/v1/vms/{vid}/migration", json={"site": "ABJ"})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.post(f"/v1/vms/{vid}/migration", json={"site": "GBM"})
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "non_porte"


async def test_redimensionner_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "resize")
    r = await client.post(
        f"/v1/vms/{vid}/redimensionnement", json={"vcpu": 4, "ramGo": 8, "diskGo": 80}
    )
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/vms/{vid}")
    assert r.json()["vcpu"] == 4 and r.json()["ramGo"] == 8 and r.json()["diskGo"] == 80
    r = await client.post(f"/v1/vms/{vid}/redimensionnement", json={"diskGo": 40})
    assert r.status_code == 422


async def test_lot_vms(client):
    espace_id = await _espace_demo(client)
    machines = [
        {
            "nom": "compose-web",
            "quantite": 2,
            "imageId": "ubuntu-24.04",
            "vcpu": 1,
            "ramGo": 2,
            "diskGo": 20,
        }
    ]
    r = await client.post("/v1/vms/lot", json={"espaceId": espace_id, "machines": machines})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get("/v1/vms", params={"espaceId": espace_id, "q": "compose-web"})
    noms = [v["nom"] for v in r.json()["donnees"]]
    assert "compose-web1" in noms and "compose-web2" in noms


async def test_instantanes_vm(client):
    espace_id = await _espace_demo(client)
    vid = await _creer_vm(client, espace_id, "instantane")
    r = await client.post(f"/v1/vms/{vid}/instantanes", json={"nom": "snap-1", "avecMemoire": True})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.get(f"/v1/vms/{vid}/instantanes")
    assert r.status_code == 200
    snap = r.json()[0]
    assert snap["nom"] == "snap-1"
    snap_id = snap["id"]
    r = await client.post(
        f"/v1/vms/{vid}/instantanes/{snap_id}", params={"confirmation": "mauvais"}
    )
    assert r.status_code == 422
    r = await client.post(f"/v1/vms/{vid}/instantanes/{snap_id}", params={"confirmation": "snap-1"})
    assert r.status_code == 202 and r.json()["statut"] == "done"
    r = await client.delete(f"/v1/vms/{vid}/instantanes/{snap_id}")
    assert r.status_code == 204
    r = await client.get(f"/v1/vms/{vid}/instantanes")
    assert r.json() == []
