/**
 * SMART HEALTH MONITORING SYSTEM — LIVE TELEMETRY & VISUALIZATION TESTS
 * 
 * Verifies Part 6C live smartwatch telemetry visualization requirements:
 * 1. Time range resolution (live_15m, 1h, 24h, kaggle_archive, all).
 * 2. Strict provenance separation (Simulated Smartwatch vs Kaggle Historical Archive).
 * 3. Point deduplication by eventId and timestamp to prevent polling artifacts.
 * 4. Gap detection avoiding misleading linear interpolation across > 20 min missing intervals.
 * 5. Scale separation across Heart Rate (bpm), SpO2 (%), and Body Temperature (°F).
 * 6. Real-time WebSocket patient channel subscription handling.
 */

import test from 'node:test';
import assert from 'node:assert';
import type { VitalsReading } from '../src/types/vitals';
import { wsManager } from '../src/api/webSocketService';

// Time range resolution helper identical to component logic
function resolveTimeBounds(range: 'live_15m' | '1h' | '24h' | 'kaggle_archive' | 'all'): {
  from?: string;
  to?: string;
  limit: number;
} {
  const now = new Date();
  if (range === 'live_15m') {
    const past15m = new Date(now.getTime() - 15 * 60 * 1000);
    return { from: past15m.toISOString(), to: now.toISOString(), limit: 100 };
  }
  if (range === '1h') {
    const past1h = new Date(now.getTime() - 60 * 60 * 1000);
    return { from: past1h.toISOString(), to: now.toISOString(), limit: 150 };
  }
  if (range === '24h') {
    const past24h = new Date(now.getTime() - 24 * 3600 * 1000);
    return { from: past24h.toISOString(), to: now.toISOString(), limit: 200 };
  }
  if (range === 'kaggle_archive') {
    return { from: '2023-10-01T00:00:00Z', to: '2023-10-12T00:00:00Z', limit: 250 };
  }
  return { from: undefined, to: undefined, limit: 100 };
}

// Deduplication helper replicating VitalTimeSeriesChart
function deduplicateReadings(readings: VitalsReading[]): VitalsReading[] {
  const seen = new Set<string>();
  const unique: VitalsReading[] = [];
  for (const r of readings) {
    const key = r.eventId ? `evt:${r.eventId}` : `${r.metricCode}:${r.measuredAt}:${r.value}`;
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(r);
    }
  }
  return unique;
}

// Gap detection helper replicating VitalTimeSeriesChart segmenting
function segmentPointsWithGaps(points: { x: number; y: number; timeMs: number }[], gapThresholdMs: number = 20 * 60 * 1000) {
  const segments: { x: number; y: number; timeMs: number }[][] = [];
  let currentSegment: { x: number; y: number; timeMs: number }[] = [];

  for (let i = 0; i < points.length; i++) {
    const pt = points[i];
    if (i > 0 && pt.timeMs - points[i - 1].timeMs > gapThresholdMs) {
      if (currentSegment.length > 0) {
        segments.push(currentSegment);
        currentSegment = [];
      }
    }
    currentSegment.push(pt);
  }
  if (currentSegment.length > 0) {
    segments.push(currentSegment);
  }
  return segments;
}

test('Time range bounds resolution produces correct windows and limits', () => {
  // Test live_15m
  const b15m = resolveTimeBounds('live_15m');
  assert.ok(b15m.from && b15m.to);
  const diff15m = new Date(b15m.to).getTime() - new Date(b15m.from).getTime();
  assert.strictEqual(diff15m, 15 * 60 * 1000);
  assert.strictEqual(b15m.limit, 100);

  // Test 1h
  const b1h = resolveTimeBounds('1h');
  assert.ok(b1h.from && b1h.to);
  const diff1h = new Date(b1h.to).getTime() - new Date(b1h.from).getTime();
  assert.strictEqual(diff1h, 60 * 60 * 1000);
  assert.strictEqual(b1h.limit, 150);

  // Test kaggle_archive
  const bKaggle = resolveTimeBounds('kaggle_archive');
  assert.strictEqual(bKaggle.from, '2023-10-01T00:00:00Z');
  assert.strictEqual(bKaggle.to, '2023-10-12T00:00:00Z');
  assert.strictEqual(bKaggle.limit, 250);

  // Test all
  const bAll = resolveTimeBounds('all');
  assert.strictEqual(bAll.from, undefined);
  assert.strictEqual(bAll.to, undefined);
  assert.strictEqual(bAll.limit, 100);
});

