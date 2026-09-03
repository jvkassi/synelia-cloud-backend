# synelia-cloud-backend

Backend de [synelia-cloud](https://github.com/jvkassi/synelia-cloud), le portail
Next.js de Synelia Cloud (vitrine, espace client, espace super admin), aujourd'hui
servi par des données fictives.

Ce dépôt construit **tout ce que le portail attend** : les 514 opérations de son
contrat `docs/api/openapi.json`, branchées sur l'OpenStack de Synelia et sur les
solutions libres du catalogue. Sans Blesta : clients, souscriptions, facturation et
paiements sont un domaine natif du backend.

**Commencer par les deux plans directeurs**, écrits pour le même contrat et les mêmes
systèmes amont, avec une comparaison honnête à la fin du second :

- [`docs/PLAN-DIRECTEUR.md`](docs/PLAN-DIRECTEUR.md) — variante **Node.js** : Node 24,
  Fastify 5, Zod 4, PostgreSQL 18 + Drizzle, Temporal, Valkey, client OpenStack à écrire.
  Contient tout ce qui ne dépend pas du langage : règles du contrat, tenancy
  organisation ↔ Keystone, modèle de données, correspondance contrat ↔ OpenStack,
  facturation, feuille de route en onze phases, décisions à prendre.
- [`docs/PLAN-DIRECTEUR-PYTHON.md`](docs/PLAN-DIRECTEUR-PYTHON.md) — variante **Python** :
  Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2 + Alembic, Temporal, Valkey, **openstacksdk**
  officiel, Authlib, Schemathesis. Renvoie au premier pour ce qui est commun et compare
  les deux pistes (§9) avec une recommandation.

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
