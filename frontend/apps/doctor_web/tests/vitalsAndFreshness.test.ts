import test from 'node:test';
import assert from 'node:assert';
import { calculateFreshness } from '../src/api/patientService';
import { formatVitalValue, formatTimestamp } from '../src/utils/formatters';

test('formatVitalValue returns em-dash for null, undefined, or NaN and never converts to zero', () => {
  assert.strictEqual(formatVitalValue(null, 'bpm'), '—');
  assert.strictEqual(formatVitalValue(undefined, '%'), '—');
  assert.strictEqual(formatVitalValue(NaN, '°F'), '—');
  assert.strictEqual(formatVitalValue(0, 'bpm'), '0 bpm');
  assert.strictEqual(formatVitalValue(72, 'bpm'), '72 bpm');
  assert.strictEqual(formatVitalValue(98.6, '°F'), '98.6 °F');
});

test('calculateFreshness accurately categorizes based on 60-second threshold', () => {
  const now = Date.now();
  
  // Reading 10 seconds ago -> fresh
  const recentTime = new Date(now - 10 * 1000).toISOString();
  assert.strictEqual(calculateFreshness(recentTime), 'fresh');

  // Reading 59 seconds ago -> fresh
  const boundaryFresh = new Date(now - 59 * 1000).toISOString();
  assert.strictEqual(calculateFreshness(boundaryFresh), 'fresh');

  // Reading 65 seconds ago -> stale
  const boundaryStale = new Date(now - 65 * 1000).toISOString();
  assert.strictEqual(calculateFreshness(boundaryStale), 'stale');

  // Kaggle historical data (October 2023) -> stale
  const kaggleDate = '2023-10-01T08:13:00Z';
  assert.strictEqual(calculateFreshness(kaggleDate), 'stale');

  // Missing or null -> unavailable
  assert.strictEqual(calculateFreshness(null), 'unavailable');
  assert.strictEqual(calculateFreshness(undefined), 'unavailable');
  assert.strictEqual(calculateFreshness(''), 'unavailable');
});

test('formatTimestamp safely handles valid ISO strings and non-ISO strings', () => {
  assert.strictEqual(formatTimestamp(null), '—');
  assert.strictEqual(formatTimestamp(undefined), '—');
  assert.strictEqual(formatTimestamp(''), '—');

  // ISO string formats correctly
  const iso = '2026-10-14T10:30:00Z';
  const formatted = formatTimestamp(iso);
  assert.ok(formatted.length > 0 && formatted !== '—');

  // Space-separated date strings format without throwing
  const spaceSeparated = '2023-10-01 08:13:00';
  const res = formatTimestamp(spaceSeparated);
  assert.ok(res.length > 0);
});
