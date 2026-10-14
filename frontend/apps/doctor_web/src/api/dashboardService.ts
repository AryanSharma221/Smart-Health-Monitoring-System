/**
 * SMART HEALTH MONITORING SYSTEM — DASHBOARD & DIRECTORY ORCHESTRATION SERVICE
 * 
 * Aggregates authorized backend responses into clinical workstation view models:
 * - Patient assigned list (GET /api/v1/patients)
 * - Latest vitals per patient (GET /api/v1/patients/{id}/vitals/latest)
 * - Alerts per patient (GET /api/v1/patients/{id}/alerts)
 * - Clinician profile (GET /api/v1/me)
 * 
 * STRICT CLINICAL RULES:
 * 1. Counts and lists are derived strictly from authorized API responses.
 * 2. Never displays zero prior to request completion.
 * 3. Never hardcodes metrics or counts.
 * 4. Tracks vitals and alert request failures independently per patient feed.
 * 5. Reusable across Overview and Patient Directory views.
 */

import {
  getAssignedPatients,
  getPatientLatestVitals,
  getPatientAlerts,
  getClinicianProfile,
} from './patientService';
import { KAGGLE_COHORT_FIXTURES } from './fixtures';
import type {
  PatientProfile,
  VitalsReading,
  PatientAlert,
  FreshnessState,
  UserSession,
} from '../types';

export interface DashboardPatientRow {
  patient: PatientProfile;
  latestVitals: VitalsReading[];
  vitalsError?: string;
  alerts: PatientAlert[];
  alertsError?: string;
  openAlertsCount: number;
  feedFreshness: FreshnessState;
  mostRecentMeasurementTime: string | null;
}

export interface DashboardOperationalSummary {
  assignedPatientsCount: number | null;
  openAlertsCount: number | null;
  freshFeedsCount: number | null;
  staleOrUnavailableCount: number | null;
}

export interface DashboardOverviewData {
  clinician: UserSession | null;
  patientRows: DashboardPatientRow[];
  reviewAlerts: PatientAlert[];
  summary: DashboardOperationalSummary;
  lastRefreshed: string | null;
  apiConnected: boolean;
  wsConfigured: boolean;
  isFixtureMode: boolean;
  errorMessage?: string;
}

/**
 * Derives operational feed freshness for a patient based on their latest readings.
 */
export function deriveFeedFreshness(
  vitals: VitalsReading[],
  vitalsError?: string
): FreshnessState {
  if (vitalsError || !vitals || vitals.length === 0) {
    return 'unavailable';
  }

  // If any active vital is fresh, feed is fresh
  if (vitals.some((v) => v.freshness === 'fresh')) {
    return 'fresh';
  }

  // If any vital has recorded stale value, feed is stale
  if (vitals.some((v) => v.freshness === 'stale')) {
    return 'stale';
  }

  if (vitals.some((v) => v.freshness === 'disconnected')) {
    return 'disconnected';
  }

  return 'unavailable';
}

/**
 * Resolves most recent measurement time across a patient's latest vitals.
 */
export function resolveLatestMeasurementTime(vitals: VitalsReading[]): string | null {
  if (!vitals || vitals.length === 0) return null;

  let latestTime: string | null = null;
  let latestMs = 0;

  for (const v of vitals) {
    if (v.measuredAt) {
      const ms = new Date(v.measuredAt).getTime();
      if (!isNaN(ms) && ms > latestMs) {
        latestMs = ms;
        latestTime = v.measuredAt;
      } else if (!latestTime) {
        latestTime = v.measuredAt; // fallback if non-ISO string
      }
    }
  }

  return latestTime;
}

/**
 * Fetches unified patient feed rows across patients, latest vitals, and alerts.
 * Supports both live FastAPI gateway querying and isolated Kaggle P101–P105 development fixtures.
 */
