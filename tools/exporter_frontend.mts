/**
 * Exporte en JSON ce que le backend copie du frontend : les 41 workflows,
 * les 13 configurations de services managés et la matrice RBAC.
 * Lancé une fois par `tools/contrat_sync.py` via tsx, côté clone du frontend.
 *
 *   tsx tools/exporter_frontend.mts ../synelia-cloud packages/contract/synelia_contract
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const [frontend, sortie] = process.argv.slice(2)
if (!frontend || !sortie) {
  console.error('usage: tsx exporter_frontend.mts <frontend> <sortie>')
  process.exit(2)
}
const lib = resolve(frontend, 'src/lib')
const { WORKFLOWS } = await import(resolve(lib, 'mock/workflows.ts'))
const { MATRICE_RBAC, ROLES_ORDRE } = await import(resolve(lib, 'rbac.ts'))
const { CONFIGURATIONS } = await import(resolve(lib, 'configurations/index.ts'))
const { TACHES_PROVISIONING, CONTRAT_INTEGRATION } = await import(resolve(lib, 'mock/marketplace.ts'))

mkdirSync(sortie, { recursive: true })
writeFileSync(resolve(sortie, 'workflows.json'), JSON.stringify(WORKFLOWS, null, 2) + '\n')
writeFileSync(
  resolve(sortie, 'rbac.json'),
  JSON.stringify({ roles: ROLES_ORDRE, actions: MATRICE_RBAC }, null, 2) + '\n',
)
writeFileSync(
  resolve(sortie, 'marketplace.json'),
  JSON.stringify({ tachesProvisioning: TACHES_PROVISIONING, contratIntegration: CONTRAT_INTEGRATION }, null, 2) + '\n',
)
const confs = Array.isArray(CONFIGURATIONS) ? CONFIGURATIONS : Object.values(CONFIGURATIONS)
writeFileSync(resolve(sortie, 'configurations.json'), JSON.stringify(confs, null, 2) + '\n')
console.log(`workflows=${WORKFLOWS.length} actions_rbac=${MATRICE_RBAC.length} configurations=${confs.length}`)
