import test from 'node:test';
import assert from 'node:assert';
import {
  deriveFeedFreshness,
  resolveLatestMeasurementTime,
  fetchPatientRows,
} from '../src/api/dashboardService';
import type { VitalsReading } from '../src/types';

test('deriveFeedFreshness correctly prioritizes fresh > stale > unavailable', () => {
  // Empty vitals -> unavailable
  assert.strictEqual(deriveFeedFreshness([]), 'unavailable');

  // Error present -> unavailable
  assert.strictEqual(deriveFeedFreshness([], 'Network timeout'), 'unavailable');

  // All stale vitals -> stale
  const staleVitals: VitalsReading[] = [
    {
      metricCode: 'heart_rate',
      label: 'Heart Rate',
      value: 74,
      unit: 'bpm',
      measuredAt: '2023-10-01T08:13:00Z',
      freshness: 'stale',
      source: 'kaggle_csv',
      isSimulated: true,
      qualityStatus: 'valid',
    },
  ];
  assert.strictEqual(deriveFeedFreshness(staleVitals), 'stale');

  // At least one fresh vital -> fresh
  const mixedVitals: VitalsReading[] = [
    ...staleVitals,
    {
      metricCode: 'spo2',
      label: 'SpO2',
      value: 98,
      unit: '%',
      measuredAt: new Date().toISOString(),
      freshness: 'fresh',
      source: 'demo_simulator',
      isSimulated: true,
      qualityStatus: 'valid',
    },
  ];
  assert.strictEqual(deriveFeedFreshness(mixedVitals), 'fresh');
});

test('resolveLatestMeasurementTime identifies the newest timestamp', () => {
  const readings: VitalsReading[] = [
    {
      metricCode: 'heart_rate',
      label: 'Heart Rate',
      value: 70,
      unit: 'bpm',
      measuredAt: '2023-10-01T08:10:00Z',
      freshness: 'stale',
      source: 'kaggle_csv',
      isSimulated: true,
      qualityStatus: 'valid',
    },
    {
      metricCode: 'spo2',
      label: 'SpO2',
      value: 98,
      unit: '%',
      measuredAt: '2023-10-01T08:15:00Z',
      freshness: 'stale',
      source: 'kaggle_csv',
      isSimulated: true,
      qualityStatus: 'valid',
    },
  ];

  const latest = resolveLatestMeasurementTime(readings);
  assert.strictEqual(latest, '2023-10-01T08:15:00Z');
});

test('fetchPatientRows with useFixtures=true returns Kaggle cohort P101–P105', async () => {
  const rows = await fetchPatientRows(true);
  assert.strictEqual(rows.length, 5);

  const ids = rows.map((r) => r.patient.patientId);
  assert.deepStrictEqual(ids, ['P101', 'P102', 'P103', 'P104', 'P105']);

  // Ensure each patient has separated vitals and alerts
  for (const row of rows) {
    assert.ok(row.latestVitals.length > 0);
    assert.strictEqual(row.feedFreshness, 'stale'); // Historical Kaggle data is stale
  }
});
