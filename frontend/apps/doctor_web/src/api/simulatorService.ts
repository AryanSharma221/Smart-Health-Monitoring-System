/**
 * SMART HEALTH MONITORING SYSTEM — SIMULATOR LIFECYCLE SERVICE
 * 
 * Provides typed client calls to backend FastAPI simulator proxy endpoints:
 * - GET  /api/v1/simulator/status (reads unified generator and ingestion states)
 * - POST /api/v1/simulator/start  (starts or resumes telemetry generation)
 * - POST /api/v1/simulator/stop   (stops telemetry generation immediately)
 */

import { apiRequest } from './client';

export type SimulatorLifecycleState = 'RUNNING' | 'STOPPED' | 'STOPPING' | 'ERROR';

export interface UnifiedSimulatorStatus {
  simulator: {
    reachable: boolean;
    is_running: boolean;
    lifecycle_state: SimulatorLifecycleState;
    latest_generation_at: string | null;
    current_scenario: string;
    active_patients?: string[];
    interrupted_patients?: string[];
    error?: string | null;
  };
  ingestion: {
    enabled: boolean;
    running: boolean;
    pipeline_health: string;
    events_received_count?: number;
    events_accepted_count: number;
    events_duplicates_skipped_count: number;
    events_rejected_count?: number;
    consecutive_failures: number;
    last_poll_succeeded?: boolean | null;
    last_poll_timestamp: string | null;
    last_successful_poll_timestamp: string | null;
    current_cursor?: string | null;
    simulator_base_url?: string | null;
    last_error_category?: string | null;
    last_error_detail?: string | null;
  };
  backend_healthy: boolean;
  disclaimer: string;
}

export interface SimulatorControlResponse {
  status: string;
  lifecycle_state: SimulatorLifecycleState;
  is_running: boolean;
  message: string;
  simulator_response?: Record<string, unknown>;
  ingestion_status?: Record<string, unknown>;
}

/**
 * Fetch unified simulator generator & ingestion worker status.
 */
export async function fetchSimulatorStatus(): Promise<UnifiedSimulatorStatus> {
  return apiRequest<UnifiedSimulatorStatus>('/simulator/status', {
    method: 'GET',
  });
}

/**
 * Start or resume smartwatch telemetry generator loop.
 */
export async function startSimulator(): Promise<SimulatorControlResponse> {
  return apiRequest<SimulatorControlResponse>('/simulator/start', {
    method: 'POST',
  });
}

/**
 * Stop smartwatch telemetry generator loop immediately.
 */
export async function stopSimulator(): Promise<SimulatorControlResponse> {
  return apiRequest<SimulatorControlResponse>('/simulator/stop', {
    method: 'POST',
  });
}

export interface ScenarioUpdateRequest {
  scenario:
    | 'normal'
    | 'resting'
    | 'active'
    | 'recovering'
    | 'signal_interruption'
    | 'alert_test'
    | 'elevated_hr'
    | 'low_spo2';
  target_patient_id?: string | null;
  alert_metric?: 'heart_rate' | 'spo2' | 'temperature' | 'all';
  reason?: string;
}

export interface ScenarioTransitionResponse {
  status: string;
  scenario: string;
  target_patient_id?: string | null;
  alert_metric?: string;
  message: string;
  simulator_response?: Record<string, unknown>;
  disclaimer: string;
}

/**
 * Trigger a reproducible demonstration scenario across demo cohort or target patient.
 */
export async function setSimulatorScenario(
  payload: ScenarioUpdateRequest
): Promise<ScenarioTransitionResponse> {
  return apiRequest<ScenarioTransitionResponse>('/simulator/scenario', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

