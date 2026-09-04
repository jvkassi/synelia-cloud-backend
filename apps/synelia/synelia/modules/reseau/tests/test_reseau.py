"""Couverture du module Réseau : reseaux, IP, groupes de sécurité, load balancers, VPN."""

ESPACE = "espace-demo-abj"
VM = "vm-demo-web"


async def _creer_reseau(client, nom="net-prod", cidr="10.50.0.0/16"):
    return await client.post(
        "/v1/reseaux", json={"nom": nom, "cidr": cidr, "espaceId": ESPACE, "dnsInterne": True}
    )


async def _creer_ip(client):
    return await client.post("/v1/ips", json={"espaceId": ESPACE, "site": "ABJ"})


async def _creer_groupe(client, nom="sg-web"):
    return await client.post(
        "/v1/groupes-securite",
        json={
            "espaceId": ESPACE,
            "nom": nom,
            "description": "Web",
            "defaultPolicy": {"ingress": "deny", "egress": "allow"},
        },
    )


async def _creer_lb(client, nom="lb-api"):
    return await client.post(
        "/v1/load-balancers",
        json={
            "espaceId": ESPACE,
            "nom": nom,
            "layer": "l7",
            "exposure": "public",
            "algo": "round_robin",
            "listeners": [{"protocole": "http", "port": 80}],
        },
    )


async def _creer_tunnel(client, nom="vpn-site"):
    return await client.post(
        "/v1/vpn",
        json={
            "espaceId": ESPACE,
            "nom": nom,
            "type": "ipsec",
            "passerelleDistante": "203.0.113.10",
            "reseauxAnnonces": ["10.50.0.0/16"],
        },
    )


# ── Réseaux ────────────────────────────────────────────────────────────────
async def test_cycle_reseau(client):
    r = await _creer_reseau(client)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["cidr"] == "10.50.0.0/16"

    r = await client.get("/v1/reseaux")
    assert r.status_code == 200 and any(x["id"] == rid for x in r.json()["donnees"])

    r = await client.get(f"/v1/reseaux/{rid}")
    assert r.status_code == 200 and r.json()["nom"] == "net-prod"

    r = await client.patch(
        f"/v1/reseaux/{rid}", json={"nom": "net-prod-2", "cidr": "10.50.0.0/16", "espaceId": ESPACE}
    )
    assert r.status_code == 200 and r.json()["nom"] == "net-prod-2"

    r = await client.delete(f"/v1/reseaux/{rid}", params={"confirmation": "net-prod-2"})
    assert r.status_code == 204


async def test_reseau_cidr_invalide(client):
    r = await _creer_reseau(client, cidr="pas-un-cidr")
    assert r.status_code == 422


async def test_reseau_nom_deja_pris(client):
    await _creer_reseau(client)
    r = await _creer_reseau(client, nom="net-prod")
    assert r.status_code == 409


# ── IP publiques ───────────────────────────────────────────────────────────
async def test_cycle_ip(client):
    r = await _creer_ip(client)
    assert r.status_code == 201, r.text
    ip = r.json()
    ipid = ip["id"]
    assert ip["adresse"].startswith("196.201.")

    r = await client.get("/v1/ips")
    assert r.status_code == 200 and any(x["id"] == ipid for x in r.json()["donnees"])

    r = await client.patch(
        f"/v1/ips/{ipid}", json={"espaceId": ESPACE, "site": "ABJ", "ptr": "www.example.com"}
    )
    assert r.status_code == 200 and r.json()["ptr"] == "www.example.com"

    r = await client.delete(f"/v1/ips/{ipid}", params={"confirmation": ip["adresse"]})
    assert r.status_code == 204


async def test_ip_allocation_incrementale(client):
    r1 = await _creer_ip(client)
    assert r1.status_code == 201
    a1 = r1.json()["adresse"]
    r2 = await _creer_ip(client)
    assert r2.status_code == 201
    a2 = r2.json()["adresse"]
    assert a1 != a2


async def test_attacher_detacher_ip(client):
    r = await _creer_ip(client)
    ipid = r.json()["id"]

    r = await client.put(f"/v1/ips/{ipid}/attachement", json={"cibleId": VM})
    assert r.status_code == 200, r.text
    assert r.json()["attachedTo"] == VM and r.json()["attachedLabel"] == "web-01"

    r = await client.put(f"/v1/ips/{ipid}/attachement", json={"cibleId": VM})
    assert r.status_code == 409

    r = await client.delete(f"/v1/ips/{ipid}/attachement")
    assert r.status_code == 200 and r.json().get("attachedTo") is None


async def test_attacher_ip_vm_introuvable(client):
    r = await _creer_ip(client)
    ipid = r.json()["id"]
    r = await client.put(f"/v1/ips/{ipid}/attachement", json={"cibleId": "vm-inconnu"})
    assert r.status_code == 404


