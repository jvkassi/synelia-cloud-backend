import { config } from '../config.js';
import { OpenstackProvisioner } from './openstack.js';
import type { Provisioner } from './types.js';

class NotConfiguredProvisioner implements Provisioner {
  private fail(): never {
    throw new Error(
      'OpenStack is not configured -- set OS_AUTH_URL / OS_USERNAME / OS_PASSWORD (see .env.example).'
    );
  }
  listVMs = () => this.fail();
  getVM = () => this.fail();
  createVM = () => this.fail();
  deleteVM = () => this.fail();
  startVM = () => this.fail();
  stopVM = () => this.fail();
  rebootVM = () => this.fail();
  listVolumes = () => this.fail();
  createVolume = () => this.fail();
  deleteVolume = () => this.fail();
}

export const provisioner: Provisioner = config.openstack.authUrl
  ? new OpenstackProvisioner()
  : new NotConfiguredProvisioner();
