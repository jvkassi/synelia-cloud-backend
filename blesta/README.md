# blesta

Blesta 6.0.1, built from source (see `Dockerfile`) and deployed on
[Dokploy](https://dokploy.com) as part of the stack in `../docker-compose.yml`
(alongside a `mariadb` container and `../middleware`).

## What's persistent vs. ephemeral

Unlike a serverless/Vercel-style deployment, Dokploy runs this as a normal
long-lived container on a real Docker host, so there's no ephemeral-disk
problem to work around:

- **Persistent** (Docker named volume `blesta-data`, mounted at
  `/opt/blesta/data`): `config/` (the DB credentials + install state
  written once by the installer wizard), `cache/`, `sessions/`. Survives
  container restarts and redeploys.
- **Persistent** (separate volume, `mariadb-data`): the actual database.
- **Not yet wired to the volume**: `uploads/` and `logs/` directories exist
  under `/opt/blesta/data/` but Blesta doesn't use them until you point it
  there — see the one-time manual step below. Until then they default to
  paths inside the container's own writable layer, which *do* survive a
  restart of the same container but are lost on a rebuild/redeploy.

## One-time manual setup (you have to do this — it's an interactive web wizard)

1. Once deployed, visit the app's URL and complete Blesta's install wizard:
   database step should show already-connected (host `mariadb`, the
   `blesta`/`MARIADB_BLESTA_PASSWORD` credentials), then create the admin
   account. Choosing **"Start a 30-day free trial"** when asked for a
   license key requires no account or card.
2. Log in as admin, go to **Settings -> System -> General -> Basic Setup**
   and set:
   - **Uploads Directory** -> `/opt/blesta/data/uploads/`
   - **Log Directory** -> `/opt/blesta/data/logs/`
   - Check **"My installation is behind a proxy or load balancer"** (Dokploy
     terminates TLS via Traefik in front of this container).
3. Under **Settings -> Company -> Emails -> Mail Settings**, configure an
   external SMTP provider — this container doesn't run a local MTA.
4. Create a staff API-access user (**Staff -> Manage -> API Access**) and
   put its username/API key into `middleware`'s `BLESTA_API_USER` /
   `BLESTA_API_KEY`.

## Extending with custom modules/plugins

`plugins/` and `modules/` in this directory are copied into the image at
build time (`/opt/blesta/blesta/plugins` and
`/opt/blesta/blesta/components/modules`) — this is where the Synelia <->
OpenStack provisioning module will live once it's built, versioned with
the rest of this repo rather than hand-edited inside a container.
