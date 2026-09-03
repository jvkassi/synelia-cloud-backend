# synelia-cloud-backend

Real backend stack for [synelia-cloud](https://github.com/jvkassi/synelia-cloud) (currently a mock-only
Next.js frontend).

**Live:** Blesta is installed and running at
https://synelia-blesta-94b350-51-68-240-164.sslip.io/admin/login/ (a
Dokploy-generated sslip.io domain — a real custom domain can replace it
any time via `domain.create` / the Dokploy dashboard). A few post-install
settings are still manual — see `blesta/README.md`.

Target architecture:

```
synelia-cloud (frontend) -> middleware/ (this repo) -> Blesta (billing/provisioning) -> OpenStack (infra)
```

## Layout

- `blesta/` — Blesta billing/client-management core, containerized, deployed on
  [Dokploy](https://dokploy.com) (self-hosted PaaS). See `blesta/README.md`.
- `middleware/` — REST API service matching `synelia-cloud`'s existing contract
  (`docs/api/openapi.json` / `src/lib/types.ts` in that repo). Calls Blesta's API for
  anything it already models (clients, invoices, services); calls a `provisioner`
  interface for actual infra — a real OpenStack (Nova/Cinder) implementation against
  a lab tenant, not a mock. See `middleware/README.md`.
- `docker-compose.yml` — the whole stack (blesta, mariadb, middleware) deployed
  together as one Dokploy compose application.

## Why Dokploy instead of Vercel

Vercel's Dockerfile-based Container Images feature requires a permission/entitlement
that isn't enabled on the team's Hobby plan (confirmed by testing — the build silently
no-ops and serves a 404 instead of running the container). Rather than block on a plan
upgrade, Blesta runs on Dokploy, a self-hosted PaaS already available
(`https://paas.fleetops.services`), which also gives Blesta the persistent disk it wants
by default (uploads, sessions, generated invoices) — no ephemeral-filesystem workarounds
needed, unlike Vercel's serverless container model.

## Why a custom Blesta image instead of the community one

`ppmathis/docker-blesta` is a solid reference (informed the nginx/PHP-FPM layout here),
but Synelia will be writing its own Blesta module for OpenStack provisioning, so the
image is built from Blesta's own source with `blesta/plugins/` and `blesta/modules/`
as first-class extension points baked into the build — not something bolted onto
someone else's maintained image.
