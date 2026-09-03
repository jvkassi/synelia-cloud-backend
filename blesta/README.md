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

## Install status: done

The install wizard has been run (via Blesta's CLI installer,
`php index.php install` inside the container). Admin login is live;
first-run credentials were shared with the repo owner directly (not
committed here) — change the password on first login. A 30-day trial
license was requested automatically and is active (`license_key` in the
`settings` table starts with `trial-`).

### Redoing the install (FORCE_REINSTALL)

`docker/entrypoint.sh` has a gated one-time reinstall path: set
`FORCE_REINSTALL=1` plus `BLESTA_DOMAIN` / `BLESTA_ADMIN_PASSWORD` in
Dokploy's compose env and redeploy — it drops and recreates the `blesta`
database, clears `config/blesta.php`, and re-runs the CLI installer
end to end (DB creds → domain → license key → admin account, all
non-interactive). **This destroys all existing Blesta data** — only use
it for a genuinely fresh start. Set `FORCE_REINSTALL` back to `0`
immediately after (a Dokploy env change + redeploy, not a code change) so
a later unrelated redeploy can never accidentally wipe the DB again.

## Remaining one-time manual setup

1. Log in as admin, go to **Settings -> System -> General -> Basic Setup**
   and set:
   - **Uploads Directory** -> `/opt/blesta/data/uploads/`
   - **Log Directory** -> `/opt/blesta/data/logs/`
   - Check **"My installation is behind a proxy or load balancer"** (Dokploy
     terminates TLS via Traefik in front of this container).
2. Under **Settings -> Company -> Emails -> Mail Settings**, configure an
   external SMTP provider — this container doesn't run a local MTA.
3. Create a staff API-access user (**Staff -> Manage -> API Access**) and
   put its username/API key into `middleware`'s `BLESTA_API_URL` /
   `BLESTA_API_USER` / `BLESTA_API_KEY` (set on the `middleware` service in
   Dokploy's compose env).

## Extending with custom modules/plugins

`plugins/` and `modules/` in this directory are copied into the image at
build time (`/opt/blesta/blesta/plugins` and
`/opt/blesta/blesta/components/modules`) — this is where the Synelia <->
OpenStack provisioning module will live once it's built, versioned with
the rest of this repo rather than hand-edited inside a container.
