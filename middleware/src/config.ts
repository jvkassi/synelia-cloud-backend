function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

export const config = {
  port: Number(process.env.PORT ?? 4000),

  blesta: {
    baseUrl: process.env.BLESTA_API_URL ?? '',
    userId: process.env.BLESTA_API_USER ?? '',
    apiKey: process.env.BLESTA_API_KEY ?? '',
  },

  // Real OpenStack lab credentials -- never log these, never return them in
  // any API response. Loaded lazily via requireOpenstack() so the server can
  // still boot (and Blesta-backed routes still work) if this block isn't
  // configured yet in a given environment.
  openstack: {
    authUrl: process.env.OS_AUTH_URL ?? '',
    username: process.env.OS_USERNAME ?? '',
    password: process.env.OS_PASSWORD ?? '',
    projectName: process.env.OS_PROJECT_NAME ?? 'admin',
    userDomainName: process.env.OS_USER_DOMAIN_NAME ?? 'Default',
    projectDomainName: process.env.OS_PROJECT_DOMAIN_NAME ?? 'Default',
    regionName: process.env.OS_REGION_NAME ?? 'RegionOne',
  },
};

export function requireOpenstack(): typeof config.openstack {
  const os = config.openstack;
  if (!os.authUrl || !os.username || !os.password) {
    throw new Error(
      'OpenStack is not configured (OS_AUTH_URL / OS_USERNAME / OS_PASSWORD) -- ' +
        'provisioning routes are unavailable until it is.'
    );
  }
  return os;
}

export { required };
