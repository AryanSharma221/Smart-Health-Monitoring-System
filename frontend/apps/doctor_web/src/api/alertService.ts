/**
 * SMART HEALTH MONITORING SYSTEM — CLINICAL SURVEILLANCE & ALERTS SERVICE
 * 
 * Interacts with agreed FastAPI endpoints:
 * - GET /api/v1/patients/{id}/alerts (patient-specific alert query)
 * - POST /api/v1/alerts/{id}/acknowledge (transition 'open' -> 'acknowledged' with optional note)
 * - POST /api/v1/alerts/{id}/resolve (transition -> 'resolved' with optional note)
 * 
 * STRICT ARCHITECTURAL CONSTRAINTS:
 * 1. SIMULATED DATA — NOT FOR MEDICAL USE.
 * 2. Scoped strictly to authorized clinician's assigned patients cohort.
 * 3. Does not invent a system-wide endpoint; aggregates via assigned patients list.
 * 4. State mutations update only after confirmed server response or in isolated fixture mode.
 * 5. Partial errors across patient feeds are isolated and preserved.
 */

import { apiRequest } from './client';
import {
  getAssignedPatients,
  getPatientAlerts,
  normalizeAlert,
  type RawAlertDto,
} from './patientService';
import {
  getAllFixtureAlerts,
  acknowledgeFixtureAlert,
  resolveFixtureAlert,
  KAGGLE_COHORT_FIXTURES,
} from './fixtures';
import type { PatientAlert, PatientProfile, AlertStatus } from '../types';

export interface AlertActionPayload {
  note?: string;
}

export interface FetchAlertsOptions {
  patientId?: string;
  useFixtures?: boolean;
}

export interface FetchAlertsResult {
  alerts: PatientAlert[];
  patients: PatientProfile[];
  patientMap: Map<string, PatientProfile>;
  partialErrors: Record<string, string>;
  isFixtureMode: boolean;
}

/**
 * Fetches alerts across assigned patients with optional patient filtering.
 * Respects backend contract: aggregates GET /api/v1/patients/{id}/alerts per assigned patient.
 */
export async function fetchAssignedAlerts(
  options: FetchAlertsOptions = {}
): Promise<FetchAlertsResult> {
  const { patientId, useFixtures = false } = options;

  if (useFixtures) {
    const alerts = getAllFixtureAlerts(patientId);
    const patients = KAGGLE_COHORT_FIXTURES.map((f) => f.patient);
    const patientMap = new Map<string, PatientProfile>();
    for (const p of patients) {
      patientMap.set(p.patientId, p);
    }

    return {
      alerts,
      patients,
      patientMap,
      partialErrors: {},
      isFixtureMode: true,
    };
  }

  // Live Gateway Mode: Fetch assigned patients first
  const patients = await getAssignedPatients();
  const patientMap = new Map<string, PatientProfile>();
  for (const p of patients) {
    patientMap.set(p.patientId, p);
  }

  const targetPatients = patientId
    ? patients.filter((p) => p.patientId === patientId || p.sourcePatientId === patientId)
    : patients;

  const partialErrors: Record<string, string> = {};
  const alertLists: PatientAlert[][] = [];

  const promises = targetPatients.map(async (patient) => {
    try {
      const pAlerts = await getPatientAlerts(patient.patientId);
      alertLists.push(pAlerts);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query alerts for patient';
      partialErrors[patient.patientId] = msg;
    }
  });

  await Promise.all(promises);

  const flatAlerts = alertLists.flat();
  // Sort descending by creation date (stable sort)
  flatAlerts.sort((a, b) => {
    const timeA = new Date(a.createdAt).getTime() || 0;
    const timeB = new Date(b.createdAt).getTime() || 0;
    return timeB - timeA;
  });

  return {
    alerts: flatAlerts,
    patients,
    patientMap,
    partialErrors,
    isFixtureMode: false,
  };
}

/**
 * Acknowledges an open alert.
 * POST /api/v1/alerts/{id}/acknowledge
 */
export async function acknowledgeAlert(
  alertId: string,
  payload?: AlertActionPayload,
  useFixtures: boolean = false
): Promise<PatientAlert> {
  if (useFixtures) {
    return acknowledgeFixtureAlert(alertId, payload?.note);
  }

  const data = await apiRequest<RawAlertDto | { data: RawAlertDto } | { alert: RawAlertDto }>(
    `/alerts/${encodeURIComponent(alertId)}/acknowledge`,
    {
      method: 'POST',
      body: JSON.stringify(payload?.note ? { note: payload.note } : {}),
    }
  );

  let raw: RawAlertDto = {};
  if (data && typeof data === 'object') {
    if ('data' in data && data.data && typeof data.data === 'object') {
      raw = data.data as RawAlertDto;
    } else if ('alert' in data && data.alert && typeof data.alert === 'object') {
      raw = data.alert as RawAlertDto;
    } else {
      raw = data as RawAlertDto;
    }
  }

  const normalized = normalizeAlert(raw, raw.patient_id || raw.patientId || '');
  return {
    ...normalized,
    alertId: normalized.alertId && !normalized.alertId.startsWith('alt_') ? normalized.alertId : alertId,
    status: (raw.status as AlertStatus) || 'acknowledged',
    acknowledgedAt: raw.acknowledged_at || normalized.acknowledgedAt || new Date().toISOString(),
    acknowledgedBy: raw.acknowledged_by || normalized.acknowledgedBy || 'Assigned Clinician',
    notes: payload?.note || normalized.notes,
  };
}

/**
 * Resolves an alert.
 * POST /api/v1/alerts/{id}/resolve
 */
export async function resolveAlert(
  alertId: string,
  payload?: AlertActionPayload,
  useFixtures: boolean = false
): Promise<PatientAlert> {
  if (useFixtures) {
    return resolveFixtureAlert(alertId, payload?.note);
  }

  const data = await apiRequest<RawAlertDto | { data: RawAlertDto } | { alert: RawAlertDto }>(
    `/alerts/${encodeURIComponent(alertId)}/resolve`,
    {
      method: 'POST',
      body: JSON.stringify(payload?.note ? { note: payload.note } : {}),
    }
  );

  let raw: RawAlertDto = {};
  if (data && typeof data === 'object') {
    if ('data' in data && data.data && typeof data.data === 'object') {
      raw = data.data as RawAlertDto;
    } else if ('alert' in data && data.alert && typeof data.alert === 'object') {
      raw = data.alert as RawAlertDto;
    } else {
      raw = data as RawAlertDto;
    }
  }

  const normalized = normalizeAlert(raw, raw.patient_id || raw.patientId || '');
  return {
    ...normalized,
    alertId: normalized.alertId && !normalized.alertId.startsWith('alt_') ? normalized.alertId : alertId,
    status: (raw.status as AlertStatus) || 'resolved',
    resolvedAt: raw.resolved_at || normalized.resolvedAt || new Date().toISOString(),
    notes: payload?.note || normalized.notes,
  };
}
