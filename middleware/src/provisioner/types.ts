// Shapes mirror synelia-cloud's src/lib/types.ts (VM, Volume) so routes can
// pass provisioner results straight through to the frontend contract.

export interface VM {
  id: string;
  espaceId: string;
  nom: string;
  os: string;
  vcpu: number;
  ramGo: number;
  diskGo: number;
  ips: Array<{ adresse: string; type: 'privee' | 'publique'; ptr?: string }>;
  statut: 'running' | 'stopped' | 'creating' | 'error' | 'migrating';
  site: string;
  flavor?: string;
}

export interface Volume {
  id: string;
  espaceId: string;
  nom: string;
  tailleGo: number;
  classe: 'nvme' | 'ssd' | 'hdd' | 'archive';
  chiffre: boolean;
  attachedTo?: string;
  ephemere: boolean;
  iops: number;
}

export interface CreateVMInput {
  nom: string;
  flavorId: string;
  imageId: string;
  networkId: string;
}

export interface CreateVolumeInput {
  nom: string;
  tailleGo: number;
}

/**
 * The boundary this repo's README calls out explicitly: everything that
 * models actual infrastructure (VMs, k8s, load balancers, volumes) goes
 * through this interface rather than talking to OpenStack directly from
 * route handlers, so a second backend (or a mock, for tests) is a second
 * implementation of this interface -- not a rewrite of the routes.
 */
export interface Provisioner {
  listVMs(): Promise<VM[]>;
  getVM(id: string): Promise<VM | null>;
  createVM(input: CreateVMInput): Promise<VM>;
  deleteVM(id: string): Promise<void>;
  startVM(id: string): Promise<void>;
  stopVM(id: string): Promise<void>;
  rebootVM(id: string): Promise<void>;

  listVolumes(): Promise<Volume[]>;
  createVolume(input: CreateVolumeInput): Promise<Volume>;
  deleteVolume(id: string): Promise<void>;

  // Not implemented yet -- k8s (magnum), load balancers (octavia) and DNS
  // (designate) all have working catalog endpoints on the lab tenant (see
  // openstack.ts comment header) but no route/mapping has been built out.
}
