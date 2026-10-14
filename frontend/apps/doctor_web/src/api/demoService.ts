/**
 * SMART HEALTH MONITORING SYSTEM — DEMO SIMULATOR & SCENARIO CONTROL SERVICE
 * 
 * Interacts with agreed FastAPI demo proxy endpoints:
 * - POST /api/v1/demo/runs (starts demo run for target patient and scenario)
 * - POST /api/v1/demo/runs/{id}/stop (idempotently halts active demo run)
 * - PATCH /api/v1/demo/runs/{id}/scenario (switches scenario on active run)
 * - GET /api/v1/demo/runs/{id} (queries run status and metrics)
 * 
 * STRICT ARCHITECTURAL CONSTRAINTS:
 * 1. SIMULATED DATA — NOT FOR MEDICAL USE.
 * 2. Scenarios support: normal, single_anomaly, combined_anomaly, missing_data, stale_data, recovery.
 * 3. Never switches to "Running" without confirmed server response.
 * 4. Isolated Kaggle P101–P105 development fixtures available when FastAPI is offline.
 */

import { apiRequest } from './client';

export type DemoScenario =
  | 'normal'
  | 'single_anomaly'
  | 'combined_anomaly'
  | 'missing_data'
  | 'stale_data'
  | 'recovery';

export type DemoRunState = 'idle' | 'running' | 'paused' | 'stopped';

export interface DemoRun {
  runId: string;
  patientId: string;
  scenario: DemoScenario;
  intervalSeconds: number;
  state: DemoRunState;
  startedAt?: string;
  stoppedAt?: string;
  lastEventId?: string | null;
  lastEventTime?: string | null;
  failedDeliveries?: number;
  isSimulated: boolean;
}

export interface StartDemoRunPayload {
  patientId: string;
  scenario: DemoScenario;
  intervalSeconds: number;
}

export interface RawDemoRunDto {
  run_id?: string;
  runId?: string;
  id?: string;
  patient_id?: string;
  patientId?: string;
  scenario?: string;
  interval_seconds?: number;
  intervalSeconds?: number;
  state?: string;
  status?: string;
  started_at?: string;
  startedAt?: string;
  stopped_at?: string;
  stoppedAt?: string;
  last_event_id?: string | null;
  lastEventId?: string | null;
  last_event_time?: string | null;
  lastEventTime?: string | null;
  failed_deliveries?: number;
  failedDeliveries?: number;
  is_simulated?: boolean;
}

/**
 * Normalizes raw API response into typed DemoRun.
 */
export function normalizeDemoRun(dto: RawDemoRunDto): DemoRun {
  const runId = dto.run_id || dto.runId || dto.id || `run_${Date.now()}`;
  const patientId = dto.patient_id || dto.patientId || 'P101';
  const scenario = (dto.scenario || 'normal') as DemoScenario;
  const intervalSeconds = dto.interval_seconds || dto.intervalSeconds || 5;

  let state: DemoRunState = 'idle';
  const rawState = (dto.state || dto.status || 'idle').toLowerCase();
  if (rawState === 'running') state = 'running';
  else if (rawState === 'paused') state = 'paused';
  else if (rawState === 'stopped') state = 'stopped';

  return {
    runId,
    patientId,
    scenario,
    intervalSeconds,
    state,
    startedAt: dto.started_at || dto.startedAt || new Date().toISOString(),
    stoppedAt: dto.stopped_at || dto.stoppedAt,
    lastEventId: dto.last_event_id || dto.lastEventId || null,
    lastEventTime: dto.last_event_time || dto.lastEventTime || null,
    failedDeliveries: dto.failed_deliveries || dto.failedDeliveries || 0,
    isSimulated: dto.is_simulated !== false,
  };
}

// In-Memory Development Fixture Run Store
let fixtureActiveRun: DemoRun | null = null;

/**
 * Starts a demonstration simulation run.
 * POST /api/v1/demo/runs
 */
export async function startDemoRun(
  payload: StartDemoRunPayload,
  useFixtures: boolean = false
): Promise<DemoRun> {
  if (useFixtures) {
    fixtureActiveRun = {
      runId: `run_fix_${Date.now().toString().slice(-6)}`,
      patientId: payload.patientId,
      scenario: payload.scenario,
      intervalSeconds: Math.max(1, Math.min(60, payload.intervalSeconds)),
      state: 'running',
      startedAt: new Date().toISOString(),
      lastEventId: `evt_fix_${Math.random().toString(36).substring(2, 8)}`,
      lastEventTime: new Date().toISOString(),
      failedDeliveries: 0,
      isSimulated: true,
    };
    return { ...fixtureActiveRun };
  }

  const data = await apiRequest<RawDemoRunDto | { data: RawDemoRunDto } | { run: RawDemoRunDto }>(
    '/demo/runs',
    {
      method: 'POST',
      body: JSON.stringify({
        patient_id: payload.patientId,
        scenario: payload.scenario,
        interval_seconds: Math.max(1, Math.min(60, payload.intervalSeconds)),
      }),
    }
  );

  let raw: RawDemoRunDto = {};
  if (data && typeof data === 'object') {
    if ('data' in data && data.data && typeof data.data === 'object') {
      raw = data.data as RawDemoRunDto;
    } else if ('run' in data && data.run && typeof data.run === 'object') {
      raw = data.run as RawDemoRunDto;
    } else {
      raw = data as RawDemoRunDto;
    }
  }

  return normalizeDemoRun(raw);
}

