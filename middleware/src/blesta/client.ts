import { config } from '../config.js';

/**
 * Thin wrapper around Blesta's REST API (https://docs.blesta.com/display/dev/API).
 * Auth is HTTP Basic: the Blesta staff username as the user, and that
 * user's API key (Staff -> Manage -> API Access) as the password.
 *
 * Not yet exercised against a live instance -- Blesta itself needs to go
 * through its one-time install wizard (creates the admin account this API
 * user is layered on top of) before BLESTA_API_USER/BLESTA_API_KEY exist.
 * See ../../blesta/README.md for that step.
 */
export class BlestaClient {
  private get baseUrl(): string {
    if (!config.blesta.baseUrl) {
      throw new Error('BLESTA_API_URL is not configured');
    }
    return config.blesta.baseUrl.replace(/\/$/, '');
  }

  private authHeader(): string {
    const { userId, apiKey } = config.blesta;
    if (!userId || !apiKey) {
      throw new Error('BLESTA_API_USER / BLESTA_API_KEY are not configured');
    }
    return 'Basic ' + Buffer.from(`${userId}:${apiKey}`).toString('base64');
  }

  /**
   * Blesta's API is RPC-shaped: POST /api/{model}/{method}.json with the
   * method's params as form fields. e.g. call('clients', 'getList') or
   * call('invoices', 'getAll', { client_id: 4 }).
   */
  async call<T>(model: string, method: string, params: Record<string, string | number> = {}): Promise<T> {
    const body = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));

    const res = await fetch(`${this.baseUrl}/api/${model}/${method}.json`, {
      method: 'POST',
      headers: {
        Authorization: this.authHeader(),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body,
    });

    if (!res.ok) {
      throw new Error(`Blesta API ${model}/${method} -> ${res.status}: ${await res.text()}`);
    }

    const json = (await res.json()) as { response?: T; error?: unknown };
    if (json.error) {
      throw new Error(`Blesta API ${model}/${method} error: ${JSON.stringify(json.error)}`);
    }
    return json.response as T;
  }
}

export const blesta = new BlestaClient();
