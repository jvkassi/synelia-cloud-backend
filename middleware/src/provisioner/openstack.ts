import { requireOpenstack } from '../config.js';
import type {
  CreateVMInput,
  CreateVolumeInput,
  Provisioner,
  VM,
  Volume,
} from './types.js';

/**
 * Real OpenStack provisioner: Keystone v3 (password auth, project-scoped)
 * for tokens, then Nova for compute and Cinder for block storage.
 *
 * The lab tenant's catalog also has neutron (network), magnum
 * (container-infra / k8s), octavia (load-balancer) and designate (dns)
 * public endpoints -- this class only wires up compute + volumes so far;
 * the others are the natural next slice (see Provisioner in types.ts).
 */
export class OpenstackProvisioner implements Provisioner {
  private token: { value: string; expiresAt: number } | null = null;
  private serviceUrls: Record<string, string> = {};

  private async authenticate(): Promise<void> {
    const os = requireOpenstack();

    const res = await fetch(`${os.authUrl}/auth/tokens`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        auth: {
          identity: {
            methods: ['password'],
            password: {
              user: {
                name: os.username,
                domain: { name: os.userDomainName },
                password: os.password,
              },
            },
          },
          scope: {
            project: {
              name: os.projectName,
              domain: { name: os.projectDomainName },
            },
          },
        },
      }),
    });

    if (!res.ok) {
      throw new Error(`Keystone auth failed: ${res.status} ${await res.text()}`);
    }

    const tokenValue = res.headers.get('x-subject-token');
    if (!tokenValue) {
      throw new Error('Keystone auth response missing X-Subject-Token header');
    }

    const body = (await res.json()) as {
      token: { expires_at: string; catalog: Array<{ type: string; endpoints: Array<{ interface: string; url: string }> }> };
    };

    for (const service of body.token.catalog) {
      const publicEndpoint = service.endpoints.find((e) => e.interface === 'public');
      if (publicEndpoint) {
        this.serviceUrls[service.type] = publicEndpoint.url;
      }
    }

    this.token = {
      value: tokenValue,
      expiresAt: new Date(body.token.expires_at).getTime(),
    };
  }

  private async ensureToken(): Promise<string> {
    // Re-auth 60s before actual expiry rather than racing it.
    if (!this.token || this.token.expiresAt - 60_000 < Date.now()) {
      await this.authenticate();
    }
    return this.token!.value;
  }

  private async request<T>(serviceType: string, path: string, init: RequestInit = {}): Promise<T> {
    const token = await this.ensureToken();
    const base = this.serviceUrls[serviceType];
    if (!base) {
      throw new Error(`No '${serviceType}' endpoint in OpenStack service catalog`);
    }

    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: {
        'X-Auth-Token': token,
        'Content-Type': 'application/json',
        ...init.headers,
      },
    });

    if (!res.ok) {
      throw new Error(`OpenStack ${serviceType} ${path} -> ${res.status}: ${await res.text()}`);
    }

    if (res.status === 204) {
      return undefined as T;
    }

    return (await res.json()) as T;
  }

  private mapServerStatus(status: string): VM['statut'] {
    switch (status) {
      case 'ACTIVE':
        return 'running';
      case 'SHUTOFF':
        return 'stopped';
      case 'BUILD':
        return 'creating';
      case 'MIGRATING':
        return 'migrating';
      default:
        return 'error';
    }
  }

  private mapServer(server: any): VM {
    const ips: VM['ips'] = [];
    for (const [networkName, addresses] of Object.entries<any[]>(server.addresses ?? {})) {
      for (const addr of addresses) {
        ips.push({
          adresse: addr.addr,
          type: addr['OS-EXT-IPS:type'] === 'floating' ? 'publique' : 'privee',
        });
      }
    }

    const flavor = server.flavor ?? {};

    return {
      id: server.id,
      espaceId: server.tenant_id ?? '',
      nom: server.name,
      os: server.image?.id ? 'unknown' : 'unknown', // Glance lookup not wired up yet
      vcpu: flavor.vcpus ?? 0,
      ramGo: flavor.ram ? Math.round(flavor.ram / 1024) : 0,
      diskGo: flavor.disk ?? 0,
      ips,
      statut: this.mapServerStatus(server.status),
      site: 'ABJ',
      flavor: flavor.original_name ?? flavor.id,
    };
  }

  async listVMs(): Promise<VM[]> {
    const data = await this.request<{ servers: any[] }>('compute', '/servers/detail');
    return data.servers.map((s) => this.mapServer(s));
  }

  async getVM(id: string): Promise<VM | null> {
    try {
      const data = await this.request<{ server: any }>('compute', `/servers/${id}`);
      return this.mapServer(data.server);
    } catch {
      return null;
    }
  }

  async createVM(input: CreateVMInput): Promise<VM> {
    const data = await this.request<{ server: any }>('compute', '/servers', {
      method: 'POST',
      body: JSON.stringify({
        server: {
          name: input.nom,
          flavorRef: input.flavorId,
          imageRef: input.imageId,
          networks: [{ uuid: input.networkId }],
        },
      }),
    });
    // Nova's create response doesn't include full detail (flavor/addresses);
    // callers should poll getVM() until statut leaves 'creating'.
    return this.mapServer(data.server);
  }

  async deleteVM(id: string): Promise<void> {
    await this.request('compute', `/servers/${id}`, { method: 'DELETE' });
  }

  async startVM(id: string): Promise<void> {
    await this.request('compute', `/servers/${id}/action`, {
      method: 'POST',
      body: JSON.stringify({ 'os-start': null }),
    });
  }

  async stopVM(id: string): Promise<void> {
    await this.request('compute', `/servers/${id}/action`, {
      method: 'POST',
      body: JSON.stringify({ 'os-stop': null }),
    });
  }

  async rebootVM(id: string): Promise<void> {
    await this.request('compute', `/servers/${id}/action`, {
      method: 'POST',
      body: JSON.stringify({ reboot: { type: 'SOFT' } }),
    });
  }

  private mapVolume(volume: any): Volume {
    return {
      id: volume.id,
      espaceId: volume.os_vol_tenant_attr_tenant_id ?? '',
      nom: volume.name ?? volume.id,
      tailleGo: volume.size,
      classe: 'ssd', // Cinder volume_type -> classe mapping is deployment-specific; TODO
      chiffre: Boolean(volume.encrypted),
      attachedTo: volume.attachments?.[0]?.server_id,
      ephemere: false,
      iops: 0, // Not exposed by Cinder directly; depends on the volume_type's QoS
    };
  }

  async listVolumes(): Promise<Volume[]> {
    const data = await this.request<{ volumes: any[] }>('volumev3', '/volumes/detail');
    return data.volumes.map((v) => this.mapVolume(v));
  }

  async createVolume(input: CreateVolumeInput): Promise<Volume> {
    const data = await this.request<{ volume: any }>('volumev3', '/volumes', {
      method: 'POST',
      body: JSON.stringify({ volume: { name: input.nom, size: input.tailleGo } }),
    });
    return this.mapVolume(data.volume);
  }

  async deleteVolume(id: string): Promise<void> {
    await this.request('volumev3', `/volumes/${id}`, { method: 'DELETE' });
  }
}