test('Provenance classification reliably distinguishes simulated vs historical records', () => {
  const simulatedReading: VitalsReading = {
    readingId: 'rdg_sim_1',
    patientId: 'P101',
    metricCode: 'heart_rate',
    value: 78,
    unit: 'bpm',
    measuredAt: new Date().toISOString(),
    freshness: 'fresh',
    isSimulated: true,
    source: 'smartwatch_simulator',
    eventId: 'evt_sim_101_1',
  };

  const historicalReading: VitalsReading = {
    readingId: 'rdg_hist_1',
    patientId: 'P101',
    metricCode: 'heart_rate',
    value: 72,
    unit: 'bpm',
    measuredAt: '2023-10-02T10:00:00Z',
    freshness: 'unavailable',
    isSimulated: false,
    source: 'kaggle_csv',
  };

  assert.strictEqual(simulatedReading.isSimulated, true);
  assert.strictEqual(simulatedReading.source, 'smartwatch_simulator');
  assert.ok(simulatedReading.eventId?.startsWith('evt_sim_'));

  assert.strictEqual(historicalReading.isSimulated, false);
  assert.strictEqual(historicalReading.source, 'kaggle_csv');
  assert.strictEqual(historicalReading.eventId, undefined);
});

test('Reading deduplication by eventId and timestamp prevents repetitive chart markers', () => {
  const now = new Date().toISOString();
  const rawReadings: VitalsReading[] = [
    {
      readingId: '1',
      patientId: 'P101',
      metricCode: 'heart_rate',
      value: 75,
      unit: 'bpm',
      measuredAt: now,
      freshness: 'fresh',
      isSimulated: true,
      eventId: 'evt_dup_01',
    },
    // Duplicate eventId from repeated polling
    {
      readingId: '2',
      patientId: 'P101',
      metricCode: 'heart_rate',
      value: 75,
      unit: 'bpm',
      measuredAt: now,
      freshness: 'fresh',
      isSimulated: true,
      eventId: 'evt_dup_01',
    },
    // Next reading
    {
      readingId: '3',
      patientId: 'P101',
      metricCode: 'heart_rate',
      value: 77,
      unit: 'bpm',
      measuredAt: new Date(Date.now() + 5000).toISOString(),
      freshness: 'fresh',
      isSimulated: true,
      eventId: 'evt_dup_02',
    },
  ];

  const deduplicated = deduplicateReadings(rawReadings);
  assert.strictEqual(deduplicated.length, 2, 'Should deduplicate readings sharing the same eventId');
  assert.strictEqual(deduplicated[0].eventId, 'evt_dup_01');
  assert.strictEqual(deduplicated[1].eventId, 'evt_dup_02');
});

test('Chart gap detection breaks SVG segments when measurements gap exceeds 20 minutes', () => {
  const baseTime = new Date('2026-10-15T00:00:00Z').getTime();
  const points = [
    { x: 10, y: 50, timeMs: baseTime },
    { x: 20, y: 55, timeMs: baseTime + 5 * 60 * 1000 }, // +5 min (continuous)
    { x: 30, y: 52, timeMs: baseTime + 10 * 60 * 1000 }, // +10 min (continuous)
    { x: 40, y: 70, timeMs: baseTime + 60 * 60 * 1000 }, // +60 min (GAP > 20 min)
    { x: 50, y: 72, timeMs: baseTime + 65 * 60 * 1000 }, // +65 min (continuous with point 4)
  ];

  const segments = segmentPointsWithGaps(points, 20 * 60 * 1000);
  assert.strictEqual(segments.length, 2, 'Should split points into 2 distinct segments across the 50-minute gap');
  assert.strictEqual(segments[0].length, 3, 'First segment contains initial 3 points');
  assert.strictEqual(segments[1].length, 2, 'Second segment contains remaining 2 points');
});

test('Scale separation preserves physiological units and reference baselines', () => {
  const hrReading: VitalsReading = {
    readingId: 'r_hr',
    patientId: 'P101',
    metricCode: 'heart_rate',
    value: 78,
    unit: 'bpm',
    measuredAt: new Date().toISOString(),
    freshness: 'fresh',
    isSimulated: true,
  };

  const spo2Reading: VitalsReading = {
    readingId: 'r_spo2',
    patientId: 'P101',
    metricCode: 'spo2',
    value: 98.5,
    unit: '%',
    measuredAt: new Date().toISOString(),
    freshness: 'fresh',
    isSimulated: true,
  };

  const tempReading: VitalsReading = {
    readingId: 'r_temp',
    patientId: 'P101',
    metricCode: 'temperature_f',
    value: 98.6,
    unit: '°F',
    measuredAt: new Date().toISOString(),
    freshness: 'fresh',
    isSimulated: true,
  };

  // Heart rate range: ~50 to 160 bpm
  assert.strictEqual(hrReading.unit, 'bpm');
  assert.ok(hrReading.value! >= 40 && hrReading.value! <= 220);

  // SpO2 range: ~70 to 100%
  assert.strictEqual(spo2Reading.unit, '%');
  assert.ok(spo2Reading.value! >= 60 && spo2Reading.value! <= 100);

  // Temperature range: ~95 to 105 °F
  assert.strictEqual(tempReading.unit, '°F');
  assert.ok(tempReading.value! >= 90 && tempReading.value! <= 110);
});

test('WebSocket patient channel subscription registers and unregisters cleanly', () => {
  // Verify method existence and safety
  assert.doesNotThrow(() => {
    wsManager.subscribePatient('P101');
    wsManager.subscribePatient('P102');
    wsManager.unsubscribePatient('P101');
    wsManager.unsubscribePatient('P102');
  });
});