/**
 * Halts an active demonstration simulation run.
 * POST /api/v1/demo/runs/{runId}/stop
 */
export async function stopDemoRun(
  runId: string,
  useFixtures: boolean = false
): Promise<DemoRun> {
  if (useFixtures) {
    if (fixtureActiveRun && fixtureActiveRun.runId === runId) {
      fixtureActiveRun = {
        ...fixtureActiveRun,
        state: 'stopped',
        stoppedAt: new Date().toISOString(),
      };
      return { ...fixtureActiveRun };
    }
    return {
      runId,
      patientId: 'P101',
      scenario: 'normal',
      intervalSeconds: 5,
      state: 'stopped',
      stoppedAt: new Date().toISOString(),
      isSimulated: true,
    };
  }

  const data = await apiRequest<RawDemoRunDto | { data: RawDemoRunDto } | { run: RawDemoRunDto }>(
    `/demo/runs/${encodeURIComponent(runId)}/stop`,
    {
      method: 'POST',
    }
  );

  let raw: RawDemoRunDto = {};
  if (data && typeof data === 'object') {
    if ('data' in data && data.data && typeof data.data === 'object') {
      raw = data.data as RawDemoRunDto;
    } else if ('run' in data && data.run && typeof data.run === 'object') {
      raw = data.run as RawDemoRunDto;
    } else {
      raw = data as RawDemoRunDto;
    }
  }

  const normalized = normalizeDemoRun(raw);
  return {
    ...normalized,
    state: 'stopped',
    stoppedAt: normalized.stoppedAt || new Date().toISOString(),
  };
}

/**
 * Switches the active simulation scenario.
 * PATCH /api/v1/demo/runs/{runId}/scenario
 */
export async function switchDemoScenario(
  runId: string,
  scenario: DemoScenario,
  useFixtures: boolean = false
): Promise<DemoRun> {
  if (useFixtures) {
    if (fixtureActiveRun && fixtureActiveRun.runId === runId) {
      fixtureActiveRun = {
        ...fixtureActiveRun,
        scenario,
        lastEventId: `evt_fix_${Math.random().toString(36).substring(2, 8)}`,
        lastEventTime: new Date().toISOString(),
      };
      return { ...fixtureActiveRun };
    }
    fixtureActiveRun = {
      runId,
      patientId: 'P101',
      scenario,
      intervalSeconds: 5,
      state: 'running',
      startedAt: new Date().toISOString(),
      isSimulated: true,
    };
    return { ...fixtureActiveRun };
  }

  const data = await apiRequest<RawDemoRunDto | { data: RawDemoRunDto } | { run: RawDemoRunDto }>(
    `/demo/runs/${encodeURIComponent(runId)}/scenario`,
    {
      method: 'PATCH',
      body: JSON.stringify({ scenario }),
    }
  );

  let raw: RawDemoRunDto = {};
  if (data && typeof data === 'object') {
    if ('data' in data && data.data && typeof data.data === 'object') {
      raw = data.data as RawDemoRunDto;
    } else if ('run' in data && data.run && typeof data.run === 'object') {
      raw = data.run as RawDemoRunDto;
    } else {
      raw = data as RawDemoRunDto;
    }
  }

  return normalizeDemoRun(raw);
}

/**
 * Queries current demonstration run status.
 * GET /api/v1/demo/runs/{runId} or GET /api/v1/demo/runs
 */
export async function getDemoRunStatus(
  runId?: string,
  useFixtures: boolean = false
): Promise<DemoRun | null> {
  if (useFixtures) {
    return fixtureActiveRun ? { ...fixtureActiveRun } : null;
  }

  try {
    const endpoint = runId ? `/demo/runs/${encodeURIComponent(runId)}` : '/demo/runs';
    const data = await apiRequest<
      RawDemoRunDto | { data: RawDemoRunDto } | { run: RawDemoRunDto } | RawDemoRunDto[]
    >(endpoint);

    let raw: RawDemoRunDto | null = null;
    if (Array.isArray(data)) {
      raw = data.length > 0 ? data[0] : null;
    } else if (data && typeof data === 'object') {
      if ('data' in data && data.data && typeof data.data === 'object') {
        raw = data.data as RawDemoRunDto;
      } else if ('run' in data && data.run && typeof data.run === 'object') {
        raw = data.run as RawDemoRunDto;
      } else {
        raw = data as RawDemoRunDto;
      }
    }

    if (!raw) return null;
    return normalizeDemoRun(raw);
  } catch {
    return null;
  }
}