# ── Groupes de sécurité ────────────────────────────────────────────────────
async def test_cycle_groupe_securite(client):
    r = await _creer_groupe(client)
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert r.json()["defaultPolicy"]["ingress"] == "deny"

    r = await client.get("/v1/groupes-securite")
    assert r.status_code == 200 and r.json()["pagination"]["total"] == 1

    regle_id = "rg-1001"
    r = await client.post(
        f"/v1/groupes-securite/{gid}/regles",
        json={
            "id": regle_id,
            "direction": "in",
            "protocole": "tcp",
            "ports": "443",
            "cible": "0.0.0.0/0",
            "description": "https",
        },
    )
    assert r.status_code == 201 and len(r.json()["rules"]) == 1

    r = await client.put(
        f"/v1/groupes-securite/{gid}/regles/{regle_id}",
        json={
            "id": regle_id,
            "direction": "in",
            "protocole": "tcp",
            "ports": "8443",
            "cible": "0.0.0.0/0",
        },
    )
    assert r.status_code == 200 and r.json()["rules"][0]["ports"] == "8443"

    r = await client.put(f"/v1/groupes-securite/{gid}/attachements", json={"cibles": [VM]})
    assert r.status_code == 200 and r.json()["attaches"] == 1

    r = await client.delete(f"/v1/groupes-securite/{gid}/regles/{regle_id}")
    assert r.status_code == 204
    r = await client.get(f"/v1/groupes-securite/{gid}")
    assert r.json()["rules"] == []

    r = await client.delete(f"/v1/groupes-securite/{gid}", params={"confirmation": "sg-web"})
    assert r.status_code == 204


# ── Load balancers ─────────────────────────────────────────────────────────
async def test_cycle_load_balancer(client):
    r = await _creer_lb(client)
    assert r.status_code == 202, r.text
    travail = r.json()
    assert travail["type"] == "lb.create" and travail["statut"] == "done"
    assert all(t["statut"] == "ok" for t in travail["taches"])

    lb = next(
        x
        for x in (await client.get("/v1/load-balancers")).json()["donnees"]
        if x["nom"] == "lb-api"
    )
    assert lb["vip"].startswith("196.201.")

    r = await client.get("/v1/load-balancers")
    lbid = next(x["id"] for x in r.json()["donnees"] if x["nom"] == "lb-api")

    r = await client.get(f"/v1/load-balancers/{lbid}")
    assert r.status_code == 200 and r.json()["exposure"] == "public"

    r = await client.patch(
        f"/v1/load-balancers/{lbid}",
        json={
            "espaceId": ESPACE,
            "nom": "lb-api-2",
            "layer": "l7",
            "exposure": "interne",
            "algo": "least_conn",
        },
    )
    assert r.status_code == 200 and r.json()["exposure"] == "interne"

    r = await client.put(
        f"/v1/load-balancers/{lbid}/pool",
        json={"cibles": [{"targetId": VM, "poids": 1}]},
    )
    assert r.status_code == 200 and r.json()["pool"][0]["targetId"] == VM

    r = await client.put(
        f"/v1/load-balancers/{lbid}/regles-l7",
        json={"regles": [{"hote": "api.example.com", "chemin": "/v1", "cible": "vm-demo-web"}]},
    )
    assert r.status_code == 200 and len(r.json()["reglesL7"]) == 1

    r = await client.get(f"/v1/load-balancers/{lbid}/metriques")
    assert r.status_code == 200 and r.json()["series"] == []

    r = await client.delete(f"/v1/load-balancers/{lbid}", params={"confirmation": "lb-api-2"})
    assert r.status_code == 204


async def test_load_balancer_waf_non_porte(client):
    r = await client.post(
        "/v1/load-balancers",
        json={
            "espaceId": ESPACE,
            "nom": "lb-waf",
            "layer": "l7",
            "exposure": "public",
            "waf": {"actif": True, "ruleset": "owasp"},
        },
    )
    assert r.status_code == 422 and r.json()["erreur"]["code"] == "non_porte"


# ── VPN ────────────────────────────────────────────────────────────────────
async def test_cycle_vpn(client):
    r = await _creer_tunnel(client)
    assert r.status_code == 201, r.text
    tunnel = r.json()
    tid = tunnel["id"]
    assert tunnel["type"] == "ipsec" and tunnel["statut"] == "up"

    r = await client.get("/v1/vpn")
    assert r.status_code == 200 and r.json()["pagination"]["total"] == 1

    r = await client.get(f"/v1/vpn/{tid}")
    assert r.status_code == 200

    r = await client.patch(
        f"/v1/vpn/{tid}", json={"espaceId": ESPACE, "nom": "vpn-site-2", "type": "ipsec"}
    )
    assert r.status_code == 200 and r.json()["nom"] == "vpn-site-2"

    r = await client.post(
        f"/v1/vpn/{tid}/profils", json={"nom": "alice", "utilisateur": "alice@corp"}
    )
    assert r.status_code == 201 and r.json()["configuration"]

    r = await client.delete(f"/v1/vpn/{tid}/profils/alice")
    assert r.status_code == 204

    r = await client.post(f"/v1/vpn/{tid}/renegociation")
    assert r.status_code == 200 and r.json()["derniereNegociation"]

    r = await client.delete(f"/v1/vpn/{tid}", params={"confirmation": "vpn-site-2"})
    assert r.status_code == 204
