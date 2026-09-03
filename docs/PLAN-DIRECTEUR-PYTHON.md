# Plan directeur — variante Python

Même cible que [`PLAN-DIRECTEUR.md`](PLAN-DIRECTEUR.md) : les **514 opérations** du contrat
`openapi.json` de synelia-cloud, sans Blesta, sur l'OpenStack de Synelia. Ce document
tranche la même série de questions avec une pile **Python**, puis compare les deux
pistes (§9) pour que le choix se fasse sur des faits.

Ce qui ne dépend pas du langage n'est pas récrit : les règles du contrat (§1 du plan
Node), la tenancy organisation ↔ Keystone (§5), le modèle de données (§6), la
correspondance contrat ↔ OpenStack (§7), la chaîne de facturation (§8), la sécurité
(§9) et les points à trancher produit (§12) valent **à l'identique** ici. Ce plan couvre
ce qui change : runtime, framework, bibliothèques, structure, outillage, et la feuille
de route ajustée.

Rédigé le 2026-09-03. Versions vérifiées sur PyPI ce jour-là.

---

## 0. Résumé exécutif

| Question | Décision |
|---|---|
| Runtime | **Python 3.13** (3.13.15 ; 3.14 accepté par toutes les dépendances retenues, bascule quand les roues natives suivent), **uv 0.12** pour les environnements, le verrou et l'espace de travail multi-paquets. |
| Framework HTTP | **FastAPI 0.141** + **Pydantic 2.13**, servi par **uvicorn 0.52** + uvloop (Granian 2.8 en option). |
| Contrat | **Contrat-first** : modèles Pydantic **générés** depuis `openapi.json` par `datamodel-code-generator` 0.76 ; conformité testée par **Schemathesis 4.25** (tests par propriétés dirigés par le contrat) + `oasdiff` en CI. |
| Base de données | **PostgreSQL 18** + **SQLAlchemy 2.0** (asyncio) + **asyncpg 0.31** + **Alembic 1.19**. Multi-tenant par `org_id` **et** Row-Level Security. |
| Opérations longues | **Temporal 1.32** (SDK Python), serveur auto-hébergé sur Postgres. Même correspondance travail ↔ workflow que le plan Node. |
| Cache, verrous, limitation | **Valkey 8** via `valkey` 6.1 (client officiel, fork de redis-py). |
| Identité | **Authlib 1.8** pour *les deux sens* (client OIDC vers l'IdP du client **et** fournisseur OIDC pour les services managés), `joserfc` 1.7 (JWT/JWK), `argon2-cffi` 25.1, `pyotp` 2.10, `python3-saml` 1.16, `ldap3` 2.9. |
| OpenStack | **openstacksdk 4.20**, le SDK unifié **officiel et maintenu par OpenStack** : identity, compute, network, block_storage, image, container_infra (Magnum), load_balancer (Octavia), dns (Designate), key_manager (Barbican), database (Trove), object_store, placement. C'est **l'argument décisif** de cette variante : le paquet de clients à écrire à la main dans le plan Node n'existe plus. |
| Kubernetes | `kubernetes_asyncio` 36.1 + Argo CD / Rollouts par API REST (`httpx`), Harbor, BuildKit — identique au plan Node. |
| Paiements | `stripe` 15.6 ; CinetPay par `httpx` (pas de SDK officiel digne de ce nom). |
| PDF | **WeasyPrint 69** : facture = gabarit HTML/CSS Jinja2, rendu sans navigateur. |
| Qualité | **ruff 0.16** (lint + format), **pyright 1.1** (strict), **pytest 9**, `pytest-asyncio` 1.4, `testcontainers` 4.15, `respx` 0.23, `polyfactory` 3.3, `hypothesis` 6. |
| Observabilité | `structlog` 26.1, `opentelemetry-sdk` 1.44 + instrumentations FastAPI/SQLAlchemy/httpx, `prometheus-client` 0.26 → Victoria*. |
| Durée | Mêmes onze phases ; **Phase 2 raccourcie de deux semaines** grâce à openstacksdk. Ordre de grandeur inchangé : **10 à 12 mois**. |

---

## 1. Pourquoi une variante Python mérite d'être posée

Trois faits, pas des goûts :

1. **OpenStack est écrit en Python et publie son SDK en Python.** `openstacksdk` couvre
   chaque service du catalogue de Gazpacho avec des objets typés, la découverte de
   version, les *application credentials*, la pagination, les attentes d'état
   (`wait_for_server`, `wait_for_status`), la gestion des microversions et les
   `endpoint_override` par service — exactement ce que le plan Node prévoyait d'écrire
   dans `packages/openstack`. Les correctifs suivent chaque cycle OpenStack.
2. **L'écosystème d'exploitation de Synelia est Python.** kolla-ansible, Ansible, les
   outils Ceph, les scripts du lab. Un backend Python est lisible et corrigeable par
   l'équipe qui exploite l'OpenStack, pas seulement par celle qui écrit le portail.
3. **Deux outils sans équivalent Node sur ce projet** : **Schemathesis** (génère des
   milliers de requêtes valides et invalides depuis `openapi.json` et vérifie que
   chaque réponse respecte le contrat) et **Authlib** (un seul cadre pour être client
   OIDC/OAuth2 *et* fournisseur OIDC, certifié).

Le prix : l'asynchrone Python demande plus de discipline qu'en Node (`openstacksdk` est
synchrone, §3.6), le débit brut d'une API FastAPI est 2 à 3 fois inférieur à Fastify sur
des routes triviales (sans conséquence ici : les routes attendent Postgres ou l'amont),
et le frontend TypeScript ne partage plus le langage — les deux dépôts partagent le
**contrat**, pas le code, ce qui est déjà la règle.

---

## 2. Architecture

Identique au plan Node : monolithe modulaire, trois processus (`api`, `worker`,
`scheduler`), une base, Temporal, Valkey, connecteurs amont derrière des interfaces.
Voir le schéma du plan Node, §2. Seule différence de fond : les appels `openstacksdk`
(synchrones) vivent dans des **activités Temporal synchrones** exécutées par un
`ThreadPoolExecutor`, ou derrière `anyio.to_thread.run_sync` dans l'API pour les
lectures. Le code de domaine reste `async`.

---

## 3. Choix technologiques

### 3.1 Socle

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Runtime | **Python 3.13** | Support jusqu'en octobre 2029 ; `openstacksdk` exige ≥ 3.11 et déclare 3.14 ; toutes les roues natives (asyncpg, argon2-cffi, xmlsec, WeasyPrint) sont disponibles. 3.14 dès que les roues sont là. | 3.12 (moins de vie). |
| Paquets | **uv 0.12** (`uv.lock`, *workspace* multi-paquets, `uv run`) | Un outil pour Python, dépendances, verrou, scripts. 10 à 100× plus rapide que pip/poetry. | poetry, pip-tools, pdm. |
| Style | **ruff 0.16** (lint + format, règles `E,F,I,UP,B,ASYNC,S,PL,RUF`) | Un binaire, une config. | black + flake8 + isort. |
| Types | **pyright 1.1** en mode `strict`, exécuté dans l'éditeur et la CI | Le plus rapide et le plus précis aujourd'hui. **ty** (Astral, 0.0.78) est encore pré-1.0 : à réévaluer en 2027. | mypy 2.3 (plus lent, inférence plus faible). |
| Exécution | **uvicorn 0.52** + **uvloop 0.22**, ou **Granian 2.8** (serveur Rust, HTTP/2, rechargement) | uvicorn est la référence ASGI ; Granian est un gain de débit sans changer le code, à mesurer en Phase 3. | gunicorn (WSGI, sans objet). |
| JSON | **orjson 3.12** (`ORJSONResponse` par défaut) | 3 à 5× plus rapide que `json`, `datetime` et UUID natifs. | ujson. |

### 3.2 HTTP et contrat

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Framework | **FastAPI 0.141** | Pydantic v2 natif, OpenAPI généré depuis les modèles, injection de dépendances par `Depends` suffisante pour un monolithe, écosystème d'instrumentation le plus large. | **Litestar 2.24** : excellent (DI, msgspec, garde-fous), plus rapide, mais écosystème et recrutement plus minces. **Django Ninja 1.7** : l'ORM Django et l'admin n'ont pas d'usage ici. |
| Validation | **Pydantic 2.13** ; modèles **générés** depuis `packages/contract/openapi.json` par **datamodel-code-generator 0.76** (`--output-model-type pydantic_v2.BaseModel --use-annotated --field-constraints`) | Les 218 schémas du contrat deviennent des classes Python **sans les recopier**. Les noms français du contrat sont conservés tels quels (`tailleGo`, `parPage`) : `alias_generator` inutile, on parle le contrat. | Écrire les modèles à la main. |
| Conformité | **Schemathesis 4.25** en CI contre l'application démarrée (Postgres et Temporal en conteneurs, amont simulés) : pour chaque opération, requêtes générées, codes de réponse et schémas vérifiés ; **oasdiff** (binaire Go) : spec servie ⊇ contrat | Un contrat de 514 opérations ne se vérifie pas à la main. Schemathesis attrape les `500` sur entrée mal formée, les champs manquants, les enums hors liste. | Tests de contrat écrits un par un seulement. |
| Documentation | Scalar via `/v1/docs` (HTML statique pointant sur `/v1/openapi.json`), hors production | Lisible, joue les requêtes. | Swagger UI par défaut de FastAPI. |
| Sécurité HTTP | Middlewares Starlette : CORS, en-têtes de sécurité (`secure` 1.0), limitation par `slowapi` ou middleware maison sur Valkey (par jeton, clé d'API, IP) | Standards. | — |
| Client HTTP amont | **httpx 0.28** (async, HTTP/2, `AsyncClient` partagé par connecteur) | Référence. | aiohttp (API moins agréable). |
| Résilience amont | **stamina 26.1** (réessais raisonnés sur `tenacity` 9) + **purgatory 3.0** (disjoncteur async, état partagé dans Valkey entre répliques) | Un disjoncteur par intégration ; état ouvert = `424` daté avec dernière lecture en cache. Le partage d'état évite qu'une réplique tape encore un amont que l'autre a déjà vu tomber. | pybreaker (synchrone, état local). |

### 3.3 Données

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Base | **PostgreSQL 18** | Identique au plan Node. | — |
| ORM | **SQLAlchemy 2.0.52** (style 2.0, `Mapped[]`, `AsyncSession`) + **asyncpg 0.31** + **Alembic 1.19** (autogénération relue) | Le standard Python ; RLS posée par un événement `after_begin` qui exécute `SET LOCAL app.org_id`. Requêtes typées, pas de chaînes SQL éparses. | SQLModel (couche mince, en retard sur SQLAlchemy 2), Tortoise, Peewee. |
| Pilote sync (métrologie en masse) | **psycopg 3.3** avec `COPY` | Charger 180 M lignes/mois de relevés se fait en `COPY`, pas en `INSERT`. | — |
| Identifiants | **UUID v7** via `uuid-utils` 0.17 (Rust) côté application, `uuidv7()` côté Postgres 18 | Identique au plan Node. | — |
| Cache, verrous, limitation | **valkey 6.1** (client officiel) | Compatible redis-py ; verrous `SET NX PX`, cache amont, limitation, pub/sub. | `redis` 8.1 (fonctionne aussi ; on suit le nom du serveur). |
| Recherche | Postgres FTS + `pg_trgm` | Identique. | — |
| Métrologie | Tables partitionnées par mois, agrégats journaliers | Identique. | TimescaleDB. |
| Secrets en base | **cryptography** (AES-256-GCM, clé d'enveloppe), puis Barbican via `openstacksdk.key_manager` | Identique au plan Node ; la bascule vers Barbican est **plus courte** ici, le client existe déjà. | — |

### 3.4 Opérations longues

| Sujet | Choix | Pourquoi |
|---|---|---|
| Orchestration | **Temporal 1.32** (`temporalio`) : workflows déterministes dans le bac à sable du SDK, **activités async** pour httpx/SQLAlchemy et **activités sync** (`ThreadPoolExecutor`) pour `openstacksdk`, `boto3`, `rgwadmin` | Même correspondance que le plan Node : travail = workflow, tâche = activité, rollback = compensation, `relance` = signal, `annulation` = `cancel`, `GET /travaux/{id}` = requête. Le SDK Python est au même niveau que le SDK TypeScript (schedules, mises à jour, versioning). |
| Catalogue | Les 41 identifiants de `workflows.ts` deviennent des noms de workflows Python (`vm_create`, `espace_create`…) avec un registre `TYPE_TRAVAIL → classe` | Le frontend affiche les mêmes étapes. |
| Planification | Temporal Schedules | Cycle de facturation, sauvegardes, ACME, relances, rotation des *application credentials*. |
| Écarté | Celery 5.6, Dramatiq 2.2, TaskIQ 0.12, Procrastinate 3.9, PgQueuer 1.3 | Files de tâches, pas d'orchestration durable : la saga à 9 étapes avec compensation est à réécrire dans chacune. |

### 3.5 Identité et accès

| Sujet | Choix | Pourquoi |
|---|---|---|
| Mots de passe | **argon2-cffi 25.1** (argon2id) | Référence. |
| MFA | **pyotp 2.10** (TOTP) ; `webauthn` (py_webauthn) en phase 2 | `/auth/mfa`, `/moi/mfa`. |
| Jetons | **joserfc 1.7** : JWT EdDSA (Ed25519), JWKS publié, accès 15 min ; rafraîchissement opaque rotatif en base | Sessions révocables (`/moi/sessions`, `/securite/sessions`). |
| Fédération amont | **Authlib 1.8** (`AsyncOAuth2Client`, découverte OIDC, PKCE) ; **python3-saml 1.16** (OneLogin, sur `xmlsec`) ; **ldap3 2.9** en phase ultérieure | `/securite/sso`, `/auth/sso/decouverte`, `/auth/sso/callback`. |
| Fournisseur OIDC aval | **Authlib 1.8, cadre serveur** (`AuthorizationServer`, grants `authorization_code` + PKCE, `refresh_token`, `client_credentials`, OpenID Connect Core, découverte, JWKS) | Un seul paquet pour les deux sens : c'est ici que Python bat le plan Node en clarté (`openid-client` + `oidc-provider` = deux bibliothèques, deux modèles). Nextcloud, Odoo, GitLab, Metabase deviennent clients OIDC de Synelia ; `POST /services/{id}/ouverture` = URL de connexion à usage unique. |
| Clés d'API, RBAC | Identique au plan Node : préfixe + hash SHA-256, portée ⊆ rôle ; matrice `rbac.ts` copiée en `rbac.py` et vérifiée identique en CI ; dépendance FastAPI `exige("vm.create_delete")` qui journalise le refus. | — |

### 3.6 OpenStack avec openstacksdk

`packages/openstack/` devient **mince** : une fabrique de connexions et des mappeurs.

| Composant | Contenu |
|---|---|
| `connexion.py` | `openstack.connect()` par **Espace Cloud** à partir de l'*application credential* chiffrée en base (`auth_type=v3applicationcredential`), `region_name` = site, `endpoint_override` par service depuis `OS_ENDPOINT_OVERRIDES` (tunnel du lab), microversions épinglées par `compute_api_version` / `block_storage_api_version` relevées dans le lab. Cache de connexions par espace (LRU, 15 min), une connexion admin pour le bootstrap des domaines/projets. |
| `services.py` | Accès nommés : `conn.compute`, `conn.network`, `conn.block_storage`, `conn.image`, `conn.identity`, `conn.container_infra`, `conn.load_balancer`, `conn.dns`, `conn.key_manager`, `conn.database`, `conn.object_store`, `conn.placement`. Rien à écrire : ce sont les *proxies* du SDK. |
| `attentes.py` | `wait_for_server`, `wait_for_status`, `wait_for_delete` du SDK, enveloppés en activités Temporal avec *heartbeat* pour que le worker puisse mourir et reprendre. |
| `erreurs.py` | `openstack.exceptions.*` → `AppError` du contrat (`ConflictException` → `nom_deja_pris`, `HttpException 403 OverQuota` → `quota_depasse`, `ResourceNotFound` → `introuvable`). |
| `rgw.py` | **rgwadmin 2.4** (Admin Ops : utilisateurs, clés, quotas, usage) + **boto3 1.43** (S3 : versioning, object lock, politiques, journaux, réplication). `aiobotocore` 3.9 pour les URL présignées côté API. |
| `notifications.py` | Consommateur oslo.messaging (`aio-pika` sur RabbitMQ) des notifications `compute.instance.*`, `volume.*`, `port.*`. Identique au plan Node. |

Le SDK est **synchrone** : toute utilisation passe par une activité Temporal synchrone
(exécutée dans le pool de threads du worker) ou, pour les rares lectures directes de
l'API (`/catalogue/gabarits`, `/catalogue/images`), par `anyio.to_thread.run_sync` avec
cache Valkey 10 min. Une règle Ruff (`ASYNC`) et une revue empêchent tout appel bloquant
dans une coroutine.

Ce que le SDK ne fait pas et qu'on garde à la main : la traduction vers les formes du
contrat (`mappers.py` de chaque module), le catalogue de `classe` de volume ↔
`volume_type` par région, et les refus documentés (`422`) pour ce que l'amont ne porte
pas (`scsiControllers`, `waf` Octavia, PRA `continu`).

### 3.7 Kubernetes, Web Cloud, services managés, commerce

Identiques au plan Node dans les choix amont (Magnum capi-helm, Argo CD + Rollouts,
Harbor + Trivy, BuildKit, Envoy Gateway, opérateurs de bases ; Stalwart, Postal,
Nextcloud, Plesk/HestiaCP, OpenProvider, Designate ; CinetPay, Stripe, virement,
prépayé en grand livre). Seules les bibliothèques changent :

| Sujet | Python |
|---|---|
| Kubernetes | **kubernetes_asyncio 36.1** (client officiel, async) ; `lightkube` 1.0 écarté (plus élégant, moins complet). Argo CD, Rollouts, Harbor : `httpx`. |
| ACME | **acme 5.8** (la bibliothèque de Certbot) : ordres, DNS-01 sur Designate via `conn.dns`. |
| Stalwart, Postal, Nextcloud OCS, Plesk REST, OpenProvider, CinetPay, WAHA, Orange SMS, VictoriaMetrics/Logs | Connecteurs `httpx` typés Pydantic, un paquet chacun sous `packages/connecteurs/`, `respx` pour les tests. |
| Stripe | **stripe 15.6** (SDK officiel, webhooks signés). |
| Charts Helm des 13 services managés | Déclenchés par Argo CD (`Application` par instance) ; `ConnecteurService` × 13 en Python, paramètres depuis `packages/catalogue/` (copie des `configurations/*.ts` traduits en JSON une fois, puis chargés). |
| PDF de facture | **WeasyPrint 69** : gabarit Jinja2 + CSS d'impression (`@page`, en-têtes, mentions légales, QR FNE quand il existera). Sans navigateur, ~200 ms par facture. `reportlab` 5.0 écarté (impératif, pénible pour la mise en page). |
| Courriels | Jinja2 + envoi par l'API Postal ; `email-validator` 2.3 à l'entrée. |
| Copilote | SDK Anthropic Python, lectures seules. |

### 3.8 Transversal

| Sujet | Choix |
|---|---|
| Journalisation | **structlog 26.1** (JSON, `correlation_id`, `org_id`, `user_id`, processeur de masquage des secrets) → VictoriaLogs. |
| Traces et métriques | **opentelemetry-sdk 1.44** + `opentelemetry-instrumentation-{fastapi,sqlalchemy,httpx,asyncpg}` → VictoriaTraces ; **prometheus-client 0.26** (`/metrics` interne) → VictoriaMetrics. |
| Configuration | **pydantic-settings 2.15** : chaque variable typée et validée au démarrage. |
| CLI | **typer 0.27** : `synelia api|worker|scheduler`, `synelia contrat sync|diff`, `synelia facturation cycle --mois 2026-09 --simulation`, `synelia fixtures enregistrer`. |
| Tests | **pytest 9**, `pytest-asyncio` 1.4 (`asyncio_mode=auto`), **testcontainers 4.15** (Postgres 18, Valkey, `temporalio/auto-setup`), `httpx.AsyncClient(transport=ASGITransport)` pour l'API, **respx 0.23** pour les amont httpx, `boto3` `Stubber` et fixtures enregistrées pour openstacksdk (`requests-mock`), **polyfactory 3.3** (fabriques Pydantic/SQLAlchemy), **hypothesis 6** sur le moteur de tarification (propriétés : monotonie, estimation = facture), `temporalio.testing.WorkflowEnvironment.start_time_skipping()` pour les workflows, **Schemathesis** en CI nocturne (long) et par domaine en CI de branche. |
| CI | GitHub Actions : `uv sync --frozen` → ruff → pyright → pytest (unitaires + intégration conteneurs) → `schemathesis run --checks all` sur le domaine touché → `oasdiff` contre `packages/contract/openapi.json` → image Docker (`python:3.13-slim`, `uv` multi-étapes, utilisateur non-root). |
| Déploiement | Image unique, commande selon rôle ; Dokploy puis Kubernetes plateforme. Identique. |

---

## 4. Structure du dépôt

Espace de travail **uv** : un `pyproject.toml` racine déclare `[tool.uv.workspace]`, chaque
paquet a le sien. Les imports sont absolus (`from synelia_kernel.erreurs import AppError`).

```
synelia-cloud-backend/
├── pyproject.toml                  # workspace uv, ruff, pyright, pytest
├── uv.lock
├── docker-compose.yml              # dev : postgres 18, valkey 8, temporal + ui, mailpit, minio
├── docker-compose.dokploy.yml
├── Dockerfile                      # python:3.13-slim, uv, image unique
├── .github/workflows/ci.yml
├── docs/
│   ├── PLAN-DIRECTEUR.md           # variante Node
│   ├── PLAN-DIRECTEUR-PYTHON.md    # ce document
│   ├── ADR/
│   └── runbooks/
│
├── apps/
│   └── synelia/                    # UN paquet applicatif, trois rôles
│       └── synelia/
│           ├── __main__.py         # typer : api | worker | scheduler | contrat | facturation | fixtures
│           ├── app.py              # fabrique FastAPI : middlewares, routeurs des modules, cycle de vie
│           ├── deps/               # correlation, auth, tenant (SET LOCAL), rbac, pagination, confirmation
│           ├── worker.py           # enregistre workflows + activités de tous les modules
│           ├── scheduler.py        # déclare les Temporal Schedules (idempotent)
│           └── modules/            # UN paquet par domaine du contrat (gabarit ci-dessous)
│
├── packages/
│   ├── contract/synelia_contract/  # openapi.json copié + modeles.py GÉNÉRÉ + rbac.py + workflows.py
│   ├── catalogue/synelia_catalogue/# configurations des 13 services managés (JSON) + chargeur
│   ├── db/synelia_db/              # modèles SQLAlchemy par domaine, alembic/, rls.py, session.py
│   ├── kernel/synelia_kernel/      # AppError, ids (uuid7), argent (int + devise), dates, chiffrement, journal, config
│   ├── openstack/synelia_openstack/# §3.6 : connexion, attentes, erreurs, rgw, notifications
│   ├── k8s/synelia_k8s/            # kubernetes_asyncio, argocd, rollouts, harbor, buildkit
│   ├── connecteurs/                # un paquet par amont : stalwart, postal, nextcloud, plesk, hestiacp,
│   │                               #   registrar_openprovider, acme, cinetpay, stripe, victoria, centreon,
│   │                               #   waha, orange_sms, services/ (ConnecteurService × 13)
│   └── testing/synelia_testing/    # conteneurs, fixtures amont enregistrées, fabriques polyfactory
│
└── tools/
    ├── contrat_sync.py             # copie openapi.json + rbac.ts→rbac.py + configurations depuis ../synelia-cloud
    ├── contrat_diff.sh             # oasdiff : servie ⊇ contrat, rapport de couverture
    └── enregistrer_fixtures.py     # capture (via tunnel) des réponses du lab pour les tests openstacksdk
```

### Gabarit d'un module (`apps/synelia/synelia/modules/vms/`)

```
vms/
├── __init__.py
├── router.py         # APIRouter : une fonction par opération, nommée par operationId (creer_vm, lister_vms…)
├── schemas.py        # ré-exports des modèles générés du contrat + modèles internes d'entrée
├── service.py        # cas d'usage : règles, quotas, estimation, démarrage des travaux
├── repo.py           # SQLAlchemy : requêtes sur les tables du module, RLS respectée
├── mappers.py        # openstack.compute.v2.server.Server → VM du contrat, jamais l'inverse
├── workflows.py      # @workflow.defn : VmCreate, VmResize, VmSnapshot… (compensations dans finally)
├── activities.py     # @activity.defn : idempotentes, un appel amont chacune, heartbeat sur les attentes
├── evenements.py     # événements de domaine → audit, métrologie, notifications (outbox)
└── tests/
    ├── test_router.py        # contrat : chaque opération, chaque code déclaré (ASGITransport)
    ├── test_service.py
    └── test_workflows.py     # WorkflowEnvironment time-skipping, activités simulées
```

Règles de dépendance, vérifiées par **import-linter** (contrats `layers` et `independence`) :

- `modules.*` → `synelia_*` (packages) : oui. `modules.a` → `modules.b.service` : oui.
  `modules.a` → `modules.b.repo` : **non**.
- `synelia_openstack` et `synelia_connecteurs.*` ne connaissent **ni** `synelia_db` **ni**
  `synelia_contract` : ils parlent l'amont, les `mappers.py` traduisent.
- `synelia_kernel` ne dépend de rien d'autre.

Les modules sont les mêmes que dans le plan Node (§4) : `auth`, `compte`, `organisations`,
`membres`, `securite`, `audit`, `tableau_de_bord`, `travaux`, `espaces`, `vms`,
`kubernetes`, `reseau`, `stockage`, `bases`, `sauvegarde`, `pra`, `applications`,
`projets`, `modeles`, `observabilite`, `services_manages`, `web_domaines`, `web_dns`,
`web_hebergement`, `web_emails`, `web_drive`, `web_ssl`, `web_backup`, `web_smtp`,
`facturation`, `support`, `docs`, `admin`, `public`.

---

## 5. Le contrat, de bout en bout, en Python

```
../synelia-cloud/docs/api/openapi.json
        │  tools/contrat_sync.py (copie + rbac.ts → rbac.py + configurations → JSON)
        ▼
packages/contract/synelia_contract/openapi.json
        │  datamodel-codegen → modeles.py (218 classes Pydantic v2, noms du contrat)
        ▼
modules/*/router.py  ──  response_model=VM, status_code=202 …
        │  FastAPI génère /v1/openapi.json depuis les routes
        ▼
CI : oasdiff  (servie ⊇ contrat)   +   schemathesis run openapi.json --base-url …
```

- Les modèles générés ne sont **jamais** édités ; un besoin interne (colonne, état
  intermédiaire) vit dans `schemas.py` du module ou dans `synelia_db`.
- `operationId` du contrat = nom de la fonction de route, en *snake_case* : `creerVm` →
  `creer_vm`. Le rapport de couverture liste les `operationId` du contrat absents de
  l'application : c'est le compteur qu'on fait monter, 0/514 en Phase 0.
- Schemathesis tourne avec des *hooks* qui fournissent un jeton valide par rôle, une
  organisation de test et des identifiants existants, pour que les `404` générés ne
  masquent pas les vrais défauts.

---

## 6. Ce qui ne change pas

Repris à l'identique du plan Node, sans récriture :

| Sujet | Référence |
|---|---|
| Règles du contrat (enveloppes, `202`, `424`, `confirmation`, `403 rolesRequis`, `X-Organisation-Id`, FCFA entiers) | `PLAN-DIRECTEUR.md` §1 |
| Tenancy organisation → domaine Keystone, Espace → projet + *application credential*, site → région | §5 |
| Modèle de données (tables par domaine, RLS, audit append-only) | §6 |
| Correspondance opération ↔ appels OpenStack | §7 (les appels se lisent `conn.compute.create_server(...)` au lieu de `POST /servers`) |
| Chaîne de facturation, règles de tarification, numérotation | §8 |
| Sécurité (application credentials, secrets, audit, jetons, emprunt d'identité, élévation, idempotence) | §9 |
| Environnements (local, CI, bac à sable, production) et fixtures du lab | §10 |
| Points à trancher produit (Plesk/Hestia, Trove/opérateurs, registrar .ci, FNE, seconde région, PRA continu, Grommunio/Stalwart, paiements, inventaire du lab) | §12, sauf le point 8 (Keycloak) qui devient moins pressant : Authlib couvre déjà les deux sens |

---

## 7. Feuille de route

Mêmes onze phases, mêmes périmètres et mêmes définitions de « fini » que le plan Node
(§11). Deux ajustements de durée, un ajout de contenu :

| # | Phase | Durée Node | Durée Python | Pourquoi |
|---|---|---|---|---|
| 0 | Socle | 2 sem. | 2 sem. | uv workspace, FastAPI, SQLAlchemy + Alembic + RLS, Temporal, Valkey, kernel, `contrat_sync`, `datamodel-codegen`, `oasdiff`, Schemathesis branché, CI, Dockerfile. |
| 1 | Identité, organisations, travaux | 4 sem. | 4 sem. | Authlib serveur inclus dès la Phase 1 (le plan Node le reportait aux services managés) : la fondation SSO existe avant qu'on en ait besoin. |
| 2 | IaaS cœur | 8 sem. | **6 sem.** | Plus de clients OpenStack à écrire ni à tester sur fixtures : `openstacksdk` + mappeurs. Le temps gagné va aux workflows et aux compensations. |
| 3 | Tableau de bord, observabilité | 3 sem. | 3 sem. | — |
| 4 | Facturation et commerce | 6 sem. | 6 sem. | WeasyPrint accélère le PDF ; la logique de grille, cycle et grand livre est la même. |
| 5 | Kubernetes, bases, DNS, SSL | 5 sem. | **4 sem.** | Magnum, Trove, Designate, Barbican : déjà dans le SDK. |
| 6 | Sauvegarde et PRA | 4 sem. | 4 sem. | Cinder backups via SDK, mais l'orchestration PRA est le vrai travail. |
| 7 | Plateforme applicative | 8 sem. | 8 sem. | Kubernetes et Argo CD : parité. |
| 8 | Services managés | 8 sem. | 8 sem. | Helm + 13 connecteurs : parité. |
| 9 | Web Cloud | 8 sem. | 8 sem. | Connecteurs httpx : parité. |
| 10 | Super admin, support, docs, vitrine | 5 sem. | 5 sem. | Placement API via SDK, marginal. |
| 11 | IA & Agents | à cadrer | à cadrer | Écosystème IA nativement Python (vLLM, LiteLLM, pgvector, LangGraph) : léger avantage si cette phase pèse. |

Total brut : **58 semaines** contre 61, mêmes parallélisations, même ordre de grandeur
de **10 à 12 mois**. La différence de trois semaines est réelle mais **n'est pas le
critère** : le critère est §9.

---

## 8. Semaine 1, concrètement

1. `uv init --workspace`, `synelia_kernel`, `synelia_contract` + `tools/contrat_sync.py`
   (copie `openapi.json`, transpile `rbac.ts` → `rbac.py` par une petite AST, exporte les
   `configurations/*.ts` en JSON via un script Node lancé une fois côté frontend).
2. `datamodel-codegen` → `modeles.py` ; vérification que les 218 classes s'importent et
   que `VM`, `Volume`, `TravailProvisioning`, `Erreur` ont bien les champs du contrat.
3. `apps/synelia` : FastAPI, middlewares `correlation`, `erreurs`, dépendances
   `pagination`, `confirmation` ; `GET /healthz` ; `tools/contrat_diff.sh` rouge à
   0/514 ; Schemathesis branché sur `/healthz` pour prouver la chaîne.
4. `synelia_db` : Postgres 18 en testcontainer, SQLAlchemy 2.0 async, première migration
   Alembic (`organisations`, `utilisateurs`, `sessions`, `memberships`, `audit`), RLS
   posée par `after_begin`, test qui prouve qu'une session à l'org A ne lit pas l'org B.
5. Temporal en compose, workflow `demo_echo` avec activité sync et activité async,
   projection dans `travaux`, `GET /travaux/{id}` conforme, test time-skipping.
6. Depuis dev01 : tunnel, `openstack.connect()` avec `OS_ENDPOINT_OVERRIDES`,
   `tools/enregistrer_fixtures.py` (catalogue, flavors, images, un serveur, un volume,
   quotas, `openstack service list` pour l'inventaire §12.10).
7. CI verte : ruff, pyright strict, pytest, schemathesis (domaine `travaux`), oasdiff,
   image.

---

## 9. Node ou Python : la comparaison

| Critère | Node (plan principal) | Python (cette variante) | Avantage |
|---|---|---|---|
| Client OpenStack | À écrire : ~10 services, types générés ou manuels, fixtures du lab, maintenance à chaque cycle | **openstacksdk** officiel, maintenu par OpenStack, tous les services du catalogue | **Python, nettement** |
| Orchestration durable | Temporal TS 1.23 | Temporal Python 1.32 | Parité |
| Contrat-first | openapi-typescript (types) + Zod écrits à la main + openapi-diff | datamodel-codegen (modèles **exécutables**) + **Schemathesis** + oasdiff | **Python** |
| Identité | jose + openid-client + oidc-provider (trois bibliothèques, excellentes) | Authlib (client **et** serveur) + joserfc + python3-saml | **Python, légèrement** |
| Débit HTTP brut | Fastify : très élevé | FastAPI : 2 à 3× moins sur route triviale | Node — sans effet ici (routes liées à Postgres/amont) |
| Modèle async | Boucle unique, tout est async, pas de piège bloquant | asyncio + code sync à isoler (openstacksdk, boto3) ; discipline requise | Node |
| Langage partagé avec le frontend | Oui (types, conventions, une seule stack à recruter) | Non — mais les deux dépôts ne partagent que le **contrat**, par conception | Node, légèrement |
| Proximité de l'exploitation | Aucune : l'infra est en Python/Ansible | Même langage que kolla-ansible, Ceph, les scripts du lab | **Python** |
| PDF de facture | @react-pdf/renderer (déclaratif, TS) | WeasyPrint (HTML/CSS d'impression) | Parité, léger avantage Python pour la mise en page légale |
| Kubernetes, Argo, Helm | client-node 2.0 + REST | kubernetes_asyncio + REST | Parité |
| Connecteurs Web Cloud, paiements | undici + cockatiel | httpx + stamina + purgatory | Parité |
| Outillage qualité | Biome, tsgo, vitest, testcontainers | ruff, pyright, pytest, testcontainers, hypothesis | Parité |
| Phase 11 (IA) | SDK et passerelles disponibles | Écosystème natif (vLLM, LiteLLM, LangGraph, pgvector) | Python |
| Effort total | ~61 sem. brutes | ~58 sem. brutes | Python, marginal |

**Recommandation.** Le code le plus risqué de ce projet n'est ni le HTTP ni la
facturation : c'est de parler correctement à OpenStack pour une centaine d'opérations,
avec les attentes d'état, les microversions, les quotas et les compensations. Sur ce
point précis, Python part avec un SDK officiel que Node n'aura jamais. À cela s'ajoute
que l'équipe qui exploite l'OpenStack de Synelia travaille en Python. **Si le backend
est porté par l'équipe infrastructure, ou par une équipe qui reste à constituer,
prendre la variante Python.** Si le backend est porté par l'équipe qui écrit le
portail et qu'elle veut une seule pile, la variante Node reste un excellent plan — elle
coûte un paquet de clients OpenStack en plus, et rien d'autre.

Ce que le choix ne change pas : le contrat, la tenancy, le modèle de données, Temporal,
Postgres, Valkey, les amont, les phases. On peut changer de langage entre la Phase 0 et
la Phase 1 sans perdre autre chose que le socle ; après la Phase 2, on ne change plus.

---

## 10. À trancher, spécifique à cette variante

1. **Python 3.13 ou 3.14 dès le départ ?** Toutes les dépendances retenues déclarent 3.14 ;
   quelques roues natives peuvent manquer sur `slim`. Recommandation : 3.13 en Phase 0,
   passage à 3.14 en Phase 3 quand les conteneurs de test le prouvent.
2. **uvicorn ou Granian ?** Recommandation : uvicorn + uvloop jusqu'à la Phase 3, mesure
   sous charge, Granian si le gain dépasse 30 % sans régression d'instrumentation OTel.
3. **Isolation du code synchrone.** Activités Temporal sync dans un pool de threads
   dimensionné (par défaut 8 par worker) ou processus séparé `worker-sync` ? Recommandation :
   pool de threads, puis file de tâches dédiée `openstack` dans Temporal si la latence des
   activités async en souffre.
4. **`ty` plutôt que pyright ?** Pas avant sa 1.0. Réévaluer début 2027.
5. **Schemathesis en CI de branche : combien ?** Le contrat complet prend des dizaines de
   minutes. Recommandation : le domaine touché en CI de branche (`--include-tag`), tout
   le contrat chaque nuit.
