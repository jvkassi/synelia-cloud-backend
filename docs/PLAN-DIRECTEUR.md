# Plan directeur — synelia-cloud-backend

Backend complet de [synelia-cloud](https://github.com/jvkassi/synelia-cloud) : tout ce que le
portail attend, sans Blesta, sans mock, sur l'OpenStack de Synelia.

Document de référence pour construire. Il tranche le cadre (runtime, framework, base,
orchestration, bibliothèques), la structure du dépôt, le modèle de tenancy, la
correspondance contrat ↔ systèmes amont, et l'ordre des chantiers. Ce qui reste à
trancher est listé en §12, pas caché dans le texte.

Rédigé le 2026-09-03. Versions vérifiées sur le registre npm ce jour-là.

---

## 0. Résumé exécutif

| Question | Décision |
|---|---|
| Périmètre | Les **514 opérations / 364 chemins / 218 schémas** de `docs/api/openapi.json` du frontend (OpenAPI 3.0.3). Le contrat est la spécification ; ce plan ne le réécrit pas. |
| Hors contrat | L'univers **IA & Agents** (`/app/ia/**`, 9 actions RBAC `ia.*`) n'a **aucun chemin** dans l'OpenAPI. Il est planifié en dernière phase et exige d'abord une extension du contrat côté frontend. |
| Blesta | **Abandonné.** Clients, souscriptions, facturation, paiements, relances, devis : domaine natif du backend. |
| Forme | **Monolithe modulaire** TypeScript, un dépôt, trois processus (`api`, `worker`, `scheduler`), une base. Pas de microservices. |
| Runtime | **Node.js 24 LTS**, pnpm 10, TypeScript 6.0 comme compilateur de référence (tsgo 7.0 en vérification rapide seulement, voir §3.1). |
| Framework HTTP | **Fastify 5.12** + **Zod 4.5** (`fastify-type-provider-zod` 7) + `@fastify/swagger` 9. Contrat vérifié en CI par diff OpenAPI. |
| Base de données | **PostgreSQL 18** + **Drizzle ORM 0.45** + `drizzle-kit`. Multi-tenant par colonne `org_id` **et** Row-Level Security. |
| Opérations longues | **Temporal 1.23** (SDK TypeScript, serveur auto-hébergé sur Postgres). Un `TravailProvisioning` = une exécution de workflow ; une tâche = une activité ; rollback = compensation saga. |
| Cache, verrous, limitation | **Valkey 8** (compatible Redis) via `ioredis` 6. |
| Identité | Fournisseur d'identité **natif** : `argon2`, `otpauth` (TOTP), `jose` (JWT/JWKS), `openid-client` 6 et `@node-saml/node-saml` 5 pour la fédération amont, **`oidc-provider` 9** pour être le fournisseur OIDC des services managés (SSO). |
| OpenStack | **Aucun SDK Node maintenu** (pkgcloud mort, js-openstack-lib retiré). On écrit `@synelia/openstack` : clients typés par service sur `undici`, Keystone v3 à *application credentials*. |
| Cible OpenStack | Lab **2026.1 Gazpacho** (kolla-ansible) : Keystone, Nova, Neutron, Cinder, Glance, Magnum, Octavia, Designate confirmés par le catalogue ; Trove, Barbican, CloudKitty, Ceph RGW à confirmer (§12). |
| Kubernetes | `@kubernetes/client-node` 2.0 + **Argo CD** (déjà exploité chez Synelia) + Argo Rollouts pour le canari. Clusters clients par **Magnum + driver Cluster API Helm**. |
| Paiements | **CinetPay** (agrégateur : Wave, Orange Money, MTN MoMo, cartes) + **Stripe** 22 (cartes EUR/USD) + virement rapproché à la main + porte-monnaie prépayé en grand livre à double entrée. |
| Web Cloud | Messagerie **Stalwart** (multi-tenant natif), relais SMTP **Postal** (clés, messages, webhooks : 1:1 avec le contrat), drive **Nextcloud**, certificats **acme-client** 5 + DNS-01 sur Designate, hébergement mutualisé **Plesk** derrière une interface d'adaptateur (HestiaCP en repli OSS, §12). |
| Observabilité | VictoriaMetrics / VictoriaLogs / VictoriaTraces (déjà en place), `prom-client`, OpenTelemetry, `pino` 10. Le portail ne sert que `Tuile`, `Serie`, `ExtraitLogs`, `LiensSortie`. |
| Tests | `vitest` 5, `testcontainers` 12 (Postgres, Valkey, Temporal), `nock` 14 pour les amont, validation des réponses contre le contrat. |
| Durée | **11 phases**, environ 10 à 12 mois pour un développeur senior assisté d'agents, en livrant un domaine complet à la fois derrière le frontend réel. |

---

## 1. Ce que le contrat impose

Tout est dans `docs/api/README.md` du frontend ; on rappelle ici ce qui structure le
backend, parce que chaque module devra s'y plier sans exception.

| Règle | Conséquence backend |
|---|---|
| Base `/v1`, JSON UTF-8, champs en français, identiques à `src/lib/types.ts` | Les schémas Zod reprennent les noms du contrat. Pas de « traduction » entre couche HTTP et domaine : les mappeurs traduisent **depuis l'amont** (Nova, Stalwart…) vers le contrat, jamais l'inverse. |
| Montants entiers en **FCFA hors taxes** | Colonnes `bigint`, jamais de flottant. EUR/USD stockés en centimes avec la devise à côté. Aucune bibliothèque monétaire : la règle est « entier + devise ». |
| Dates ISO 8601 UTC | `timestamptz` partout, sérialisation `toISOString()`. |
| Collections en `{ donnees, pagination }`, paramètres `page`, `parPage`, `tri`, `ordre`, `q` | Un seul helper `pagine()` ; `pagination` = `{ page, parPage, total, totalPages }`. |
| Organisation portée par le jeton, remplaçable par `X-Organisation-Id` | Le contexte de requête calcule `orgId` une fois ; RLS Postgres pose `SET LOCAL app.org_id` par transaction. Une requête sans `org_id` sur une table tenant échoue en base, pas seulement en code. |
| Long = `202` + `TravailProvisioning`, suivi par `GET /travaux/{id}` | Une seule fabrique `demarrerTravail(type, entree)` qui ouvre l'exécution Temporal et renvoie la forme du contrat. |
| Erreur `{ erreur: { code, message, correlationId } }` | `AppError(code, statut, message)` + gestionnaire unique. `correlationId` = ULID posé en entrée de requête, propagé dans les journaux, les activités Temporal et les appels amont (`X-Correlation-Id`). |
| Secrets renvoyés à la création ou à la rotation seulement | Les colonnes secrètes sont chiffrées (AES-256-GCM, clé d'enveloppe) et les schémas de réponse *n'ont pas le champ* ailleurs que sur ces deux opérations. |
| Destructif = paramètre `confirmation` = nom exact, sinon `422` sans rien détruire | Hook de route `exigeConfirmation(res => res.nom)` exécuté **avant** toute lecture amont. |
| Facturable = `POST /facturation/estimation` d'abord | Le moteur de tarification (§8) expose `estimer(ressource)` réutilisé par l'estimation et par la création. |
| Amont en défaut = `424` avec `integration`, `donneesPartielles`, `dateDonnees` | Chaque connecteur amont est enveloppé dans un disjoncteur (`cockatiel` 4). Un état ouvert renvoie la dernière lecture en cache Valkey, datée. |
| `403` avec `rolesRequis`, refus journalisé | La matrice RBAC de `src/lib/rbac.ts` (38 actions × 10 rôles) est **copiée dans le dépôt** (`packages/contract/rbac.ts`) et vérifiée identique en CI. Le hook `exige('vm.create_delete')` écrit l'événement d'audit sur refus. |
| Portées `/**` client, `/admin/**` super admin, `/public/**` sans authentification | Trois plugins Fastify racine, trois politiques d'authentification. `/admin/**` refuse tout jeton sans rôle `super_admin` ou `platform_operator`. |

Deux règles produit que le contrat *fait respecter* :

- **Un domaine est attaché à un serveur et à un seul** → contrainte d'unicité en base sur
  `web_domaines.nom`, et `409` sur l'attachement.
- **Les bases mutualisées n'ont aucun accès distant** → `hoteInterne` est une boucle
  locale, aucune route ne l'ouvre.

---

## 2. Architecture cible

```
                         synelia-cloud (Next.js, Vercel)
                                     │  HTTPS /v1
                                     ▼
┌──────────────────────── synelia-cloud-backend ─────────────────────────┐
│                                                                        │
│  api  (Fastify)          worker  (Temporal)        scheduler           │
│  ─ routes par module     ─ workflows par module    ─ métrologie horaire│
│  ─ auth, RBAC, tenant    ─ activités = appels      ─ cycle de factur.  │
│  ─ validation Zod          amont idempotents       ─ relances, purges  │
│  ─ 202 → travaux         ─ compensation (rollback) ─ sondes de santé   │
│          │                        │                        │           │
│          └──────── packages/ (domaine, db, openstack, connecteurs) ────┘
│                                   │                                    │
│   PostgreSQL 18 (plan de contrôle, RLS)   Valkey 8   Temporal (Postgres)│
└────────────────────────────────────────────────────────────────────────┘
          │                │              │               │
          ▼                ▼              ▼               ▼
   OpenStack Gazpacho   Kubernetes    Web Cloud        Commerce
   Keystone Nova        plateforme    Stalwart         CinetPay
   Neutron Cinder       Argo CD       Postal           Stripe
   Glance Magnum        Rollouts      Nextcloud        (virement)
   Octavia Designate    Harbor        Plesk/Hestia
   Trove Barbican       CNPG & co     Registrar
   Ceph RGW (S3)        Trivy         ACME
          │
   VictoriaMetrics · VictoriaLogs · VictoriaTraces · Centreon · WAHA (WhatsApp)
```

**Pourquoi un monolithe modulaire et pas des services.** Le contrat est une seule API
avec un seul modèle de tenancy et un seul journal d'audit. Le découpage qui compte est
celui des *modules* (un par domaine du contrat) et des *processus* (servir HTTP, exécuter
des workflows, tenir l'horloge) — pas celui des déploiements. Un module ne parle à un
autre que par son service exporté, jamais par ses tables : c'est ce qui permettra
d'extraire un domaine si un jour une équipe en a la charge, sans le décider aujourd'hui.

**Trois processus, une image Docker.** `node dist/main.js api|worker|scheduler`. Même
code, même configuration, rôles différents. Le `worker` peut monter à plusieurs répliques
sans toucher à l'`api`.

**Le plan de contrôle est la source de vérité, l'amont est la réalité.** Une VM existe
dans notre base *avant* d'exister dans Nova (statut `creating`) et *après* avoir été
supprimée (statut `deleted`, conservé pour la facturation). Un réconciliateur horaire
compare et signale les dérives (`anomalies`) au lieu de les masquer.

---

## 3. Choix technologiques

Chaque ligne : ce qu'on prend, en quelle version, pourquoi, ce qu'on a écarté.

### 3.1 Socle

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Runtime | **Node.js 24 LTS** (24.20) | LTS actif jusqu'en 2028. Le cœur Rust du worker Temporal et `argon2` sont des addons natifs Node. | Bun comme runtime : le SDK Temporal ne le supporte pas ; on garde Node. |
| Paquets | **pnpm 10**, workspaces | Monorepo `apps/` + `packages/`, liens stricts, un seul lockfile. | bun (imposé côté frontend) : deuxième format de verrou pour rien côté backend ; npm : trop lent en workspace. |
| Langage | **TypeScript 6.0.3** pour l'émission et l'outillage, **tsgo 7.0** en `typecheck` rapide | TS 7 (compilateur Go, GA le 8 juillet 2026) n'a pas d'API programmatique stable avant 7.1 : `typescript-eslint`, `vitest --typecheck` et les générateurs en dépendent. On prend la vitesse là où elle ne casse rien. | Passer tout en TS 7 maintenant. |
| Style | **Biome 2.5** (lint + format) | Un outil, une config, rapide. | ESLint 10 + Prettier : deux outils, config lourde. |
| Exécution dev | **tsx 4.23** (`tsx watch`) | Zéro configuration, esbuild dessous, insensible à la version de TS. | ts-node. |
| Build | **esbuild** via tsx/tsup → `dist/` ESM | Un bundle par processus, démarrage < 1 s. | tsc seul (trop lent en watch). |

### 3.2 HTTP et contrat

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Framework | **Fastify 5.12** | Le schéma est la source de vérité : validation d'entrée, sérialisation de sortie et OpenAPI sortent de la même déclaration. Plugins encapsulés = frontières de module naturelles. ~2× Express en débit. | **NestJS 12** : la DI et les décorateurs apportent de la structure, mais dupliquent ce que l'OpenAPI existant impose déjà, et le contrat-first y est contre-nature (DTO classes + class-validator). **Hono 4** : excellent, mais moins outillé côté serveur long-vécu (plugins, hooks de cycle de vie). **Express 5** : plus lent, sans schéma. |
| Validation | **Zod 4.5** + **fastify-type-provider-zod 7.0** | Types inférés, un schéma par ressource du contrat, export OpenAPI via `@fastify/swagger` 9.8. Peer deps vérifiées : `fastify ^5.5`, `zod >=4.1.5`. | TypeBox : plus rapide, mais l'écosystème (openapi, tests) est plus mince. |
| Types du contrat | **openapi-typescript 7.13** → `packages/contract/types.d.ts` | Le fichier `openapi.json` du frontend est copié dans `packages/contract/` à chaque mise à jour (script `pnpm contrat:sync`), les types en sortent. Le domaine importe ces types : renommer un champ casse la compilation ici avant de casser un écran là-bas. | Écrire les types à la main (dérive garantie). |
| Conformité | **openapi-diff 0.24** en CI : spec servie ⊇ contrat | Toute opération du contrat absente ou dont la forme diverge fait échouer la CI. Le tableau de couverture (§11) se lit dans le rapport. | Tests manuels. |
| Documentation | **@scalar/fastify-api-reference** sur `/v1/docs` (hors prod) | Lisible, cherchable, joue les requêtes. | Swagger UI. |
| Sécurité HTTP | `@fastify/helmet` 13, `@fastify/cors` 11, `@fastify/rate-limit` 11 (Valkey), `@fastify/under-pressure` 9 | Standards. La limitation est par clé : jeton, clé d'API ou IP. | — |
| Client HTTP amont | **undici 8** (`request` + `Agent` avec pool) | Le client de Node, keep-alive, timeouts fins. | got/ky/ofetch : surcouche inutile. |
| Résilience amont | **cockatiel 4** (retry, disjoncteur, délai) | Un disjoncteur par intégration ; c'est lui qui produit le `424`. | p-retry seul (pas de disjoncteur). |

### 3.3 Données

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Base | **PostgreSQL 18** | `uuidv7()` natif, E/S asynchrones, partitionnement mûr pour la métrologie. | MariaDB (héritage Blesta, sans objet). |
| ORM | **Drizzle ORM 0.45** + **drizzle-kit 0.31** | SQL typé sans magie, migrations générées et relues, support des politiques RLS dans le schéma (`pgPolicy`). | **Prisma 8** (encore en RC ce jour, moteur lourd, RLS pénible). **Kysely** : excellent, mais sans migrations générées. |
| Pilote | **postgres.js 3.4** | Rapide, pipelining, un seul objet de connexion. | node-postgres : bien, plus lent. |
| Identifiants | **UUID v7** (`uuid` 14 / `uuidv7()`) | Triables, sans coordination, index B-tree heureux. Le contrat ne contraint pas la forme des `id`. | ULID (moins standard en base). |
| Cache, verrous, limitation | **Valkey 8** + **ioredis 6** | Compatible Redis, licence BSD. Verrous de provisioning (`SET NX PX`), limitation, cache des lectures amont, pub/sub des événements. | Redis 7 (licence). |
| Recherche | **Postgres FTS + `pg_trgm`** | `GET /recherche` cherche des noms de ressources et des tickets, pas des documents : pas besoin d'un moteur. | Meilisearch, Elasticsearch. |
| Métrologie | **Tables partitionnées par mois** (`usage_horaire`) | Volume : ~50 métriques × ~5 000 ressources × 720 h/mois ≈ 180 M lignes/mois au plus. Partition mensuelle + agrégats journaliers matérialisés suffisent. | TimescaleDB (licence, dépendance d'extension). |
| Secrets en base | **AES-256-GCM** clé d'enveloppe (`node:crypto`), clé maître via variable d'environnement puis **Barbican** | Mots de passe de bases, clés S3, jetons amont. Rotation possible par version de clé. | Vault (une pièce de plus à exploiter). |

### 3.4 Opérations longues

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Orchestration | **Temporal 1.23** (`@temporalio/client`, `worker`, `workflow`, `testing`), serveur auto-hébergé, persistance Postgres | Le contrat décrit *exactement* un workflow durable : `TravailProvisioning` avec `taches[]` ordonnées, `statut ∈ {queued, running, done, failed, rolled_back}`, `erreur.suggestion`, `POST /travaux/{id}/relance` (reprise **à l'étape échouée**), `POST /travaux/{id}/annulation`. En Temporal : workflow = travail, activité = tâche, `try/catch` + compensations = rollback, signal = relance, `cancel` = annulation, requête = lecture des tâches. Tout ça est garanti au redémarrage d'un worker. | **BullMQ 6** : parfait pour « envoyer un mail », insuffisant pour une saga de 9 étapes avec compensation ; il faudrait réécrire la machine à états. **pg-boss / graphile-worker** : mêmes limites. |
| Catalogue | Les **41 identifiants** de `src/lib/mock/workflows.ts` (`vm.create`, `espace.create`, `k8s.upgrade`, `dr.failover.real`, `web.ssl.renew`…) deviennent les noms des workflows Temporal | Le frontend affiche les étapes du catalogue ; le backend remonte les mêmes noms d'étapes. Une seule table `travaux` miroir (projection) pour `GET /travaux` sans interroger Temporal à chaque liste. | Inventer une nomenclature. |
| Planification | **Temporal Schedules** | Cycle de facturation, sauvegardes planifiées, réindexations, renouvellements ACME, relances. Une seule horloge, visible dans l'UI Temporal. | node-cron (perd la main au redémarrage). |

### 3.5 Identité et accès

| Sujet | Choix | Pourquoi | Écarté |
|---|---|---|---|
| Mots de passe | **argon2** 0.45 (argon2id) | Référence. | bcrypt. |
| MFA | **otpauth** 9.5 (TOTP), **@simplewebauthn/server** (phase 2, clés de sécurité) | Le contrat : `POST /auth/mfa`, `POST/DELETE /moi/mfa`. | — |
| Jetons | **jose** 6 : JWT signés EdDSA (Ed25519), JWKS publié, jeton d'accès 15 min + rafraîchissement opaque en base (rotation, révocation par session) | `GET /moi/sessions`, `DELETE /securite/sessions/{id}` exigent des sessions révocables : le rafraîchissement est une ligne en base, l'accès reste sans état. | @fastify/jwt (moins de contrôle). |
| Fédération amont (le client se connecte avec son IdP) | **openid-client 6.8** (OIDC), **@node-saml/node-saml 5.1** (SAML 2.0) | `GET /securite/sso`, `PUT`, `POST /securite/sso/test`, `GET /auth/sso/decouverte` (par domaine de courriel), `POST /auth/sso/callback`. Une configuration SSO par organisation. LDAP : phase ultérieure via `ldapts`. | Keycloak comme IdP : il apporte fédération et SSO gratuitement, mais la séquence `connexion → mfa` du contrat s'accorde mal au *direct grant*, et il faudrait synchroniser deux annuaires. On garde la porte ouverte (§12). |
| Fournisseur OIDC aval (les services managés se connectent avec Synelia) | **oidc-provider 9.12** (panva, certifié OpenID) | `PUT /services/{id}/sso` avec `clientId` et `groupMappings` : Nextcloud, Odoo, GitLab, Metabase… deviennent des clients OIDC de notre fournisseur. `POST /services/{id}/ouverture` = URL de connexion à usage unique. | Un Keycloak « aval » séparé. |
| Clés d'API | Préfixe lisible + secret hashé (SHA-256), portée = sous-ensemble d'actions RBAC du rôle émetteur | `X-Api-Key`, `/securite/cles-api`, rotation. | — |
| Autorisation | **Matrice RBAC copiée** de `rbac.ts`, évaluée par `(rôle, action, portée)` avec les `Membership.scopeType ∈ {org, espace, application, service}` | Un `espace_admin` d'un Espace n'a pas le rôle sur un autre Espace. La lecture seule (`◐`) autorise les `GET` de la ressource, pas les mutations. | Casbin/OPA : la matrice tient en 38 lignes. |

### 3.6 OpenStack

Il n'existe **pas de SDK Node maintenu** : `pkgcloud` (2.2, abandonné), `js-openstack-lib`
(retiré par OpenStack), `node-openstack-wrapper` (GoDaddy, inactif). On écrit le nôtre,
et c'est une bonne nouvelle : on ne dépend d'aucune abstraction d'autrui sur le cœur du
produit.

`packages/openstack/` :

| Composant | Contenu |
|---|---|
| `keystone.ts` | Auth v3 par *application credential* (jamais mot de passe admin en production), scoping projet/domaine, catalogue, rafraîchissement 60 s avant expiration, création de domaines/projets/utilisateurs/*application credentials*/quotas (service admin). |
| `nova.ts` | Microversion **épinglée** (celle relevée dans le lab, ≥ 2.96 ; jamais `latest`), serveurs (create, detail, actions, resize/confirm, snapshot, console URL, live-migration, interfaces), flavors, keypairs, quotas par projet, `os-simple-tenant-usage`. |
| `neutron.ts` | Réseaux, sous-réseaux, routeurs, ports, IP flottantes, groupes de sécurité et règles, quotas, VPNaaS (IPsec). |
| `cinder.ts` | v3, microversion **épinglée** de même : volumes, types, attachements, extension, snapshots, **backups** (source des points de restauration), quotas. |
| `glance.ts` | Images (catalogue `/catalogue/images`), propriétés `os_distro`, visibilité, taille. |
| `magnum.ts` | Templates et clusters (driver Cluster API Helm), redimensionnement de pools, mise à niveau, kubeconfig (`/certificates`). |
| `octavia.ts` | Load balancers, listeners, pools, membres, health monitors, politiques L7, stats. |
| `designate.ts` | Zones, recordsets, DNSSEC, exports ; `zone-applicative` et DNS-01 ACME. |
| `barbican.ts` | Secrets et conteneurs (certificats TLS des listeners Octavia, clés BYOK). |
| `trove.ts` | Instances, datastores, utilisateurs/bases, sauvegardes, réplicas (à confirmer dans le lab, §12). |
| `rgw.ts` | Ceph RGW **Admin Ops API** (utilisateurs, clés, quotas, usage) signé SigV4 (`aws4`), et **S3** via `@aws-sdk/client-s3` 3.1125 (buckets, versioning, object lock, politiques, journaux). |
| `notifications.ts` | Consommateur **oslo.messaging** (RabbitMQ, `amqplib` 2) des notifications `compute.instance.*`, `volume.*`, `port.*` : c'est la source *exacte* des durées facturables et des événements. |

Chaque client : `undici` + `cockatiel`, `X-Correlation-Id` propagé, erreurs OpenStack
traduites en `AppError` (`quota_depasse` ← 403 `OverQuota`, `nom_deja_pris` ← 409, …),
tests sur fixtures JSON **enregistrées depuis le lab**, jamais inventées. Les types sont
générés depuis les spécifications OpenAPI produites par `openstack/codegenerator` quand
elles existent (Nova, Neutron, Cinder, Glance, Keystone, Octavia), écrits à la main sinon.

Le lab est joignable **depuis dev01 uniquement** (VIP `192.168.26.234`, HTTP clair, catalogue
qui annonce la VIP). Le développement se fait avec le tunnel SSH décrit dans le fichier `admin-openrc` du lab (hors dépôt),
et la variable `OS_ENDPOINT_OVERRIDES` (JSON `{ compute: "http://127.0.0.1:8774/v2.1", … }`)
permet de forcer les URL de service quand le catalogue ment. En production, TLS externe
activé sur kolla est un **prérequis**, pas une option.

### 3.7 Kubernetes et plateforme applicative

| Sujet | Choix | Pourquoi |
|---|---|---|
| Client | **@kubernetes/client-node 2.0** | Client officiel, maintenu par le projet Kubernetes. |
| Livraison | **Argo CD** (API REST, instance existante `argocd.k8s.abj.smile.ci` pour l'exploitation ; une instance dédiée pour la plateforme client) + dépôt GitOps `synelia-cloud-gitops` écrit par le backend | Un déploiement = un commit + une `Application` Argo. L'état voulu est relisible et auditable. |
| Stratégies | **Argo Rollouts** | `strategie ∈ {rolling, canari, blue_green}`, `canari.pct/seuil5xx/fenetreS` du contrat = un `Rollout` avec analyse VictoriaMetrics. |
| Construction | **BuildKit** (`buildkitd` en pod) + **Nixpacks** ou Dockerfile → **Harbor** (registre par organisation, scan **Trivy** intégré = `findings[]` du contrat) | `builder ∈ {nixpacks, dockerfile, image}`. |
| Entrée | **Envoy Gateway** (Gateway API) + certificat wildcard `*.apps.synelia.cloud` (ACME DNS-01 Designate) | `zone-applicative`, `domaines-applicatifs`, redirections, `routage`. |
| Bases des projets | Opérateurs : **CloudNativePG**, **MariaDB Operator**, **Percona Operator for MongoDB**, **OT Redis Operator**, **Altinity ClickHouse Operator** | `MoteurBase` du contrat couvert au complet ; `hoteInterne` = service ClusterIP, sans exposition. |
| Clusters clients | **Magnum + magnum-capi-helm** (Cluster API sur un cluster de gestion) | Chemin officiel Gazpacho ; `pools`, `autoscale`, `modules` (CNI, ingress, monitoring, cert-manager) sont des valeurs Helm du driver. |
| Cible `vm` des applications | Phase tardive : un agent Docker Compose sur VM Nova (`cloud-init`) piloté par Temporal | Le contrat le prévoit (`cible: 'vm'`, `emplacement.vms`), la valeur immédiate est faible. |

### 3.8 Web Cloud et services managés

| Produit du contrat | Solution amont | Intégration |
|---|---|---|
| Emails (`/web/emails`, boîtes, alias, SPF/DKIM/DMARC) | **Stalwart** (Rust, IMAP/JMAP/SMTP/CalDAV, multi-tenant natif, quotas par tenant) | API de gestion (JMAP admin depuis v0.16, REST avant). Un *tenant* Stalwart par organisation, un domaine par messagerie. DKIM publié via Designate. Ouverture SSO vers son webmail. |
| Relais SMTP (`/web/smtp`, clés, messages, webhooks, test) | **Postal** | API HTTP + webhooks : `cles` = *credentials*, `messages` = journal de livraison, `webhooks` = natifs. Correspondance quasi 1:1. |
| Drive (`/web/drive`, sièges, ouverture) | **Nextcloud** (mutualisé par groupe d'organisations ou dédié) | API OCS Provisioning (utilisateurs, groupes, quotas), *external storage* S3 RGW, SSO par notre `oidc-provider`. |
| Domaines (`/web/domaines`, disponibilité, transfert, code auth, renouvellement) | **Interface `Registrar`** ; premier adaptateur **OpenProvider** (gTLD, nombreux ccTLD) ; **.ci via NIC.CI** en accréditation directe (§12) | Le backend ne parle jamais EPP directement en phase 1. |
| DNS (`/web/dns`) | **Designate** | Zones par organisation, modèles (`/web/dns/modeles`) appliqués côté backend. |
| SSL (`/web/ssl`) | **acme-client 5.4** (Let's Encrypt / ZeroSSL, DNS-01 sur Designate, HTTP-01 sinon) ; OV/EV via revendeur en phase ultérieure | Renouvellement par Temporal Schedule 30 jours avant. Certificats stockés dans Barbican. |
| Hébergement mutualisé (`/web/hebergements`, PHP, FTP/SFTP, cron, bases, sites WordPress/PrestaShop avec préproduction, mises à jour, analyse de sécurité) | **Interface `PanneauHebergement`** ; adaptateur **Plesk** (REST + WP Toolkit) recommandé, **HestiaCP** en repli OSS | Voir §12 : c'est la décision la plus structurante restant à prendre. Le contrat (staging WordPress, extensions PHP, scan malware) correspond trait pour trait à Plesk. |
| Sauvegarde Web (`/web/backup`) | Sauvegardes du panneau vers S3 RGW (object lock) + tests de restauration Temporal | Unifiées dans `points_restauration`. |
| Services managés (`/services`, catalogue de 13 slugs) | **Charts Helm sur la plateforme Kubernetes**, un espace de noms par instance dédiée, instances mutualisées avec tenant applicatif | Slugs → solutions du mock : `drive-pro`→Nextcloud, `email-pro`→Grommunio (à discuter : Stalwart sert déjà les emails Web Cloud), `visio`→Jitsi Meet + Rocket.Chat, `ged`→Mayan EDMS, `erp`→Odoo Community, `crm`→EspoCRM, `wordpress`, `prestashop`, `bi`→Metabase, `forge`→GitLab CE, `coffre`→Vaultwarden, `automatisation`→n8n, `analytics-web`→Matomo. Chaque solution a un **`ConnecteurService`** : `provisionner`, `configurer(parametres)`, `sieges`, `sso`, `versions`, `exporter`, `metriques`, `urlOuverture`. Les `parametres` viennent des 13 fichiers `src/lib/configurations/*.ts` du frontend, copiés dans `packages/catalogue/`. |

### 3.9 Commerce

| Sujet | Choix | Pourquoi |
|---|---|---|
| Métrologie | Notifications oslo (durées exactes) + relevé horaire (`scheduler`) Nova/Cinder/Neutron/Octavia/RGW/Magnum/Trove/Kubernetes → `usage_horaire` | Deux sources se recoupent : la notification donne l'instant, le relevé rattrape ce qui a été manqué. |
| Tarification | Moteur natif : `offres` (catalogue admin), `grille_tarifaire` (prix unitaire par métrique, site, palier, date d'effet), `estimer()` partagé par `/facturation/estimation`, `/modeles/{slug}/estimation`, `/public/simulateur` | CloudKitty écarté : il ne connaît ni les services managés, ni le Web Cloud, ni les sièges. |
| Facturation | Cycle mensuel (`POST /admin/facturation/cycle`, Temporal Schedule le 1er à 02:00 UTC) : agrégation → lignes → facture `brouillon` → numérotation séquentielle par année (`SYN-2026-000123`, verrou transactionnel) → `emise` → PDF | Numérotation continue et sans trou : exigence comptable. |
| PDF | **@react-pdf/renderer 4.9** | Déclaratif, sans navigateur, polices embarquées, rapide en lot. Playwright écarté (Chromium par facture). |
| Taxes | TVA 18 % (Côte d'Ivoire) par défaut, exonérations par organisation (`tva` du contrat), mentions légales par pays | **FNE (facture normalisée électronique, DGI)** : obligation en cours de déploiement en Côte d'Ivoire — à instruire (§12), prévue comme *post-traitement* de l'émission. |
| Paiements | **CinetPay** (Wave, Orange Money, MTN MoMo, cartes locales ; webhook de notification + vérification `/v2/payment/check`), **Stripe 22** (cartes EUR/USD, `PaymentIntent`, webhooks signés), **virement** (rapprochement manuel côté admin), **prépayé** (grand livre) | `MoyenPaiement` du contrat couvert au complet. Chaque fournisseur derrière `PasserellePaiement` ; tout webhook est idempotent par `evenement_id`. |
| Porte-monnaie | **Grand livre à double entrée** (`ecritures`, débit/crédit, solde = somme, jamais une colonne) | Rechargement, consommation, avoir SLA, remboursement : auditables. |
| Relances | Temporal Schedule quotidien : J+1, J+7, J+15, suspension à J+30 (configurable), notification email/WhatsApp | `POST /admin/facturation/impayes/relances`. |
| Devis | `devis` avec lignes, validité, acceptation → souscription + workflow `devis.accept` | Contrat : `/facturation/devis`, `/public/devis`. |
| SLA | Calcul mensuel de disponibilité par ressource depuis VictoriaMetrics ; réclamations → avoir au grand livre | `/facturation/sla`, `/facturation/sla/reclamations`. |

### 3.10 Transversal

| Sujet | Choix |
|---|---|
| Journalisation | **pino 10** (JSON, `correlationId`, `orgId`, `userId`, jamais de secret : liste de champs masqués), `pino-pretty` en dev. Expédition vers VictoriaLogs. |
| Traces et métriques | **@opentelemetry/sdk-node 0.222** + `@fastify/otel` + auto-instrumentations (pg, undici, ioredis) → VictoriaTraces ; **prom-client 15** → VictoriaMetrics (`/metrics` interne). |
| Notifications | Email transactionnel via **Postal** (notre relais) avec gabarits **@react-email/components** ; SMS via API Orange CI ; WhatsApp via **WAHA** (`bot.labs.synelia.tech`, déjà en place) ; webhooks signés HMAC. Canaux du contrat `email | sms | whatsapp | webhook` couverts. |
| Fichiers | Pièces de tickets et exports vers S3 RGW, URL présignées. Le contrat téléverse en base64 JSON (`POST /support/pieces`), limité à 10 Mo. |
| Copilote (`POST /copilote`, suggestions) | Anthropic SDK, modèle Sonnet 5 ; outils = lectures du plan de contrôle uniquement, jamais de mutation. |
| Configuration | **@t3-oss/env-core** + Zod : toute variable déclarée, typée, validée au démarrage. |
| Tests | **vitest 5** ; **testcontainers 12** (`@testcontainers/postgresql`, Valkey, `temporalio/auto-setup`) ; `fastify.inject` ; **nock 14** pour les amont ; `@temporalio/testing` (horloge accélérée) pour les workflows ; validation de chaque réponse de test contre le schéma du contrat (`ajv` 8). |
| CI | GitHub Actions : Biome → typecheck (tsgo) → vitest → build → **openapi-diff** contre `packages/contract/openapi.json` → image Docker. Secret scanning activé. |
| Déploiement | Image unique, **Dokploy** (déjà utilisé, `paas.fleetops.services`) pour l'API, le worker, le scheduler, Postgres, Valkey, Temporal. Migration vers la plateforme Kubernetes en Phase 7 quand elle existe. |

---

## 4. Structure du dépôt

Monorepo pnpm. `blesta/` et `middleware/` sont supprimés en Phase 0 : le premier n'a
plus d'objet, le second est absorbé (son client Keystone/Nova sert de graine à
`packages/openstack`).

```
synelia-cloud-backend/
├── package.json                    # pnpm workspaces, scripts racine
├── pnpm-workspace.yaml
├── tsconfig.base.json              # strict, ES2024, NodeNext, verbatimModuleSyntax
├── biome.json
├── docker-compose.yml              # dev : postgres, valkey, temporal, temporal-ui, mailpit, minio
├── docker-compose.dokploy.yml      # déploiement Dokploy (api, worker, scheduler + dépendances)
├── Dockerfile                      # image unique, cible node:24-alpine
├── .github/workflows/ci.yml
├── docs/
│   ├── PLAN-DIRECTEUR.md           # ce document
│   ├── ADR/                        # une décision par fichier quand elle change
│   └── runbooks/                   # tunnel lab, rotation de clés, cycle de facturation
│
├── apps/
│   ├── api/                        # processus HTTP
│   │   └── src/
│   │       ├── main.ts             # `api | worker | scheduler` selon argv
│   │       ├── app.ts              # fabrique Fastify : plugins, hooks, modules
│   │       ├── plugins/            # correlation, auth, tenant, rbac, erreurs, pagination, swagger
│   │       └── modules/            # UN dossier par domaine du contrat (voir gabarit ci-dessous)
│   ├── worker/                     # workers Temporal : enregistre workflows + activités des modules
│   └── scheduler/                  # déclare les Temporal Schedules (idempotent au démarrage)
│
├── packages/
│   ├── contract/                   # openapi.json copié du frontend + types générés + rbac.ts copié
│   │   ├── openapi.json
│   │   ├── types.d.ts              # openapi-typescript
│   │   ├── rbac.ts                 # matrice, identique à src/lib/rbac.ts (vérifié en CI)
│   │   └── workflows.ts            # les 41 identifiants de travaux et leurs étapes
│   ├── catalogue/                  # configurations des 13 services managés (copie de src/lib/configurations)
│   ├── db/                         # schéma Drizzle, migrations, politiques RLS, seeds
│   │   ├── schema/<domaine>.ts
│   │   ├── migrations/
│   │   └── rls.ts
│   ├── kernel/                     # AppError, Result, ids, argent, dates, chiffrement, logger, config
│   ├── openstack/                  # §3.6
│   ├── k8s/                        # client-node, Argo CD, Rollouts, Harbor, BuildKit
│   ├── connecteurs/
│   │   ├── stalwart/  postal/  nextcloud/  plesk/  hestiacp/  registrar-openprovider/  acme/
│   │   ├── cinetpay/  stripe/
│   │   ├── victoria/  centreon/  waha/  orange-sms/
│   │   └── services/               # ConnecteurService × 13 slugs (Helm + API de chaque solution)
│   └── testing/                    # conteneurs, fixtures amont enregistrées, fabriques
│
└── tools/
    ├── contrat-sync.mjs            # copie openapi.json + rbac.ts + configurations depuis ../synelia-cloud
    ├── contrat-diff.mjs            # openapi-diff : servie ⊇ contrat, rapport de couverture
    └── enregistrer-fixtures.mjs    # capture des réponses du lab (via tunnel) pour les tests
```

### Gabarit d'un module (`apps/api/src/modules/vms/`)

```
vms/
├── index.ts          # plugin Fastify : enregistre routes + expose le service au conteneur
├── routes.ts         # une fonction par opération du contrat, nommée par operationId (creerVm, listerVms…)
├── schemas.ts        # Zod : corps, réponses, paramètres — noms du contrat
├── service.ts        # cas d'usage : règles métier, quotas, estimation, démarrage des travaux
├── repo.ts           # Drizzle : requêtes sur les tables du module, RLS respectée
├── mappers.ts        # amont → contrat (Nova server → VM), jamais l'inverse
├── workflows.ts      # workflows Temporal du module (vm.create, vm.resize, vm.snapshot…)
├── activities.ts     # activités : idempotentes, un appel amont chacune, correlationId propagé
├── evenements.ts     # événements de domaine émis (vm.creee, vm.supprimee) → audit, métrologie, notifications
└── __tests__/
    ├── routes.test.ts         # contrat : chaque opération, chaque code de réponse déclaré
    ├── service.test.ts
    └── workflows.test.ts      # @temporalio/testing, activités simulées
```

Règles de dépendance, vérifiées par Biome (`noRestrictedImports`) :

- `modules/*` → `packages/*` : oui. `modules/a` → `modules/b/service.ts` : oui.
  `modules/a` → `modules/b/repo.ts` : **non**.
- `packages/connecteurs/*` et `packages/openstack` ne connaissent **ni** la base **ni** le
  contrat : ils parlent le langage de l'amont, les `mappers.ts` des modules traduisent.
- `packages/kernel` ne dépend de rien d'autre.

### Modules (un par domaine du contrat)

`auth` · `compte` · `organisations` · `membres` · `securite` · `audit` · `tableau-de-bord`
· `travaux` · `espaces` · `vms` · `kubernetes` · `reseau` (réseaux, IP, groupes de
sécurité, LB, VPN) · `stockage` (volumes, buckets, clés S3) · `bases` · `sauvegarde` ·
`pra` · `applications` (apps, environnements, composants, déploiements, dépôts, canvas) ·
`projets` (projets, services, domaines applicatifs, zone, routage) · `modeles` ·
`observabilite` · `services-manages` (catalogue, instances, sièges, SSO, versions,
exports) · `web-domaines` · `web-dns` · `web-hebergement` (hébergements, sites, bases,
comptes fichiers, tâches, services partagés) · `web-emails` · `web-drive` · `web-ssl` ·
`web-backup` · `web-smtp` · `facturation` · `support` · `docs` · `admin` (sous-modules
pilotage, clients, infrastructure, produit, finance, exploitation) · `public`.

---

## 5. Tenancy : organisation ↔ OpenStack

| Portail | Postgres | Keystone / OpenStack |
|---|---|---|
| `Organisation` | `organisations` | **Domaine Keystone** `org-<id>` (isolation des utilisateurs de service et des quotas domaine) |
| `EspaceCloud` (site, cidr, quota) | `espaces` | **Projet Keystone** dans le domaine, dans la **région** du site (`ABJ` = `RegionOne` aujourd'hui ; `GBM` = seconde région quand elle existera) ; réseau Neutron `cidr` + sous-réseau + routeur vers l'externe ; groupe de sécurité par défaut ; **quotas Nova/Cinder/Neutron** = `quota` du contrat ; *application credential* du projet chiffrée en base |
| `Membership` | `memberships` | Aucun utilisateur Keystone par personne : le backend agit avec l'*application credential* du projet, l'humain n'a jamais de compte OpenStack |
| `Backend` (admin) | `backends` | Une entrée par région/cloud ; `type: 'openstack'` seul implémenté, les autres types du contrat (`proxmox`, `vsphere`…) restent des lignes de catalogue sans connecteur |
| `Placement` (admin) | `placements` | Choix de la région/agrégat d'hôtes à la création |
| `Bucket` | `buckets` | Utilisateur RGW par organisation (`org-<id>`), buckets préfixés, clés S3 = sous-utilisateurs RGW |

Le compte de service admin du lab ne sert **qu'au
bootstrap** d'un domaine/projet ; tout le reste passe par des *application credentials*
à portée réduite, révocables une par une.

---

## 6. Modèle de données (tables principales)

Toutes les tables tenant portent `org_id uuid not null` + politique RLS
`org_id = current_setting('app.org_id')::uuid` ; les tables plateforme (`backends`,
`offres`, `grille_tarifaire`, `equipe`) n'ont pas d'`org_id`. Horodatage `cree_le`,
`modifie_le`, suppression logique `supprime_le` là où la facturation l'exige.

| Domaine | Tables |
|---|---|
| Identité | `utilisateurs` (email unique, argon2, mfa_secret chiffré, idp_source), `sessions` (rafraîchissement hashé, IP, UA, révocation), `invitations`, `memberships` (rôle, scope_type, scope_id), `cles_api` (préfixe, hash, portée[]), `sso_configurations` (par org : oidc/saml, métadonnées), `politiques_securite`, `preferences` |
| Organisations | `organisations`, `organisations_synthese` (vue matérialisée : espaces, utilisateurs, CA mensuel, vCPU) |
| Infra | `espaces`, `vms`, `vm_instantanes`, `volumes`, `reseaux`, `ips_publiques`, `groupes_securite`, `regles_securite`, `load_balancers` (+ `lb_listeners`, `lb_pool_membres`, `lb_regles_l7`), `vpn_tunnels`, `vpn_profils`, `k8s_clusters`, `k8s_pools`, `buckets`, `cles_s3`, `bases_managees`, `catalogue_gabarits`, `catalogue_images` (cache Glance enrichi : `os`, `famille`) |
| Travaux | `travaux` (projection : id = workflow id, type, label, statut, taches jsonb, erreur jsonb), `evenements_domaine` (outbox) |
| Protection | `plans_sauvegarde`, `points_restauration`, `restaurations`, `plans_pra`, `pra_groupes`, `pra_exercices` |
| PaaS | `applications`, `environnements`, `composants`, `variables` (chiffrées si secret), `deploiements`, `deploiement_etapes`, `deploiement_findings`, `projets`, `projet_services`, `domaines_applicatifs`, `zones_applicatives`, `depots_connexions` (jetons GitHub/GitLab chiffrés) |
| Services managés | `catalogue_services` (+ `paliers`, `versions`), `services_manages`, `sieges`, `services_exports`, `services_versions_historique` |
| Web Cloud | `web_domaines`, `dns_zones` (miroir Designate), `web_hebergements`, `web_sites`, `web_sites_maj`, `web_bases`, `web_bases_utilisateurs`, `web_comptes_fichiers`, `web_taches`, `web_services_partages`, `web_messageries`, `web_boites`, `web_alias`, `web_drives`, `web_certificats`, `web_sauvegardes`, `smtp_relais`, `smtp_cles`, `smtp_messages` (miroir Postal, rétention 30 j), `smtp_webhooks` |
| Commerce | `offres`, `familles_offres`, `grille_tarifaire`, `souscriptions`, `usage_horaire` (partitionnée), `usage_journalier`, `factures`, `facture_lignes`, `sequences_factures`, `paiements`, `paiement_evenements` (webhooks bruts, idempotence), `moyens_paiement` (jetons de fournisseur chiffrés), `ecritures` (grand livre), `devis`, `devis_lignes`, `sla_mesures`, `sla_reclamations`, `relances`, `cycles_facturation`, `marges` (vue) |
| Exploitation | `tickets`, `ticket_messages`, `ticket_pieces`, `base_connaissances`, `docs_sections`, `docs_parcours`, `docs_progression`, `bacs_a_sable`, `alertes_regles`, `anomalies`, `onboarding`, `statut_services`, `incidents`, `incident_maj`, `leads`, `equipe` (staff Synelia), `elevations`, `fenetres_patching`, `campagnes_migration`, `campagnes_marketplace`, `attestations`, `rapports_conformite`, `pages_legales`, `etudes_cas`, `datacenters` |
| Audit | `audit` (**append-only** : trigger qui interdit UPDATE/DELETE, hash chaîné `hash_precedent`), `audit_exports` |

---

## 7. Correspondance contrat ↔ OpenStack (extrait normatif)

| Opération | Appels |
|---|---|
| `POST /espaces` (202, `espace.create`) | Keystone : projet, quotas ; Neutron : réseau, sous-réseau (`cidr`), routeur, gateway, SG par défaut ; Designate : zone interne `<code>.int.synelia.cloud` si `dnsInterne` ; Keystone : application credential ; **compensation** en ordre inverse |
| `PUT /espaces/{id}/quota` | Nova `os-quota-sets`, Cinder `os-quota-sets`, Neutron `quotas` ; refus `402` si usage > nouveau quota |
| `GET /catalogue/gabarits` | Nova flavors (+ `extra_specs` pour `type: gpu/memory`), cache 10 min |
| `GET /catalogue/images` | Glance images publiques + `os_distro`, `os_version` ; cache 10 min |
| `POST /vms` (202, `vm.create`) | Estimation → réservation quota locale → Nova `POST /servers` (flavor, image ou `block_device_mapping_v2` pour disque Cinder, `networks`, `security_groups`, `key_name`, `user_data`, `metadata.synelia_*`) → attente `ACTIVE` (polling activité, heartbeat) → Cinder volumes additionnels + attach → IP flottante si demandée → Designate PTR → tag → `vm.creee` |
| `PATCH /vms/{id}` | Nova `PUT /servers/{id}` (name), `tags` |
| `PUT /vms/{id}/materiel` (202) | `hardware.*` du contrat : `nics` → Neutron ports + `os-interface` ; `secureBoot`, `vtpm`, `videoMo` → propriétés d'image/flavor (`hw_*`), exige arrêt ; `scsiControllers` → non porté par Nova : refus `422` documenté |
| `POST /vms/{id}/redimensionnement` (202, `vm.resize`) | Nova `resize` → `VERIFY_RESIZE` → `confirmResize` ; `revertResize` en compensation |
| `POST /vms/{id}/migration` (202, `vm.migrate`) | Nova `os-migrateLive` (admin) ; `site` cible = région : refus si ≠ région courante (pas de migration inter-région en v1) |
| `arret/demarrage/redemarrage` | `os-stop`, `os-start`, `reboot SOFT|HARD` |
| `POST /vms/{id}/console` | Nova `remote-consoles` (`novnc`) → URL à usage unique proxifiée |
| `instantanes` | Nova `createImage` (Glance) pour VM boot-from-image ; Cinder snapshot pour boot-from-volume ; restauration = rebuild/nouveau volume |
| `GET /vms/{id}/metriques` | VictoriaMetrics (libvirt exporter) → `Tuile[]`, `Serie[]` fenêtres 24h/7j/30j |
| `GET /vms/{id}/journaux` | Nova `os-getConsoleOutput` (20 lignes) + lien VictoriaLogs |
| `POST /vms/lot` (202, `vm.compose`) | Workflow enfant par VM, résultat agrégé |
| `/volumes` | Cinder v3 : `volume_type` ↔ `classe` (`nvme`, `ssd`, `hdd`, `archive` : **table de correspondance par région** en configuration), `encrypted` ↔ `chiffre`, `os-extend`, attach via Nova `os-volume_attachments` |
| `/buckets`, `/cles-s3` | RGW Admin Ops (utilisateur, sous-utilisateur, clés, quota) + S3 (bucket, versioning, object-lock, policy, logging, replication vers l'autre région) |
| `/reseaux`, `/ips`, `/groupes-securite` | Neutron ; `defaultPolicy.ingress: 'deny'` = pas de règle ; `antiDdos` = propriété de catalogue (hors OpenStack) |
| `/load-balancers` | Octavia v2 : LB (`vip_subnet_id`), listeners (TLS : certificat Barbican), pool (`lb_algorithm` ↔ `algo`, `session_persistence` ↔ `sticky`), membres, health monitor, L7 policies/rules ; `waf`, `rateLimit` = non portés par Octavia → `422` documenté ou couche Envoy en Phase 7 |
| `/vpn` type `ipsec` | Neutron VPNaaS : ike/ipsec policy, vpnservice, endpoint groups, site connection ; type `ssl` : VM appliance WireGuard (`cloud-init`), `profils` = paires de clés |
| `/kubernetes` | Magnum : cluster template (driver capi-helm, version), cluster (`master_count` ↔ `controlPlane`), `nodegroups` ↔ `pools` (`min/max` ↔ `autoscale`), `upgrade`, `/certificates` ↔ kubeconfig ; `modules` = valeurs Helm des addons |
| `/bases` | Trove (PG, MySQL, MariaDB, Redis) : instance dans le réseau de l'Espace, `replicas`, `backups`, `users` ; Mongo/ClickHouse = opérateurs k8s plateforme (§12) |
| `/sauvegarde` | Cinder backups (incrémentaux) vers RGW (object lock si `immutable`), Nova snapshots, sauvegardes applicatives des services ; `destinations.autre_site` = backup cross-région ; `chiffrement.byok` = clé Barbican du client |
| `/pra` | Réplication `planifie` = backups cross-région à cadence `rpoCibleMin` ; `continu` = **RBD mirroring Ceph** (prérequis infra, §12) ; bascule = workflow `dr.failover.*` par `groupes[].ordre` avec `ipRepli` |
| `/web/dns`, `zone-applicative`, ACME DNS-01 | Designate v2 |
| `/observabilite/*` | VictoriaMetrics (`/api/v1/query_range`), VictoriaLogs (`/select/logsql/query`, 20 lignes), vmalert + Alertmanager pour `alertes` ; événements = `evenements_domaine` + notifications oslo |
| `/admin/capacite`, `/admin/sites`, `/admin/backends` | Placement API (`resource_providers/{id}/inventories|usages`), Nova hypervisors, Cinder pools, agrégats ; projection `saturation.j30/j60/j90` par régression linéaire sur `usage_journalier` |
| `/admin/migration/campagnes` | Lots de `vm.migrate` (live-migration) ou de rebuild inter-backend, workflow `migration.lot` |

---

## 8. Facturation : du relevé à la facture

```
notifications oslo ──┐
                     ├──► usage_horaire (ressource, métrique, quantité, heure, org, espace, site)
relevé horaire ──────┘             │
                                   ▼  agrégation nocturne
                          usage_journalier ──► GET /facturation/consommation, /ventilation
                                   │
      grille_tarifaire ────────────┤  cycle mensuel (Temporal Schedule, 1er 02:00 UTC)
      souscriptions ───────────────┤
      sieges, services_manages ────┤
                                   ▼
                    factures (brouillon) ─► numérotation ─► emise ─► PDF ─► notification
                                   │
                          paiements (CinetPay, Stripe, virement, prépayé)
                                   │
                          ecritures (grand livre) ─► solde, avoirs SLA, relances
```

Règles :

- Une ressource facturée à l'heure l'est pour chaque heure **entamée** entre `cree_le` et
  `supprime_le` ; les périodes `SHUTOFF` sont facturées au tarif « arrêté » (stockage,
  IP) : la grille distingue `vm.vcpu.heure`, `vm.ram_go.heure`, `vm.arretee.heure`.
- `estimer()` et le cycle utilisent **le même** moteur : l'aperçu de coût ne peut pas
  mentir.
- Une facture émise ne change plus ; toute correction est un avoir.
- `admin/facturation/marges` = revenu par offre − coût de revient déclaré par
  `backends` (prix interne par vCPU/Go/To saisi par l'admin).

---

## 9. Sécurité

- Jamais de mot de passe admin OpenStack en production : *application credentials*,
  une par projet, rotation semestrielle par Temporal Schedule.
- Secrets d'exploitation (clés maîtres, jetons de fournisseurs) : variables
  d'environnement Dokploy en phase 1, Barbican ensuite. Aucun secret en base en clair,
  aucun dans les journaux (liste de masquage pino), aucun dans les réponses hors
  création/rotation.
- Audit append-only, hash chaîné, exports signés. Chaque refus RBAC est un événement.
- Jetons : accès 15 min EdDSA, rafraîchissement opaque rotatif, révocation par session,
  détection de réutilisation (famille de rafraîchissement).
- Emprunt d'identité (`POST /organisations/{id}/emprunt-identite`) : jeton marqué
  `emprunt: true`, 30 min, journalisé, bandeau côté frontend.
- Élévation (`/admin/equipe/{id}/elevation`) : rôle `super_admin` temporaire, motif
  obligatoire, expiration.
- Idempotence des mutations sensibles : en-tête `Idempotency-Key` stocké 24 h dans Valkey.
- Politiques de sécurité par organisation (`/securite/politiques`) : longueur de mot de
  passe, MFA obligatoire, durée de session, IP autorisées.
- Isolation en base par RLS **en plus** du filtre applicatif ; tests dédiés qui
  vérifient qu'une requête avec l'org A ne lit jamais l'org B.

---

## 10. Environnements

| Environnement | Où | OpenStack | Amont Web Cloud |
|---|---|---|---|
| Local | `docker-compose.yml` : Postgres 18, Valkey 8, Temporal (auto-setup) + UI, Mailpit, MinIO (S3) | Fixtures `nock` enregistrées, ou tunnel vers le lab depuis dev01 avec `OS_ENDPOINT_OVERRIDES` | Fixtures |
| CI | testcontainers | Fixtures | Fixtures |
| Bac à sable (`api.bac-a-sable.synelia.cloud`) | Dokploy | Lab Gazpacho, projets `sandbox-*` purgés chaque nuit | Instances de test |
| Production (`api.synelia.cloud`) | Dokploy puis Kubernetes plateforme | Régions ABJ (puis GBM), TLS externe, Ceph | Réels |

`tools/enregistrer-fixtures.mjs` capture les réponses réelles du lab (une fois, via le
tunnel) et les anonymise : les tests des clients OpenStack rejouent des réponses vraies.

---

## 11. Feuille de route

Onze phases. Chaque phase livre un **domaine complet du contrat**, branché sur le
frontend réel (variable `NEXT_PUBLIC_API_URL` côté synelia-cloud), avec ses tests, sa
métrologie et son audit. Les nombres d'opérations viennent du contrat. Les durées
supposent un développeur senior à temps plein assisté d'agents ; elles sont des ordres
de grandeur honnêtes, pas des engagements.

| # | Phase | Opérations | Contenu | Prérequis | Durée |
|---|---|---|---|---|---|
| 0 | **Socle** | 0 (+ `/healthz`, `/metrics`, `/v1/docs`) | Monorepo, Fastify, Zod, Drizzle + RLS, Temporal, Valkey, kernel (erreurs, correlation, pagination, argent, chiffrement), plugins auth/tenant/rbac, `contrat-sync`, `contrat-diff`, CI, Dockerfile, compose, suppression de `blesta/` et `middleware/` | — | 2 sem. |
| 1 | **Identité, organisations, travaux** | 61 + 4 | `auth` (connexion, MFA, inscription, invitations, mot de passe, rafraîchissement), `compte`, `organisations`, `membres`, `securite` (clés d'API, sessions, politiques ; SSO OIDC/SAML), `audit`, `travaux`, `rbac/matrice`, `referentiels`, `onboarding` | 0 | 4 sem. |
| 2 | **IaaS cœur** | Espaces 8, VMs 21, Stockage 18, Réseau 37 | `packages/openstack` (Keystone, Nova, Neutron, Cinder, Glance, RGW, Barbican), tenancy §5, workflows `espace.create`, `vm.*`, volumes, buckets, réseaux, IP, groupes de sécurité, LB (Octavia), VPN IPsec ; **estimation** et grille tarifaire minimale ; métrologie horaire ; fixtures du lab | 1, tunnel lab, TLS kolla pour la prod | 8 sem. |
| 3 | **Tableau de bord, observabilité, anomalies** | 9 + 9 | VictoriaMetrics/Logs → `Tuile/Serie/ExtraitLogs`, `LiensSortie` Centreon/Grafana, `alertes` (vmalert), `evenements`, `anomalies` + correctifs, `recherche`, réconciliateur amont ↔ base | 2 | 3 sem. |
| 4 | **Facturation et commerce** | 20 + admin finance 6 + admin catalogue 10 | Grille, souscriptions, cycle mensuel, factures, PDF, numérotation, TVA, CinetPay, Stripe, virement, prépayé (grand livre), devis, relances, SLA, ventilation, exports ; `admin/catalogue/*` (offres, familles, publication) | 2, comptes CinetPay/Stripe | 6 sem. |
| 5 | **Kubernetes, bases managées, DNS, SSL** | 13 + 10 + 11 + 8 | Magnum capi-helm (`k8s.create/upgrade/pool.roll`), kubeconfig, modules ; Trove (`bases`) ; Designate (`web/dns`, zone applicative) ; ACME (`web/ssl`, 8) | 2, driver capi installé dans le lab | 5 sem. |
| 6 | **Sauvegarde et PRA** | 21 | Plans, points, restaurations, conformité 3-2-1, vérifications ; PRA planifié (backups cross-région), exercices ; `admin/conformite/tests-restauration` | 2, RGW object lock, seconde région pour le repli réel | 4 sem. |
| 7 | **Plateforme applicative** | Applications 23, Projets 29, Déploiements 8, Modèles 3 | Cluster plateforme + Argo CD + Rollouts + Harbor/Trivy + BuildKit + Envoy Gateway + opérateurs de bases ; dépôt GitOps ; `app.deploy/rollback`, canari, promotion, approbation ; `projets/*/services` (application, base, statique, cron, worker) ; `domaines-applicatifs` (vérification DNS, certificats) ; `depots/branches` (GitHub/GitLab via `@octokit/rest` 22, `@gitbeaker/rest` 43) | 5 (k8s), 4 (estimation modèles) | 8 sem. |
| 8 | **Services managés** | 24 + admin marketplace 5 | Charts Helm des 13 solutions, `ConnecteurService` × 13, sièges, SSO via `oidc-provider`, versions/rollback, exports (réversibilité), configuration depuis `packages/catalogue` ; `admin/marketplace/*` | 7 | 8 sem. (≈ 3 j par solution + socle) |
| 9 | **Web Cloud** | Domaines 8, Hébergement 20, Sites 10, Bases 10, Emails 10, Drive 7, Backup 6, SMTP 14 | Registrar OpenProvider, Plesk (ou HestiaCP) derrière `PanneauHebergement`, Stalwart, Nextcloud, Postal, sauvegardes Web ; règle « un domaine, un serveur » | 5 (DNS, SSL), 8 (Nextcloud), décision §12 | 8 sem. |
| 10 | **Super admin, support, docs, vitrine** | Admin 36 (pilotage 5, infrastructure 11, exploitation 18, clients 2), Support 9, Docs 8, Public 18 | Santé, capacité (Placement API), sites, backends, placements, migration (campagnes), équipe et élévations, statut/incidents, tickets admin, leads, attestations, conformité ; tickets client, base de connaissances, pièces ; docs, parcours, bac à sable ; vitrine (offres, tarifs, simulateur, statut, pages légales, contact, devis, disponibilité de domaine) | 4, 6 | 5 sem. |
| 11 | **IA & Agents** | hors contrat | Étendre d'abord `outils/openapi/` côté frontend (passerelle, clés, routage, garde-fous, connaissances, inférence, agents, orchestration) ; puis passerelle (LiteLLM ou natif), vLLM sur GPU, `pgvector`, budgets. Pas avant que le contrat existe. | contrat frontend | à cadrer |

Total phases 0–10 : **environ 61 semaines calendaires brutes**, dont une part se
parallélise (4 pendant 3, 6 pendant 5, 9 pendant 8) : **10 à 12 mois** est l'ordre de
grandeur réaliste pour brancher les 514 opérations sur du réel.

**Définition de « fini » pour une phase** : toutes les opérations du domaine passent le
`contrat-diff` ; chaque code de réponse déclaré a un test ; chaque mutation écrit l'audit ;
chaque ressource facturable est relevée ; le frontend, pointé sur le bac à sable, passe
ses écrans du domaine sans mock ; un runbook existe pour ce que l'exploitant devra faire
à la main.

### Semaine 1, concrètement

1. `pnpm init` du monorepo, `packages/kernel`, `packages/contract` + `tools/contrat-sync.mjs`
   (copie `openapi.json`, `rbac.ts`, `configurations/` depuis un clone frère du frontend).
2. `apps/api` : Fastify + Zod + swagger + plugins `correlation`, `erreurs`, `pagination` ;
   `GET /healthz` ; `tools/contrat-diff.mjs` rouge à 0/514 — c'est le compteur qu'on fait
   monter.
3. `packages/db` : Postgres 18 via testcontainers, Drizzle, première migration
   (`organisations`, `utilisateurs`, `sessions`, `memberships`, `audit`), RLS activée et
   testée.
4. Temporal en compose, premier workflow `demo.echo` avec projection dans `travaux`,
   `GET /travaux/{id}` conforme.
5. Depuis dev01 : tunnel, `tools/enregistrer-fixtures.mjs` sur le lab (catalogue Keystone,
   flavors, images, un serveur, un volume, quotas). Ces fixtures dictent les types de
   `packages/openstack`.
6. CI verte : Biome, typecheck, vitest, build, diff de contrat, image.

---

## 12. À trancher (avec recommandation)

Chaque point change le travail à faire ; aucun ne bloque les phases 0 à 3.

1. **Hébergement mutualisé : Plesk ou HestiaCP ?** Le contrat (préproduction WordPress,
   mises à jour, analyse de sécurité, extensions PHP à la carte, comptes FTP/SFTP, cron,
   bases et utilisateurs) est *le* périmètre de Plesk + WP Toolkit, avec une API REST
   solide. HestiaCP est libre mais son API est mince et mono-serveur. **Recommandation :
   Plesk Web Host Edition**, une licence par VM d'hébergement, derrière
   `PanneauHebergement` pour ne pas se lier. Coût de licence à intégrer au palier.
2. **Bases managées : Trove ou opérateurs Kubernetes ?** Trove vit dans le réseau de
   l'Espace (isolation gratuite) mais ne couvre pas Mongo ni ClickHouse et sa communauté
   est réduite. Les opérateurs (CNPG, MariaDB, Percona, Redis, Altinity) sont excellents
   mais tournent sur la plateforme, hors du réseau du client : il faut une exposition
   (Octavia vers le cluster, ou Multus vers le réseau Neutron). **Recommandation : Trove
   en Phase 5 pour PG/MySQL/MariaDB/Redis, opérateurs en Phase 7 pour Mongo/ClickHouse
   et pour les bases des projets applicatifs**, puis convergence quand l'exposition
   réseau est réglée. À vérifier : Trove est-il déployé dans le lab ?
3. **Registrar .ci.** OpenProvider couvre les gTLD ; pour `.ci`, soit un revendeur qui
   le propose, soit une **accréditation NIC.CI** (démarche administrative, EPP ou
   interface propre : à instruire avec NIC.CI). Recommandation : démarrer l'accréditation
   dès la Phase 4, en parallèle du code.
4. **FNE (facture normalisée électronique, DGI Côte d'Ivoire).** Si l'obligation
   s'applique à Synelia à la date de mise en production, l'émission d'une facture devra
   passer par la plateforme de la DGI (numéro et QR code normalisés). Recommandation :
   instruire avec l'expert-comptable pendant la Phase 4 ; le modèle prévoit un
   post-traitement d'émission.
5. **Seconde région (Grand-Bassam).** Le contrat expose `Site ∈ {ABJ, GBM}` partout ;
   le lab n'a qu'une région. Le PRA « réel » et la réplication d'objets exigent la
   seconde. Recommandation : un `Backend` GBM en `maintenance` dans le catalogue admin
   jusqu'à ce qu'il existe ; le frontend l'affiche honnêtement.
6. **PRA en mode `continu`.** Exige le RBD mirroring Ceph entre sites, hors du
   backend. Recommandation : `planifie` seul en Phase 6, `continu` refusé avec `422`
   et message explicite jusqu'à la mise en place infra.
7. **`email-pro` (Grommunio) vs Web Cloud emails (Stalwart).** Deux serveurs de mail
   pour deux produits est une charge inutile. Recommandation : **Stalwart pour les deux**
   (il fait IMAP/JMAP/CalDAV/CardDAV) ; Grommunio seulement si le client exige la
   compatibilité Exchange/ActiveSync.
8. **Keycloak en secours.** Si la fédération SSO (OIDC + SAML + LDAP) et le fournisseur
   OIDC aval prennent plus de 4 semaines en Phase 1, on bascule sur Keycloak 26
   (Organizations) derrière les mêmes routes. La décision se prend à la fin de la Phase 1,
   pas avant.
9. **Fournisseur de paiement.** CinetPay est l'agrégateur dominant (Wave, OM, MoMo,
   cartes) ; les comptes marchands (KYB) prennent des semaines : à ouvrir dès la Phase 2.
10. **Ce que le lab a vraiment.** Le catalogue confirme Keystone, Nova, Neutron, Cinder,
    Glance, Magnum, Octavia, Designate. À vérifier depuis dev01 avec
    `openstack service list` : Trove, Barbican, Placement, Ceilometer/RabbitMQ pour les
    notifications, Ceph RGW (ou Swift) pour l'objet, le driver Magnum (capi-helm ou
    heat), la version de microversion Nova maximale.

---

## 13. Ce que ce plan refuse

- **Microservices** : une API, un modèle, un audit ; les modules suffisent.
- **Un ORM « magique »** ou un générateur de CRUD : le contrat a 218 schémas précis, chaque
  route est écrite et testée.
- **Réimplémenter un produit amont** (webmail, explorateur de fichiers, ERP) : le backend
  provisionne, configure, ouvre la porte (`/ouverture`), et s'arrête là — comme le
  frontend.
- **Servir des données inventées** : quand l'amont ne répond pas, c'est un `424` daté ;
  quand une fonction n'est pas portée par l'amont (`scsiControllers`, `waf` Octavia,
  PRA `continu`), c'est un `422` qui dit pourquoi, jamais un `200` creux.
- **Toucher au frontend depuis ce dépôt** : les évolutions de contrat (Phase 11, écarts
  découverts) passent par `outils/openapi/` côté synelia-cloud, puis `contrat:sync` ici.
