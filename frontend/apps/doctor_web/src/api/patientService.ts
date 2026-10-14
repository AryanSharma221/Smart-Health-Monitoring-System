/**
 * SMART HEALTH MONITORING SYSTEM — PATIENTS, VITALS & ALERTS SERVICE
 * 
 * Interacts with agreed FastAPI endpoints:
 * - GET /api/v1/me
 * - GET /api/v1/patients
 * - GET /api/v1/patients/{id}/vitals/latest
 * - GET /api/v1/patients/{id}/alerts
 */

import { apiRequest } from './client';
import type {
  PatientProfile,
  PatientAlert,
  VitalsReading,
  MetricCode,
  MetricUnit,
  FreshnessState,
  TelemetrySource,
  UserSession,
  AlertSeverity,
  AlertStatus,
} from '../types';

/** Configured freshness window in seconds (60 seconds per Member 1/2 contract) */
export const FRESHNESS_THRESHOLD_SECONDS = 60;

const METRIC_LABELS: Record<MetricCode, string> = {
  heart_rate: 'Heart Rate',
  spo2: 'SpO2',
  temperature_f: 'Temp (°F)',
  temperature_c: 'Temp (°C)',
  respiratory_rate: 'Resp. Rate',
  systolic_bp: 'Systolic BP',
  diastolic_bp: 'Diastolic BP',
};

const METRIC_DEFAULT_UNITS: Record<MetricCode, MetricUnit> = {
  heart_rate: 'bpm',
  spo2: '%',
  temperature_f: '°F',
  temperature_c: '°C',
  respiratory_rate: 'breaths/min',
  systolic_bp: 'mmHg',
  diastolic_bp: 'mmHg',
};

/**
 * Calculates freshness of a reading based on its measured timestamp.
 * If timestamp is null or invalid, returns 'unavailable'.
 * If timestamp age <= threshold, returns 'fresh'.
 * If timestamp age > threshold, returns 'stale'.
 */
export function calculateFreshness(
  measuredAt: string | null | undefined,
  thresholdSeconds: number = FRESHNESS_THRESHOLD_SECONDS
): FreshnessState {
  if (!measuredAt) return 'unavailable';

  try {
    const measuredTime = new Date(measuredAt).getTime();
    if (isNaN(measuredTime)) return 'stale'; // Fallback for raw non-ISO string

    const now = Date.now();
    const ageSeconds = (now - measuredTime) / 1000;

    if (ageSeconds < 0) return 'fresh'; // Tolerant of small clock skew
    return ageSeconds <= thresholdSeconds ? 'fresh' : 'stale';
  } catch {
    return 'unavailable';
  }
}

/** Raw API Patient structure from FastAPI backend */
interface RawPatientDto {
  patient_id?: string;
  patientId?: string;
  id?: string;
  name?: string;
  full_name?: string;
  source_patient_id?: string;
  sourcePatientId?: string;
  date_of_birth?: string;
  gender?: 'M' | 'F' | 'Other' | 'Unknown';
  height_cm?: number;
  weight_kg?: number;
  assigned_doctor_id?: string;
}

/** Raw API Metric structure */
interface RawMetricDto {
  metric_code?: string;
  metricCode?: string;
  value?: number | null;
  unit?: string;
  measured_at?: string | null;
  received_at?: string | null;
  source?: string;
  is_simulated?: boolean;
  quality_status?: 'valid' | 'suspect' | 'out_of_range';
  freshness?: FreshnessState;
}

/** Raw API Latest Vitals wrapper */
interface RawLatestVitalsDto {
  patient_id?: string;
  patientId?: string;
  metrics?: RawMetricDto[];
}

/** Raw API Alert structure */
export interface RawAlertDto {
  alert_id?: string;
  alertId?: string;
  id?: string;
  patient_id?: string;
  patientId?: string;
  severity?: 'critical' | 'elevated' | 'advisory' | 'info';
  reason?: string;
  message?: string;
  status?: 'open' | 'acknowledged' | 'resolved';
  created_at?: string;
  createdAt?: string;
  acknowledged_by?: string;
  acknowledged_at?: string;
  resolved_at?: string;
  notes?: string;
  assessment_id?: string;
}

/**
 * Normalizes raw patient DTO into typed PatientProfile.
 */
