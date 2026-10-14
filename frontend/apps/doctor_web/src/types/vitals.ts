/**
 * SMART HEALTH MONITORING SYSTEM — VITALS & TELEMETRY CONTRACTS
 * 
 * CRITICAL HEALTHCARE CONSTRAINTS:
 * 1. SIMULATED DATA — NOT FOR MEDICAL USE.
 * 2. Missing readings must remain 'unavailable' / null. Never substitute 0 or fake "normal" values.
 * 3. Kaggle historical data contains ONLY: heart_rate, spo2, temperature_f.
 * 4. Respiratory rate & BP are supported only in the live synthetic simulator.
 * 5. Isolation Forest outputs are anomaly scores, NEVER medical diagnoses.
 */

export type MetricCode =
  | 'heart_rate'
  | 'spo2'
  | 'temperature_f'
  | 'temperature_c'
  | 'respiratory_rate'
  | 'systolic_bp'
  | 'diastolic_bp';

export type MetricUnit =
  | 'bpm'
  | '%'
  | '°F'
  | '°C'
  | 'breaths/min'
  | 'mmHg';

/**
 * Data provenance source.
 * 'kaggle_csv': 1,500 historical rows across patients P101–P105.
 * 'demo-simulator': Live generated synthetic telemetry stream.
 */
export type TelemetrySource = 'kaggle_csv' | 'demo-simulator' | 'system_seed';

/**
 * Freshness status of telemetry readings.
 * - fresh: Received within recent valid time window.
 * - stale: Timestamp exceeds freshness threshold (> configured duration).
 * - unavailable: Metric was not measured / absent in source (DO NOT display 0).
 * - disconnected: Gateway or telemetry stream connection interrupted.
 */
export type FreshnessState = 'fresh' | 'stale' | 'unavailable' | 'disconnected';

export interface VitalsReading {
  /** Metric identifier */
  metricCode: MetricCode;
  /** Label for display (e.g. "Heart Rate", "Oxygen Saturation") */
  label: string;
  /** Numeric value; null when unavailable. NEVER substitute 0 for missing values. */
  value: number | null;
  /** Measurement unit */
  unit: MetricUnit;
  /** ISO-8601 string or source timestamp string */
  measuredAt: string | null;
  /** Freshness state of this metric */
  freshness: FreshnessState;
  /** Source provenance */
  source: TelemetrySource;
  /** Flag indicating simulated data */
  isSimulated: boolean;
  /** Quality status or verification flags */
  qualityStatus?: 'valid' | 'suspect' | 'out_of_range';
}

/**
 * ML Anomaly Assessment Result (Member 3 package).
 * NOTE: This is software anomaly detection only, NOT a clinical diagnosis.
 */
export type AnomalyResultStatus = 'normal_like' | 'anomalous' | 'insufficient_data';

export interface AnomalyAssessment {
  assessmentId: string;
  patientId: string;
  modelVersion: string;
  result: AnomalyResultStatus;
  anomalyScore: number;
  timeWindowStart: string;
  timeWindowEnd: string;
  featureSummary: Record<string, number>;
  isSimulated: boolean;
  explanation: string[];
}
