/**
 * SMART HEALTH MONITORING SYSTEM — API CONFIGURATION
 * 
 * SECURITY & ARCHITECTURAL BOUNDARIES:
 * 1. All client communication flows exclusively through the FastAPI backend gateway.
 * 2. Frontend code NEVER connects directly to MySQL or MongoDB.
 * 3. Never expose database connection strings, credentials, or private secrets in browser code.
 * 4. In development, endpoints are configured via Vite environment variables.
 */

export interface ApiConfig {
  baseUrl: string;
  wsUrl: string;
  timeoutMs: number;
  isSimulated: boolean;
}

const getProcessEnv = (): Record<string, string | undefined> | undefined => {
  try {
    const g = globalThis as unknown as { process?: { env?: Record<string, string | undefined> } };
    return g.process?.env;
  } catch {
    return undefined;
  }
};

const resolveBaseUrl = (): string => {
  const envUrl =
    typeof import.meta !== 'undefined' && import.meta.env
      ? import.meta.env.VITE_API_BASE_URL
      : getProcessEnv()?.VITE_API_BASE_URL;
  if (typeof envUrl === 'string' && envUrl.trim().length > 0) {
    return envUrl.trim().replace(/\/+$/, '');
  }
  if (typeof window !== 'undefined' && window.location.hostname === '127.0.0.1') {
    return 'http://127.0.0.1:8000';
  }
  return 'http://localhost:8000';
};

const resolveWsUrl = (): string => {
  const envWs =
    typeof import.meta !== 'undefined' && import.meta.env
      ? import.meta.env.VITE_WS_BASE_URL
      : getProcessEnv()?.VITE_WS_BASE_URL;
  if (typeof envWs === 'string' && envWs.trim().length > 0) {
    return envWs.trim().replace(/\/+$/, '');
  }
  if (typeof window !== 'undefined' && window.location.hostname === '127.0.0.1') {
    return 'ws://127.0.0.1:8000';
  }
  return 'ws://localhost:8000';
};

export const API_CONFIG: Readonly<ApiConfig> = {
  baseUrl: resolveBaseUrl(),
  wsUrl: resolveWsUrl(),
  timeoutMs: 10000,
  isSimulated: true, // System-wide indicator that readings are simulated
};

/**
 * Helper to construct versioned API route URLs.
 * Automatically avoids duplicating /api/v1 if already present in endpoint.
 * Example: getApiUrl('/patients') -> 'http://localhost:8000/api/v1/patients'
 * Example: getApiUrl('/api/v1/evaluation/crud/records') -> 'http://localhost:8000/api/v1/evaluation/crud/records'
 */
export function getApiUrl(endpoint: string, version: string = 'v1'): string {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  if (cleanEndpoint.startsWith(`/api/${version}/`) || cleanEndpoint === `/api/${version}`) {
    return `${API_CONFIG.baseUrl}${cleanEndpoint}`;
  }
  if (cleanEndpoint.startsWith('/api/')) {
    return `${API_CONFIG.baseUrl}${cleanEndpoint}`;
  }
  return `${API_CONFIG.baseUrl}/api/${version}${cleanEndpoint}`;
}
