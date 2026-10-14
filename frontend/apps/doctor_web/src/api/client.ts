/**
 * SMART HEALTH MONITORING SYSTEM — AUTHORIZED API CLIENT
 * 
 * Strict architectural boundaries:
 * 1. Consumes exclusively central FastAPI gateway endpoints (/api/v1/...).
 * 2. Authenticates requests via Bearer token retrieved from sessionStorage.
 * 3. Never logs tokens, passwords, or patient credentials.
 * 4. Distinctly categorizes network offline errors from HTTP error statuses.
 * 5. Handles request timeout and cancellation via AbortController.
 * 6. Safely handles empty 204 responses and non-JSON backend error payloads.
 */

import { getApiUrl, API_CONFIG } from './config';

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  skipAuth?: boolean;
}

export type ApiErrorType =
  | 'network_error'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'server_error'
  | 'parse_error'
  | 'timeout';

export class ApiClientError extends Error {
  public statusCode?: number;
  public errorType: ApiErrorType;
  public responseData?: unknown;

  constructor(
    message: string,
    errorType: ApiErrorType,
    statusCode?: number,
    responseData?: unknown
  ) {
    super(message);
    this.name = 'ApiClientError';
    this.errorType = errorType;
    this.statusCode = statusCode;
    this.responseData = responseData;
  }
}

/**
 * Retrieves stored session token from sessionStorage.
 */
export function getStoredAuthToken(): string | null {
  try {
    return sessionStorage.getItem('shm_auth_token');
  } catch {
    return null;
  }
}

/**
 * Executes an authorized HTTP request against the FastAPI backend.
 */
export async function apiRequest<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const url = getApiUrl(endpoint);
  const { timeoutMs = API_CONFIG.timeoutMs, skipAuth = false, headers = {}, ...customConfig } = options;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const requestHeaders: Record<string, string> = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    ...(headers as Record<string, string>),
  };

  if (!skipAuth) {
    const token = getStoredAuthToken();
    if (token) {
      requestHeaders['Authorization'] = `Bearer ${token}`;
    }
  }

  try {
    const response = await fetch(url, {
      ...customConfig,
      headers: requestHeaders,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    // Handle non-2xx responses with error payload extraction
    if (!response.ok) {
      let errorBody: unknown = undefined;
      let detailMsg: string | undefined = undefined;

      try {
        const errText = await response.text();
        if (errText && errText.trim().length > 0) {
          try {
            errorBody = JSON.parse(errText);
            if (errorBody && typeof errorBody === 'object') {
              if ('detail' in errorBody && typeof errorBody.detail === 'string') {
                detailMsg = errorBody.detail;
              } else if ('message' in errorBody && typeof errorBody.message === 'string') {
                detailMsg = errorBody.message;
              }
            }
          } catch {
            errorBody = errText;
            detailMsg = errText.slice(0, 200);
          }
        }
      } catch {
        // error body reading failed, proceed with status-based message
      }

      if (response.status === 401) {
        throw new ApiClientError(
          detailMsg || 'Authentication required or session expired. Please sign in again.',
          'unauthorized',
          401,
          errorBody
        );
      }

      if (response.status === 403) {
        throw new ApiClientError(
          detailMsg || 'Access denied. Clinician role is not authorized for this resource.',
          'forbidden',
          403,
          errorBody
        );
      }

      if (response.status === 404) {
        throw new ApiClientError(
          detailMsg || `Resource not found at ${endpoint}.`,
          'not_found',
          404,
          errorBody
        );
      }

      if (response.status >= 500) {
        throw new ApiClientError(
          detailMsg || `FastAPI service error (HTTP ${response.status}).`,
          'server_error',
          response.status,
          errorBody
        );
      }

      throw new ApiClientError(
        detailMsg || `API request failed with HTTP ${response.status}.`,
        'server_error',
        response.status,
        errorBody
      );
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return null as unknown as T;
    }

    // Parse response body
    const rawText = await response.text();
    if (!rawText || rawText.trim().length === 0) {
      return null as unknown as T;
    }

    try {
      const data = JSON.parse(rawText);
      return data as T;
    } catch {
      throw new ApiClientError(
        'Invalid JSON response received from API gateway.',
        'parse_error',
        response.status
      );
    }
  } catch (error: unknown) {
    clearTimeout(timeoutId);

    if (error instanceof ApiClientError) {
      throw error;
    }

    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiClientError(
        `Request to ${endpoint} timed out after ${timeoutMs / 1000}s.`,
        'timeout'
      );
    }

    // Network disconnection / gateway unreachable
    throw new ApiClientError(
      `Unable to reach the FastAPI gateway at ${API_CONFIG.baseUrl}. Ensure the backend service is running.`,
      'network_error'
    );
  }
}
