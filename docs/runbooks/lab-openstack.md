# Runbook — Lab OpenStack (ctrl1 / comp1 / stor1)

| hôte  | IP             | rôle       |
|-------|----------------|------------|
| ctrl1 | 192.168.26.235 | contrôleur |
| comp1 | 192.168.26.236 | calcul     |
| stor1 | 192.168.26.237 | stockage   |

Depuis dev01 : `env -u SSH_AUTH_SOCK ssh -o PubkeyAuthentication=no root@192.168.26.235` (mot de passe partagé,
hors dépôt). L'agent SSH de dev01 est mort : toujours `env -u SSH_AUTH_SOCK`.

Brancher le backend sur le lab : `SYNELIA_FOURNISSEUR=openstack`, `SYNELIA_OS_AUTH_URL=http://192.168.26.234:5000/v3`,
`SYNELIA_OS_APPLICATION_CREDENTIAL_ID/SECRET` (créer avec `openstack application credential create synelia`),
`uv sync --extra openstack`. Depuis un poste distant : tunnel SSH + `SYNELIA_OS_ENDPOINT_OVERRIDES='{"compute":"http://127.0.0.1:8774/v2.1"}'`.