function normalizePatient(dto: RawPatientDto): PatientProfile {
  const patientId = dto.patient_id || dto.patientId || dto.id || 'P_UNKNOWN';
  return {
    patientId,
    sourcePatientId: dto.source_patient_id || dto.sourcePatientId || patientId,
    name: dto.name || dto.full_name || `Patient ${patientId}`,
    dateOfBirth: dto.date_of_birth,
    gender: dto.gender || 'Unknown',
    heightCm: dto.height_cm,
    weightKg: dto.weight_kg,
    assignedDoctorId: dto.assigned_doctor_id,
  };
}

/**
 * Normalizes raw metric DTO into typed VitalsReading.
 */
function normalizeMetric(dto: RawMetricDto): VitalsReading {
  const metricCode = (dto.metric_code || dto.metricCode || 'heart_rate') as MetricCode;
  const label = METRIC_LABELS[metricCode] || metricCode;
  const unit = (dto.unit || METRIC_DEFAULT_UNITS[metricCode] || '') as MetricUnit;
  const measuredAt = dto.measured_at || null;

  // Prefer backend-provided freshness if present; otherwise calculate against threshold
  const freshness: FreshnessState =
    dto.freshness && ['fresh', 'stale', 'unavailable', 'disconnected'].includes(dto.freshness)
      ? dto.freshness
      : calculateFreshness(measuredAt);

  return {
    metricCode,
    label,
    value: typeof dto.value === 'number' && !isNaN(dto.value) ? dto.value : null,
    unit,
    measuredAt,
    freshness,
    source: (dto.source || 'kaggle_csv') as TelemetrySource,
    isSimulated: dto.is_simulated !== false,
    qualityStatus: dto.quality_status || 'valid',
  };
}

/**
 * Normalizes raw alert DTO into typed PatientAlert.
 */
export function normalizeAlert(dto: RawAlertDto, fallbackPatientId: string): PatientAlert {
  const rawStatus = (dto.status || '').toLowerCase();
  let status: AlertStatus = 'open';
  if (rawStatus === 'acknowledged') {
    status = 'acknowledged';
  } else if (rawStatus === 'resolved') {
    status = 'resolved';
  } else if (rawStatus === 'new' || rawStatus === 'open') {
    status = 'open';
  }

  const rawSeverity = (dto.severity || '').toLowerCase();
  let severity: AlertSeverity = 'elevated';
  if (rawSeverity === 'critical') {
    severity = 'critical';
  } else if (rawSeverity === 'high' || rawSeverity === 'elevated' || rawSeverity === 'medium') {
    severity = 'elevated';
  } else if (rawSeverity === 'low' || rawSeverity === 'advisory') {
    severity = 'advisory';
  } else if (rawSeverity === 'info') {
    severity = 'info';
  }

  return {
    alertId: dto.alert_id || dto.alertId || dto.id || `alt_${Math.random().toString(36).substring(2, 9)}`,
    patientId: dto.patient_id || dto.patientId || fallbackPatientId,
    severity,
    reason: dto.reason || dto.message || 'Anomaly pattern flagged for review',
    status,
    createdAt: dto.created_at || dto.createdAt || new Date().toISOString(),
    acknowledgedBy: dto.acknowledged_by,
    acknowledgedAt: dto.acknowledged_at,
    resolvedAt: dto.resolved_at,
    notes: dto.notes,
    assessmentId: dto.assessment_id,
  };
}

/**
 * Fetches the authenticated clinician profile.
 * GET /api/v1/me
 */
export async function getClinicianProfile(): Promise<UserSession> {
  const data = await apiRequest<{
    user_id?: string;
    userId?: string;
    id?: string;
    email?: string;
    name?: string;
    role?: 'doctor' | 'patient' | 'admin';
    license_number?: string;
  }>('/me');

  return {
    userId: data.user_id || data.userId || data.id || 'usr_unknown',
    email: data.email || '',
    name: data.name || 'Dr. Assigned Clinician',
    role: data.role || 'doctor',
    licenseNumber: data.license_number,
  };
}

/**
 * Fetches the list of assigned patients for the authenticated doctor.
 * GET /api/v1/patients
 */
