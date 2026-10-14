/**
 * SMART HEALTH MONITORING SYSTEM — AUTHENTICATION SERVICE BOUNDARY
 * 
 * Agrees with system contract: POST /api/v1/auth/login
 * 
 * SECURITY & INTEGRATION CONSTRAINTS:
 * 1. The FastAPI backend is the sole authority for credential verification.
 * 2. Never log credentials, passwords, or tokens to the console.
 * 3. Never embed hardcoded tokens or shortcuts.
 * 4. Distinctly categorize network failures (gateway offline) from invalid credentials (401).
 * 5. Handles session storage in sessionStorage (cleared on tab close / logout).
 */

import { getApiUrl, API_CONFIG } from './config';
import type { UserSession } from '../types';

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface LoginResponse {
  accessToken: string;
  tokenType: string;
  user: UserSession;
}

export type AuthErrorType =
  | 'invalid_credentials'
  | 'network_error'
  | 'server_error'
  | 'session_expired'
  | 'unexpected_response'
  | 'unknown';

export class AuthServiceError extends Error {
  public type: AuthErrorType;
  public statusCode?: number;

  constructor(type: AuthErrorType, message: string, statusCode?: number) {
    super(message);
    this.name = 'AuthServiceError';
    this.type = type;
    this.statusCode = statusCode;
  }
}

const TOKEN_STORAGE_KEY = 'shm_auth_token';
const USER_STORAGE_KEY = 'shm_user_session';

/**
 * Executes login against POST /api/v1/auth/login.
 */
export async function loginWithCredentials(
  credentials: LoginCredentials
): Promise<LoginResponse> {
  const url = getApiUrl('/auth/login');
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_CONFIG.timeoutMs);

  const cleanEmail = credentials.email.trim();
  // Transmit credentials without trimming or modifying password
  const payload = {
    email: cleanEmail,
    password: credentials.password,
  };

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    // 401 Unauthorized / 400 Bad Request
    if (response.status === 401 || response.status === 400) {
      throw new AuthServiceError(
        'invalid_credentials',
        'Invalid clinician email or password. Please verify your credentials and try again.',
        response.status
      );
    }

    // 403 Forbidden
    if (response.status === 403) {
      throw new AuthServiceError(
        'invalid_credentials',
        'Account is disabled or clinician authorization is restricted.',
        403
      );
    }

    // Server Error 5xx
    if (response.status >= 500) {
      throw new AuthServiceError(
        'server_error',
        `The FastAPI authentication service encountered an internal error (HTTP ${response.status}).`,
        response.status
      );
    }

    if (!response.ok) {
      throw new AuthServiceError(
        'unexpected_response',
        `Authentication failed with unexpected status HTTP ${response.status}.`,
        response.status
      );
    }

    const data = await response.json();

    // Validate expected contract fields
    const accessToken = data.access_token || data.accessToken || data.token;
    if (!accessToken || typeof accessToken !== 'string') {
      throw new AuthServiceError(
        'unexpected_response',
        'Authentication response missing valid access token.'
      );
    }

    // Resolve user profile from response or construct normalized UserSession
    const rawUser = data.user || {};
    const userSession: UserSession = {
      userId: rawUser.user_id || rawUser.userId || 'usr_unknown',
      email: rawUser.email || cleanEmail,
      name: rawUser.name || cleanEmail.split('@')[0],
      role: rawUser.role || 'doctor',
      licenseNumber: rawUser.license_number || rawUser.licenseNumber,
    };

    const loginResult: LoginResponse = {
      accessToken,
      tokenType: data.token_type || 'bearer',
      user: userSession,
    };

    // Store in browser sessionStorage (cleared on window close)
    sessionStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
    sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(userSession));

    return loginResult;
  } catch (error: unknown) {
    clearTimeout(timeoutId);

    if (error instanceof AuthServiceError) {
      throw error;
    }

    if (error instanceof Error && error.name === 'AbortError') {
      throw new AuthServiceError(
        'network_error',
        `Authentication request timed out after ${API_CONFIG.timeoutMs / 1000} seconds. The backend gateway is unresponsive.`
      );
    }

    // Network disconnection / TypeError fetch failed
    throw new AuthServiceError(
      'network_error',
      `Unable to reach the FastAPI authentication gateway at ${API_CONFIG.baseUrl}. Ensure the backend service is running.`
    );
  }
}

/**
 * Retrieves persisted session from sessionStorage if available.
 */
export function getPersistedSession(): { token: string; user: UserSession } | null {
  try {
    const token = sessionStorage.getItem(TOKEN_STORAGE_KEY);
    const userJson = sessionStorage.getItem(USER_STORAGE_KEY);
    if (!token || !userJson) return null;
    const user = JSON.parse(userJson) as UserSession;
    return { token, user };
  } catch {
    clearStoredSession();
    return null;
  }
}

/**
 * Clears authentication tokens and cached user data.
 */
export function clearStoredSession(): void {
  try {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(USER_STORAGE_KEY);
  } catch {
    // ignore storage exceptions
  }
}