export async function fetchPatientRows(useFixtures: boolean): Promise<DashboardPatientRow[]> {
  if (useFixtures) {
    return KAGGLE_COHORT_FIXTURES.map((fix) => {
      const openAlertsCount = fix.alerts.filter((a) => a.status === 'open').length;
      const feedFreshness = deriveFeedFreshness(fix.latestVitals);
      const mostRecentMeasurementTime = resolveLatestMeasurementTime(fix.latestVitals);

      return {
        patient: fix.patient,
        latestVitals: fix.latestVitals,
        alerts: fix.alerts,
        openAlertsCount,
        feedFreshness,
        mostRecentMeasurementTime,
      };
    });
  }

  // 1. Fetch assigned patients from GET /api/v1/patients
  const patients = await getAssignedPatients();

  // 2. Concurrently fetch vitals and alerts for all assigned patients
  const vitalsPromises = patients.map((p) =>
    getPatientLatestVitals(p.patientId)
      .then((vitals) => ({ patientId: p.patientId, vitals, error: undefined }))
      .catch((err: Error) => ({
        patientId: p.patientId,
        vitals: [] as VitalsReading[],
        error: err.message || 'Unable to retrieve vitals',
      }))
  );

  const alertsPromises = patients.map((p) =>
    getPatientAlerts(p.patientId)
      .then((alerts) => ({ patientId: p.patientId, alerts, error: undefined }))
      .catch((err: Error) => ({
        patientId: p.patientId,
        alerts: [] as PatientAlert[],
        error: err.message || 'Unable to retrieve alerts',
      }))
  );

  const [vitalsResults, alertsResults] = await Promise.all([
    Promise.all(vitalsPromises),
    Promise.all(alertsPromises),
  ]);

  const vitalsMap = new Map<string, { vitals: VitalsReading[]; error?: string }>();
  for (const res of vitalsResults) {
    vitalsMap.set(res.patientId, { vitals: res.vitals, error: res.error });
  }

  const alertsMap = new Map<string, { alerts: PatientAlert[]; error?: string }>();
  for (const res of alertsResults) {
    alertsMap.set(res.patientId, { alerts: res.alerts, error: res.error });
  }

  // 3. Assemble patient rows preserving per-feed partial error metadata
  return patients.map((patient) => {
    const vInfo = vitalsMap.get(patient.patientId) || { vitals: [] };
    const aInfo = alertsMap.get(patient.patientId) || { alerts: [] };
    const pAlerts = aInfo.alerts;
    const openAlertsCount = pAlerts.filter((a) => a.status === 'open').length;
    const feedFreshness = deriveFeedFreshness(vInfo.vitals, vInfo.error);
    const mostRecentMeasurementTime = resolveLatestMeasurementTime(vInfo.vitals);

    return {
      patient,
      latestVitals: vInfo.vitals,
      vitalsError: vInfo.error,
      alerts: pAlerts,
      alertsError: aInfo.error,
      openAlertsCount,
      feedFreshness,
      mostRecentMeasurementTime,
    };
  });
}

/**
 * Builds DashboardOverviewData from isolated development fixtures (Kaggle cohort P101–P105).
 */
export function buildFixtureOverviewData(currentUser?: UserSession | null): DashboardOverviewData {
  const patientRows: DashboardPatientRow[] = KAGGLE_COHORT_FIXTURES.map((fix) => {
    const openAlertsCount = fix.alerts.filter((a) => a.status === 'open').length;
    const feedFreshness = deriveFeedFreshness(fix.latestVitals);
    const mostRecentMeasurementTime = resolveLatestMeasurementTime(fix.latestVitals);

    return {
      patient: fix.patient,
      latestVitals: fix.latestVitals,
      alerts: fix.alerts,
      openAlertsCount,
      feedFreshness,
      mostRecentMeasurementTime,
    };
  });

  const allAlerts: PatientAlert[] = [];
  for (const row of patientRows) {
    for (const a of row.alerts) {
      if (a.status === 'open') {
        allAlerts.push(a);
      }
    }
  }

  const freshFeedsCount = patientRows.filter((r) => r.feedFreshness === 'fresh').length;
  const staleOrUnavailableCount = patientRows.filter(
    (r) => r.feedFreshness === 'stale' || r.feedFreshness === 'unavailable' || r.feedFreshness === 'disconnected'
  ).length;

  return {
    clinician: currentUser || {
      userId: 'usr_doc_01',
      name: 'Dr. Sarah Jenkins, MD',
      email: 'doctor@hospital.org',
      role: 'doctor',
      licenseNumber: 'MD-94021',
    },
    patientRows,
    reviewAlerts: allAlerts,
    summary: {
      assignedPatientsCount: patientRows.length,
      openAlertsCount: allAlerts.length,
      freshFeedsCount,
      staleOrUnavailableCount,
    },
    lastRefreshed: new Date().toISOString(),
    apiConnected: false,
    wsConfigured: false,
    isFixtureMode: true,
  };
}

/**
 * Fetches dashboard overview from live FastAPI gateway.
 */
export async function fetchLiveDashboardOverview(): Promise<DashboardOverviewData> {
  let clinician: UserSession | null = null;
  try {
    clinician = await getClinicianProfile();
  } catch {
    // Non-fatal if session already has user
  }

  const patientRows = await fetchPatientRows(false);

  const reviewAlerts: PatientAlert[] = [];
  for (const row of patientRows) {
    for (const a of row.alerts) {
      if (a.status === 'open') {
        reviewAlerts.push(a);
      }
    }
  }

  reviewAlerts.sort((a, b) => {
    const timeA = new Date(a.createdAt).getTime() || 0;
    const timeB = new Date(b.createdAt).getTime() || 0;
    return timeB - timeA;
  });

  const freshFeedsCount = patientRows.filter((r) => r.feedFreshness === 'fresh').length;
  const staleOrUnavailableCount = patientRows.filter(
    (r) => r.feedFreshness === 'stale' || r.feedFreshness === 'unavailable' || r.feedFreshness === 'disconnected'
  ).length;

  return {
    clinician,
    patientRows,
    reviewAlerts,
    summary: {
      assignedPatientsCount: patientRows.length,
      openAlertsCount: reviewAlerts.length,
      freshFeedsCount,
      staleOrUnavailableCount,
    },
    lastRefreshed: new Date().toISOString(),
    apiConnected: true,
    wsConfigured: false,
    isFixtureMode: false,
  };
}
