# Runbook — Lab OpenStack (ctrl1 / comp1 / comp2 / stor1)

| hôte  | IP             | rôle       |
|-------|----------------|------------|
| ctrl1 | 192.168.26.235 | contrôleur (+ CAPI/CAPO, k3s de management Magnum) |
| comp1 | 192.168.26.236 | calcul     |
| comp2 | 192.168.26.238 | calcul     |
| stor1 | 192.168.26.237 | stockage   |

Depuis dev01 : `env -u SSH_AUTH_SOCK ssh -o PubkeyAuthentication=no root@192.168.26.235` (mot de passe partagé,
hors dépôt). L'agent SSH de dev01 est mort : toujours `env -u SSH_AUTH_SOCK`. Symptôme si oublié : un échec
SSH absurde (`Connection to UNKNOWN port 65535 timed out`) au lieu d'un vrai refus/timeout — c'est l'agent
mort qui casse la négociation, pas un problème réseau réel.

Le physical host redémarre les VM libvirt du lab (arrêt nocturne ~21h UTC) : après chaque redémarrage,
vérifier Octavia (`o-hm0`/`octavia-interface`, bug de course au boot connu, cf. plus bas) et l'état des
VM hébergement Web Cloud / cluster Kubernetes (cf. §CAPI).

## Accéder à une VM du lab sans IP flottante

Les VM sans IP flottante (masters Magnum, nœuds sans routage externe) ne sont joignables que depuis le
même réseau L2 — pas depuis dev01. Trouver le namespace `qdhcp-<network_id>` du réseau Neutron concerné
(`ip netns list` sur ctrl1) puis `ip netns exec qdhcp-<id> ssh ...` (ou `ping`, `curl`) depuis ctrl1.

## Bug récurrent : `containerd` version du config.toml après mise à jour non surveillée

Une mise à jour de paquet régénère `/etc/containerd/config.toml` en `version = 4`, alors que le binaire
installé sur les VM du lab ne sait lire que jusqu'à la version 3 → `containerd.service`/`docker.service`
boot-loop indéfiniment au moindre redémarrage de VM. Symptôme : Docker inutilisable sur une VM
hébergement/Drive après un reboot, alors qu'elle l'était avant.
- Fix réactif : `sed -i 's/^version = 4/version = 3/' /etc/containerd/config.toml && systemctl reset-failed containerd docker && systemctl restart containerd docker`.
- Fix durable : un drop-in systemd (`DROP_IN_CONTAINERD` dans `web_hebergement/service.py`, réutilisé par
  `web_drive` et `projets`) baké dans le cloud-init de toute nouvelle VM, avec un `ExecStartPre` qui ré-applique
  le sed avant chaque démarrage de containerd — pas la peine de refixer à la main sur les VM créées après ce fix.

## Cluster Kubernetes (Magnum/CAPI) — où regarder quand `openstack coe cluster show` reste bloqué

Le statut Magnum (`CREATE_IN_PROGRESS`, etc.) reflète l'état du `Cluster` Cluster-API, pas forcément le vrai
état des VM. Les contrôleurs CAPI/CAPO tournent **sur ctrl1**, sous containerd/`crictl` (pas `docker ps`),
dans un cluster de management **k3s** local :
```
ssh ctrl1
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl get cluster,machines,kubeadmcontrolplane,openstackmachine -A
kubectl describe machine <nom> -n magnum-system   # conditions Ready/NodeHealthy/HealthCheckSucceeded
kubectl logs -n capi-kubeadm-control-plane-system deploy/capi-kubeadm-control-plane-controller-manager --tail=50
```
Si une `Machine` reste `Ready: False` avec `OpenstackMachine Ready: true` (le port Neutron et la VM Nova
existent), le nœud est monté côté infra mais son kubelet/API server ne répond pas — souvent un simple hang
post-reboot de la VM. Vérifier le boot réel sans réseau via la console série Nova
(`compute.get_server_console_output(server_id, length=60)`) avant de creuser plus loin ; un `reboot_server(id, 'HARD')`
suffit fréquemment à débloquer un nœud qui bootait proprement mais ne répondait plus (ping/SSH silencieux
alors que le port Neutron est `ACTIVE` — la VM elle-même était juste figée). CAPI reconcilie toutes les
~10 min : laisser le temps après un hard reboot avant de conclure à un problème plus profond.

## Brancher le backend sur le lab

`SYNELIA_FOURNISSEUR=openstack`, `SYNELIA_OS_AUTH_URL=http://192.168.26.234:5000/v3`,
`SYNELIA_OS_APPLICATION_CREDENTIAL_ID/SECRET` (créer avec `openstack application credential create synelia`),
`uv sync --extra openstack`. Depuis un poste distant : tunnel SSH + `SYNELIA_OS_ENDPOINT_OVERRIDES='{"compute":"http://127.0.0.1:8774/v2.1"}'`.

## État réel vs simulé de l'univers Infrastructure

Voir [[infra-universe-real-vs-simulated]] (mémoire de session) pour le détail à jour — au 2026-09-07,
VM/Espaces/Buckets/Kubernetes/Load-balancers/Réseau/Volumes/Bases sont tous réellement provisionnés sur ce
lab (Sauvegardes/PRA échouent honnêtement, Karbor n'étant pas déployé). Deux points ouverts non corrigés :
un plantage de l'API partagée sous charge concurrente réelle (suspecté : appel SDK OpenStack synchrone
bloquant la boucle asyncio), et des enregistrements `web_hebergement` orphelins en base dont la VM Nova
réelle a été supprimée sans nettoyage côté DB.
