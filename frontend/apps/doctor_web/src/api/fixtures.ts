/**
 * SMART HEALTH MONITORING SYSTEM — ISOLATED DEVELOPMENT FIXTURES
 * 
 * SPECIFICATION & GOVERNANCE:
 * 1. Used strictly when the local FastAPI gateway is offline for visual verification.
 * 2. Matches exact Kaggle dataset cohort P101–P105 (1,500 historical rows).
 * 3. Never substitute for live integration. Live integration requires active FastAPI.
 * 4. All metrics are marked SIMULATED with source 'kaggle_csv'.
 * 5. Historical timestamps naturally evaluate as 'stale' without active simulator.
 */

import type { PatientProfile, VitalsReading, PatientAlert, ClinicalMessage } from '../types';

export interface PatientFixture {
  patient: PatientProfile;
  latestVitals: VitalsReading[];
  alerts: PatientAlert[];
}

export const KAGGLE_COHORT_FIXTURES: PatientFixture[] = [
  {
    patient: {
      patientId: 'P101',
      sourcePatientId: 'P101',
      name: 'Patient P101 (Kaggle Cohort)',
      gender: 'M',
      dateOfBirth: '1979-05-14',
      heightCm: 176,
      weightKg: 78,
      assignedDoctorId: 'usr_doc_01',
    },
    latestVitals: [
      {
        metricCode: 'heart_rate',
        label: 'Heart Rate',
        value: 78,
        unit: 'bpm',
        measuredAt: '2023-10-01T08:13:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'spo2',
        label: 'SpO2',
        value: 98.4,
        unit: '%',
        measuredAt: '2023-10-01T08:13:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'temperature_f',
        label: 'Temp (°F)',
        value: 98.6,
        unit: '°F',
        measuredAt: '2023-10-01T08:13:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
    ],
    alerts: [
      {
        alertId: 'alt_p101_01',
        patientId: 'P101',
        severity: 'elevated',
        reason: 'Predefined simulated anomaly example: transient SpO2 dip with compensatory HR elevation (synthetic test pattern).',
        status: 'open',
        createdAt: '2023-10-01T08:14:00Z',
        assessmentId: 'asm_if_101',
      },
    ],
  },
  {
    patient: {
      patientId: 'P102',
      sourcePatientId: 'P102',
      name: 'Patient P102 (Kaggle Cohort)',
      gender: 'F',
      dateOfBirth: '1972-11-20',
      heightCm: 162,
      weightKg: 64,
      assignedDoctorId: 'usr_doc_01',
    },
    latestVitals: [
      {
        metricCode: 'heart_rate',
        label: 'Heart Rate',
        value: 88,
        unit: 'bpm',
        measuredAt: '2023-10-01T08:15:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'spo2',
        label: 'SpO2',
        value: 96.1,
        unit: '%',
        measuredAt: '2023-10-01T08:15:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'temperature_f',
        label: 'Temp (°F)',
        value: 99.1,
        unit: '°F',
        measuredAt: '2023-10-01T08:15:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
    ],
    alerts: [
      {
        alertId: 'alt_p102_01',
        patientId: 'P102',
        severity: 'advisory',
        reason: 'Marginal baseline drift observed during overnight monitoring window.',
        status: 'acknowledged',
        createdAt: '2023-10-01T07:45:00Z',
        acknowledgedBy: 'Dr. Sarah Jenkins, MD',
        acknowledgedAt: '2023-10-01T08:10:00Z',
        notes: 'Patient resting comfortably, continuing standard surveillance.',
      },
    ],
  },
  {
    patient: {
      patientId: 'P103',
      sourcePatientId: 'P103',
      name: 'Patient P103 (Kaggle Cohort)',
      gender: 'M',
      dateOfBirth: '1961-03-08',
      heightCm: 180,
      weightKg: 89,
      assignedDoctorId: 'usr_doc_01',
    },
    latestVitals: [
      {
        metricCode: 'heart_rate',
        label: 'Heart Rate',
        value: 112,
        unit: 'bpm',
        measuredAt: '2023-10-01T08:20:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'spo2',
        label: 'SpO2',
        value: 91.2,
        unit: '%',
        measuredAt: '2023-10-01T08:20:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'temperature_f',
        label: 'Temp (°F)',
        value: 101.4,
        unit: '°F',
        measuredAt: '2023-10-01T08:20:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
    ],
    alerts: [
      {
        alertId: 'alt_p103_01',
        patientId: 'P103',
        severity: 'critical',
        reason: 'Elevated temperature (101.4°F) with tachycardia (112 bpm) exceeding physiological review threshold.',
        status: 'open',
        createdAt: '2023-10-01T08:21:00Z',
        assessmentId: 'asm_rule_103',
      },
    ],
  },
  {
    patient: {
      patientId: 'P104',
      sourcePatientId: 'P104',
      name: 'Patient P104 (Kaggle Cohort)',
      gender: 'F',
      dateOfBirth: '1986-09-29',
      heightCm: 168,
      weightKg: 58,
      assignedDoctorId: 'usr_doc_01',
    },
    latestVitals: [
      {
        metricCode: 'heart_rate',
        label: 'Heart Rate',
        value: 68,
        unit: 'bpm',
        measuredAt: '2023-10-01T08:22:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'spo2',
        label: 'SpO2',
        value: 99.0,
        unit: '%',
        measuredAt: '2023-10-01T08:22:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'temperature_f',
        label: 'Temp (°F)',
        value: 98.2,
        unit: '°F',
        measuredAt: '2023-10-01T08:22:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
    ],
    alerts: [
      {
        alertId: 'alt_p104_01',
        patientId: 'P104',
        severity: 'info',
        reason: 'Routine sensor calibration verification check completed.',
        status: 'resolved',
        createdAt: '2023-10-01T06:30:00Z',
        acknowledgedBy: 'Dr. Sarah Jenkins, MD',
        acknowledgedAt: '2023-10-01T06:45:00Z',
        resolvedAt: '2023-10-01T07:15:00Z',
        notes: 'Electrode impedance verified within normal operating tolerance.',
      },
    ],
  },
  {
    patient: {
      patientId: 'P105',
      sourcePatientId: 'P105',
      name: 'Patient P105 (Kaggle Cohort)',
      gender: 'M',
      dateOfBirth: '1954-12-04',
      heightCm: 172,
      weightKg: 82,
      assignedDoctorId: 'usr_doc_01',
    },
    latestVitals: [
      {
        metricCode: 'heart_rate',
        label: 'Heart Rate',
        value: 82,
        unit: 'bpm',
        measuredAt: '2023-10-01T08:25:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'spo2',
        label: 'SpO2',
        value: 97.5,
        unit: '%',
        measuredAt: '2023-10-01T08:25:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
      {
        metricCode: 'temperature_f',
        label: 'Temp (°F)',
        value: 98.4,
        unit: '°F',
        measuredAt: '2023-10-01T08:25:00Z',
        freshness: 'stale',
        source: 'kaggle_csv',
        isSimulated: true,
        qualityStatus: 'valid',
      },
    ],
    alerts: [
      {
        alertId: 'alt_p105_01',
        patientId: 'P105',
        severity: 'elevated',
        reason: 'Sustained post-activity heart rate elevation above age-adjusted resting baseline.',
        status: 'open',
        createdAt: '2023-10-01T08:30:00Z',
        assessmentId: 'asm_rule_105',
      },
    ],
  },
];

/**
 * Resolves a patient fixture by identifier.
 */
export function getFixturePatientById(patientId: string): PatientFixture | undefined {
  return KAGGLE_COHORT_FIXTURES.find(
    (f) => f.patient.patientId === patientId || f.patient.sourcePatientId === patientId
  );
}

/**
 * Returns deterministic Kaggle historical series for development fixture mode.
 */
export function getFixturePatientHistory(
  patientId: string,
  metricCode: 'heart_rate' | 'spo2' | 'temperature_f' | 'temperature_c' = 'heart_rate',
  from?: string,
  to?: string
): VitalsReading[] {
  // Base hourly/daily timestamps spanning Oct 01 to Oct 06, 2023 (Kaggle dataset period)
  const timestamps = [
    '2023-10-01T08:13:00Z',
    '2023-10-01T14:30:00Z',
    '2023-10-01T20:45:00Z',
    '2023-10-02T08:00:00Z',
    '2023-10-02T16:15:00Z',
    '2023-10-03T09:30:00Z',
    '2023-10-03T18:20:00Z',
    '2023-10-04T08:45:00Z',
    '2023-10-04T15:10:00Z',
    '2023-10-05T10:00:00Z',
    '2023-10-05T19:30:00Z',
    '2023-10-06T08:20:00Z',
  ];

  // Specific profiles per patient matching dataset distribution
  const seriesData: Record<string, Record<string, number[]>> = {
    P101: {
      heart_rate: [76, 78, 80, 84, 88, 92, 85, 80, 78, 77, 79, 78],
      spo2: [98.8, 98.4, 98.2, 97.5, 96.8, 96.2, 97.4, 98.1, 98.4, 98.5, 98.6, 98.4],
      temperature_f: [98.4, 98.6, 98.7, 98.9, 99.1, 99.0, 98.8, 98.6, 98.5, 98.6, 98.7, 98.6],
    },
    P102: {
      heart_rate: [82, 85, 88, 86, 84, 87, 89, 88, 86, 87, 88, 88],
      spo2: [96.5, 96.2, 96.1, 96.4, 96.8, 96.5, 96.2, 96.1, 96.3, 96.2, 96.1, 96.1],
      temperature_f: [98.8, 99.0, 99.1, 99.0, 98.9, 99.2, 99.1, 99.1, 99.0, 99.2, 99.1, 99.1],
    },
    P103: {
      heart_rate: [88, 94, 99, 104, 110, 115, 112, 108, 102, 98, 94, 112],
      spo2: [95.2, 94.6, 93.8, 92.5, 91.0, 90.5, 91.2, 92.0, 93.4, 94.0, 94.8, 91.2],
      temperature_f: [99.2, 99.8, 100.4, 101.1, 101.8, 102.1, 101.4, 100.8, 100.1, 99.6, 99.2, 101.4],
    },
    P104: {
      heart_rate: [66, 68, 70, 69, 67, 68, 71, 70, 68, 67, 69, 68],
      spo2: [99.2, 99.0, 98.9, 99.1, 99.3, 99.0, 98.8, 99.0, 99.1, 99.2, 99.0, 99.0],
      temperature_f: [98.0, 98.2, 98.3, 98.1, 98.0, 98.2, 98.4, 98.2, 98.1, 98.2, 98.3, 98.2],
    },
    P105: {
      heart_rate: [80, 82, 84, 83, 81, 82, 85, 84, 82, 83, 81, 82],
      spo2: [97.8, 97.5, 97.4, 97.6, 97.8, 97.5, 97.2, 97.5, 97.6, 97.7, 97.4, 97.5],
      temperature_f: [98.2, 98.4, 98.5, 98.3, 98.2, 98.4, 98.6, 98.4, 98.3, 98.5, 98.4, 98.4],
    },
  };

  const patientKey = seriesData[patientId] ? patientId : 'P101';
  const targetMetricKey = metricCode === 'temperature_c' ? 'temperature_f' : metricCode;
  const values = seriesData[patientKey][targetMetricKey] || seriesData[patientKey].heart_rate;

  const unitMap: Record<string, string> = {
    heart_rate: 'bpm',
    spo2: '%',
    temperature_f: '°F',
    temperature_c: '°C',
  };

  const labelMap: Record<string, string> = {
    heart_rate: 'Heart Rate',
    spo2: 'SpO2',
    temperature_f: 'Temp (°F)',
    temperature_c: 'Temp (°C)',
  };

  let readings: VitalsReading[] = timestamps.map((ts, idx) => ({
    metricCode,
    label: labelMap[metricCode] || metricCode,
    value: values[idx % values.length],
    unit: (unitMap[metricCode] || '') as any,
    measuredAt: ts,
    freshness: 'stale', // Historical CSV records evaluate accurately as stale
    source: 'kaggle_csv',
    isSimulated: true,
    qualityStatus: 'valid',
  }));

  if (from) {
    const fromMs = new Date(from).getTime();
    if (!isNaN(fromMs)) {
      readings = readings.filter((r) => r.measuredAt && new Date(r.measuredAt).getTime() >= fromMs);
    }
  }

  if (to) {
    const toMs = new Date(to).getTime();
    if (!isNaN(toMs)) {
      readings = readings.filter((r) => r.measuredAt && new Date(r.measuredAt).getTime() <= toMs);
    }
  }

  return readings;
}

/**
 * Returns all alerts across the Kaggle development fixture cohort, sorted descending by creation time.
 */
export function getAllFixtureAlerts(patientId?: string): PatientAlert[] {
  const all: PatientAlert[] = [];
  for (const fix of KAGGLE_COHORT_FIXTURES) {
    if (!patientId || fix.patient.patientId === patientId || fix.patient.sourcePatientId === patientId) {
      all.push(...fix.alerts);
    }
  }
  return all.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
}

/**
 * Acknowledges an alert in the development fixtures (updates in-memory fixture state).
 */
export function acknowledgeFixtureAlert(alertId: string, note?: string): PatientAlert {
  for (const fix of KAGGLE_COHORT_FIXTURES) {
    const found = fix.alerts.find((a) => a.alertId === alertId);
    if (found) {
      if (found.status === 'resolved') {
        throw new Error('Invalid state transition: Cannot acknowledge a resolved alert.');
      }
      found.status = 'acknowledged';
      found.acknowledgedAt = new Date().toISOString();
      found.acknowledgedBy = 'Dr. Sarah Jenkins, MD';
      if (note) {
        found.notes = note;
      }
      return { ...found };
    }
  }
  throw new Error(`Alert "${alertId}" not found in development fixtures.`);
}

/**
 * Resolves an alert in the development fixtures (updates in-memory fixture state).
 */
export function resolveFixtureAlert(alertId: string, note?: string): PatientAlert {
  for (const fix of KAGGLE_COHORT_FIXTURES) {
    const found = fix.alerts.find((a) => a.alertId === alertId);
    if (found) {
      if (found.status === 'resolved') {
        throw new Error('Invalid state transition: Alert is already resolved.');
      }
      found.status = 'resolved';
      found.resolvedAt = new Date().toISOString();
      if (note) {
        found.notes = note;
      }
      return { ...found };
    }
  }
  throw new Error(`Alert "${alertId}" not found in development fixtures.`);
}

/**
 * Isolated development consultation messages for Kaggle cohort P101–P105.
 */
export const KAGGLE_COHORT_MESSAGES: ClinicalMessage[] = [
  {
    messageId: 'msg_p101_01',
    senderId: 'P101',
    receiverId: 'usr_doc_01',
    patientId: 'P101',
    content: 'Good morning Dr. Jenkins, I noticed my heart rate felt slightly elevated while taking the stairs.',
    createdAt: '2023-10-01T08:20:00Z',
    isFromDoctor: false,
  },
  {
    messageId: 'msg_p101_02',
    senderId: 'usr_doc_01',
    receiverId: 'P101',
    patientId: 'P101',
    content: 'Good morning. I inspected your recent telemetry feed — your vitals stabilized quickly back to baseline. Please continue resting and message us immediately if you experience dizziness or shortness of breath.',
    createdAt: '2023-10-01T08:35:00Z',
    isFromDoctor: true,
  },
  {
    messageId: 'msg_p103_01',
    senderId: 'P103',
    receiverId: 'usr_doc_01',
    patientId: 'P103',
    content: 'Hello doctor, feeling quite feverish and fatigued this morning.',
    createdAt: '2023-10-01T08:24:00Z',
    isFromDoctor: false,
  },
  {
    messageId: 'msg_p103_02',
    senderId: 'usr_doc_01',
    receiverId: 'P103',
    patientId: 'P103',
    content: 'I see your recorded temperature was 101.4°F. I have acknowledged the surveillance alert. Please remain hydrated, take prescribed antipyretics, and we will monitor your telemetry.',
    createdAt: '2023-10-01T08:42:00Z',
    isFromDoctor: true,
  },
];

/**
 * Retrieves consultation messages from development fixtures for a given patient.
 */
export function getFixtureMessages(patientId?: string): ClinicalMessage[] {
  const filtered = patientId
    ? KAGGLE_COHORT_MESSAGES.filter(
        (m) => m.patientId === patientId || m.receiverId === patientId || m.senderId === patientId
      )
    : [...KAGGLE_COHORT_MESSAGES];

  return filtered.sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
}

/**
 * Sends a message in development fixture mode (appends to in-memory fixtures).
 */
export function sendFixtureMessage(
  receiverId: string,
  content: string,
  currentUserId: string = 'usr_doc_01'
): ClinicalMessage {
  const newMsg: ClinicalMessage = {
    messageId: `msg_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
    senderId: currentUserId,
    receiverId,
    patientId: receiverId,
    content: content.trim(),
    createdAt: new Date().toISOString(),
    isFromDoctor: true,
  };
  KAGGLE_COHORT_MESSAGES.push(newMsg);
  return { ...newMsg };
}

/**
 * Resets development fixture alerts and messages back to initial benchmark baseline.
 */
export function resetFixtureData(): void {
  for (const fix of KAGGLE_COHORT_FIXTURES) {
    for (const alert of fix.alerts) {
      if (alert.alertId === 'alt_p101_01' || alert.alertId === 'alt_p103_01' || alert.alertId === 'alt_p105_01') {
        alert.status = 'open';
        alert.acknowledgedAt = undefined;
        alert.acknowledgedBy = undefined;
        alert.resolvedAt = undefined;
        alert.notes = undefined;
      } else if (alert.alertId === 'alt_p102_01') {
        alert.status = 'acknowledged';
        alert.acknowledgedBy = 'Dr. Sarah Jenkins, MD';
        alert.acknowledgedAt = '2023-10-01T08:00:00Z';
        alert.resolvedAt = undefined;
        alert.notes = undefined;
      } else if (alert.alertId === 'alt_p104_01') {
        alert.status = 'resolved';
      }
    }
  }

  // Reset messages back to initial 4
  KAGGLE_COHORT_MESSAGES.length = 0;
  KAGGLE_COHORT_MESSAGES.push(
    {
      messageId: 'msg_p101_01',
      senderId: 'P101',
      receiverId: 'usr_doc_01',
      patientId: 'P101',
      content: 'Good morning Dr. Jenkins, I noticed my heart rate felt slightly elevated while taking the stairs.',
      createdAt: '2023-10-01T08:20:00Z',
      isFromDoctor: false,
    },
    {
      messageId: 'msg_p101_02',
      senderId: 'usr_doc_01',
      receiverId: 'P101',
      patientId: 'P101',
      content: 'Good morning. I inspected your recent telemetry feed — your vitals stabilized quickly back to baseline. Please continue resting and message us immediately if you experience dizziness or shortness of breath.',
      createdAt: '2023-10-01T08:35:00Z',
      isFromDoctor: true,
    },
    {
      messageId: 'msg_p103_01',
      senderId: 'P103',
      receiverId: 'usr_doc_01',
      patientId: 'P103',
      content: 'Hello doctor, feeling quite feverish and fatigued this morning.',
      createdAt: '2023-10-01T08:24:00Z',
      isFromDoctor: false,
    },
    {
      messageId: 'msg_p103_02',
      senderId: 'usr_doc_01',
      receiverId: 'P103',
      patientId: 'P103',
      content: 'I see your recorded temperature was 101.4°F. I have acknowledged the surveillance alert. Please remain hydrated, take prescribed antipyretics, and we will monitor your telemetry.',
      createdAt: '2023-10-01T08:42:00Z',
      isFromDoctor: true,
    }
  );
}