export async function getAssignedPatients(): Promise<PatientProfile[]> {
  const data = await apiRequest<RawPatientDto[] | { data: RawPatientDto[] } | { patients: RawPatientDto[] }>('/patients');

  let list: RawPatientDto[] = [];
  if (Array.isArray(data)) {
    list = data;
  } else if (data && typeof data === 'object') {
    if ('data' in data && Array.isArray(data.data)) {
      list = data.data;
    } else if ('patients' in data && Array.isArray(data.patients)) {
      list = data.patients;
    }
  }

  return list.map(normalizePatient);
}

/**
 * Fetches latest vital readings for a single patient.
 * GET /api/v1/patients/{id}/vitals/latest
 */
export async function getPatientLatestVitals(patientId: string): Promise<VitalsReading[]> {
  const data = await apiRequest<RawLatestVitalsDto | RawMetricDto[]>(`/patients/${encodeURIComponent(patientId)}/vitals/latest`);

  let metrics: RawMetricDto[] = [];
  if (Array.isArray(data)) {
    metrics = data;
  } else if (data && typeof data === 'object' && Array.isArray(data.metrics)) {
    metrics = data.metrics;
  }

  return metrics.map(normalizeMetric);
}

/**
 * Fetches alerts for a single patient.
 * GET /api/v1/patients/{id}/alerts
 */
export async function getPatientAlerts(patientId: string): Promise<PatientAlert[]> {
  const data = await apiRequest<
    RawAlertDto[] | { data: RawAlertDto[] } | { alerts: RawAlertDto[] } | { items: RawAlertDto[] }
  >(`/patients/${encodeURIComponent(patientId)}/alerts`);

  let list: RawAlertDto[] = [];
  if (Array.isArray(data)) {
    list = data;
  } else if (data && typeof data === 'object') {
    if ('items' in data && Array.isArray(data.items)) {
      list = data.items;
    } else if ('data' in data && Array.isArray(data.data)) {
      list = data.data;
    } else if ('alerts' in data && Array.isArray(data.alerts)) {
      list = data.alerts;
    }
  }

  return list.map((a) => normalizeAlert(a, patientId));
}

/**
 * Query filters for historical vitals endpoint.
 * GET /api/v1/patients/{id}/vitals?metric_code=&from=&to=
 */
export interface VitalHistoryQuery {
  metricCode?: MetricCode;
  from?: string;
  to?: string;
}

/**
 * Fetches a single patient profile by identifier.
 * First queries GET /api/v1/patients/{id}; falls back to resolving from GET /api/v1/patients.
 */
export async function getPatientById(patientId: string): Promise<PatientProfile> {
  try {
    const data = await apiRequest<RawPatientDto>(`/patients/${encodeURIComponent(patientId)}`);
    return normalizePatient(data);
  } catch (err: unknown) {
    // If single endpoint returns 404 or fails, resolve from assigned patients collection
    const patients = await getAssignedPatients();
    const match = patients.find(
      (p) => p.patientId === patientId || p.sourcePatientId === patientId
    );
    if (match) return match;
    throw err;
  }
}

/**
 * Fetches historical vital readings for a patient.
 * GET /api/v1/patients/{id}/vitals?metric_code=&from=&to=
 */
export async function getPatientVitalHistory(
  patientId: string,
  query?: VitalHistoryQuery
): Promise<VitalsReading[]> {
  const params = new URLSearchParams();
  if (query?.metricCode) {
    params.append('metric_code', query.metricCode);
  }
  if (query?.from) {
    params.append('from', query.from);
  }
  if (query?.to) {
    params.append('to', query.to);
  }

  const qs = params.toString() ? `?${params.toString()}` : '';
  const data = await apiRequest<RawMetricDto[] | { data: RawMetricDto[] } | { metrics: RawMetricDto[] }>(
    `/patients/${encodeURIComponent(patientId)}/vitals${qs}`
  );

  let metrics: RawMetricDto[] = [];
  if (Array.isArray(data)) {
    metrics = data;
  } else if (data && typeof data === 'object') {
    if ('data' in data && Array.isArray(data.data)) {
      metrics = data.data;
    } else if ('metrics' in data && Array.isArray(data.metrics)) {
      metrics = data.metrics;
    }
  }

  return metrics.map(normalizeMetric);
}

