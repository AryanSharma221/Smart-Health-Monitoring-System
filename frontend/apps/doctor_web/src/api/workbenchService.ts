/**
 * SMART HEALTH MONITORING SYSTEM — DEMO SQL WORKBENCH API SERVICE
 *
 * Provides typed client execution for the Demo Mode SQL Workbench:
 * - Strictly sends single SQL statements to POST /api/v1/evaluation/workbench/execute.
 * - Requires is_demo_mode: true.
 * - Enforces zero writes to MongoDB.
 * - Captures real execution duration, returned rows, affected count, and ML assessment feedback.
 */

import { apiRequest, ApiClientError } from './client';
import { getApiUrl } from './config';

export interface SQLWorkbenchExecuteRequest {
  sql: string;
  is_demo_mode: boolean;
  patient_id?: string;
  params?: Record<string, any>;
}

export interface MLAssessmentSummary {
  assessed: boolean;
  event_id?: string | null;
  patient_id?: string | null;
  anomaly_score?: number | null;
  result?: string | null;
  alert_created: boolean;
  alert_severity?: string | null;
  message?: string | null;
}

export interface SQLWorkbenchExecuteResponse {
  status: 'success' | 'error';
  statement_type: string;
  execution_time_ms: number;
  columns?: string[] | null;
  rows?: any[][] | null;
  row_count: number;
  rows_affected?: number | null;
  last_inserted_id?: string | number | null;
  message?: string | null;
  error?: string | null;
  ml_assessment?: MLAssessmentSummary | null;
}

export interface CommandHistoryItem {
  id: string;
  sql: string;
  status: 'success' | 'error';
  statementType: string;
  timestamp: string;
  executionTimeMs: number;
  rowsAffected?: number | null;
  rowCount?: number | null;
  lastInsertedId?: string | number | null;
  errorMessage?: string | null;
}

export const workbenchService = {
  /**
   * Execute validated SQL statement against the isolated demo SQLite database.
   * In Demo Mode, if an expired or invalid token is encountered, automatically
   * acquires a fresh doctor session token and retries once seamlessly.
   */
  async executeQuery(
    request: SQLWorkbenchExecuteRequest
  ): Promise<SQLWorkbenchExecuteResponse> {
    try {
      return await apiRequest<SQLWorkbenchExecuteResponse>(
        '/evaluation/workbench/execute',
        {
          method: 'POST',
          body: JSON.stringify(request),
        }
      );
    } catch (err: unknown) {
      if (err instanceof ApiClientError && err.statusCode === 401 && request.is_demo_mode) {
        try {
          const loginUrl = getApiUrl('/auth/login');
          const loginResp = await fetch(loginUrl, {
            method: 'POST',
            headers: {
              'Accept': 'application/json',
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              email: 'doctor@hospital.org',
              password: 'DoctorPassword123!',
            }),
          });
          if (loginResp.ok) {
            const loginData = await loginResp.json();
            const token = loginData.access_token || loginData.token;
            if (token) {
              sessionStorage.setItem('shm_auth_token', token);
              return await apiRequest<SQLWorkbenchExecuteResponse>(
                '/evaluation/workbench/execute',
                {
                  method: 'POST',
                  body: JSON.stringify(request),
                }
              );
            }
          }
        } catch {
          // If auto-refresh fails, throw original error
        }
      }
      throw err;
    }
  },
};
