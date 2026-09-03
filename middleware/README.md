# middleware

REST API for `synelia-cloud`, shaped to match its existing contract
(`docs/api/openapi.json` / `src/lib/types.ts` in that repo).

## Stack: Node.js + TypeScript + Express

The frontend is already Next.js/TypeScript, so the same language keeps the
type definitions shareable later; Express over a heavier framework because
this is a thin routing/translation layer over two other systems (Blesta,
OpenStack), not where the business logic should live.

## Structure

- `src/blesta/client.ts` — Blesta REST API client (HTTP Basic auth: staff
  username + API key). Everything Blesta already models — clients, orders,
  invoices, services, packages — goes through this.
- `src/provisioner/` — the boundary for actual infrastructure. `types.ts`
  defines the `Provisioner` interface (`VM`/`Volume` shapes matching
  synelia-cloud's `types.ts`); `openstack.ts` is a real implementation
  (Keystone auth + Nova + Cinder) against the OVH lab tenant; `index.ts`
  picks it if `OS_AUTH_URL` etc. are set, otherwise a stub that throws a
  clear "not configured" error instead of the frontend contract silently
  returning empty data.
- `src/routes/` — one file per resource group. Only a representative slice
  of synelia-cloud's ~360 endpoints is implemented (`/vms`, `/volumes`,
  `/organisations`, `/facturation/factures`) to prove both integration
  paths (Blesta-backed and OpenStack-backed) end to end; the rest follow
  the same pattern.

## What's real vs. stubbed right now

- OpenStack: **real**, tested against the lab tenant's Keystone (auth
  succeeds, catalog resolved). Compute (Nova) and block storage (Cinder)
  are wired up; networking (Neutron), k8s (Magnum), load balancers
  (Octavia) and DNS (Designate) all have working catalog endpoints but no
  route/mapping yet — same `Provisioner` interface, next slice.
- Blesta: client code is written against Blesta's documented API shape but
  **not yet exercised against a live instance** — Blesta needs to go
  through its one-time install wizard first (see `../blesta/README.md`),
  which is also when `BLESTA_API_USER`/`BLESTA_API_KEY` get created.

## Running

```
cp .env.example .env   # fill in Blesta + OpenStack values
npm install
npm run dev
```
