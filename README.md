# synelia-cloud-backend

Backend de [synelia-cloud](https://github.com/jvkassi/synelia-cloud), le portail
Next.js de Synelia Cloud (vitrine, espace client, espace super admin), aujourd'hui
servi par des données fictives.

Ce dépôt construit **tout ce que le portail attend** : les 514 opérations de son
contrat `docs/api/openapi.json`, branchées sur l'OpenStack de Synelia et sur les
solutions libres du catalogue. Sans Blesta : clients, souscriptions, facturation et
paiements sont un domaine natif du backend.

**Commencer par [`docs/PLAN-DIRECTEUR.md`](docs/PLAN-DIRECTEUR.md)** : cadre
technique (Node 24, Fastify 5, Zod 4, PostgreSQL 18 + Drizzle, Temporal, Valkey),
structure du monorepo, tenancy organisation ↔ Keystone, correspondance contrat ↔
OpenStack, modèle de données, facturation, feuille de route en onze phases et
décisions restant à prendre.

```
synelia-cloud (frontend) ──► apps/api · apps/worker · apps/scheduler (ce dépôt)
                                   │
        PostgreSQL · Valkey · Temporal · OpenStack Gazpacho · Kubernetes · Stalwart ·
        Postal · Nextcloud · Plesk · Designate · ACME · CinetPay · Stripe · Victoria*
```

## État du dépôt

La Phase 0 du plan (socle du monorepo) n'a pas encore commencé. Les deux dossiers
présents sont l'héritage de la première approche, retenue puis abandonnée :

- `blesta/` — image Docker de Blesta et son installation sur Dokploy. **Abandonné** :
  la facturation est native. À supprimer en Phase 0.
- `middleware/` — premier essai Express avec un client Keystone/Nova/Cinder minimal.
  **Remplacé** par `apps/api` et `packages/openstack` ; son code sert de graine et
  disparaît en Phase 0.
- `docker-compose.yml` — pile Blesta + MariaDB + middleware. Remplacée par la pile du
  plan (Postgres, Valkey, Temporal) en Phase 0.
