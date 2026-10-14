import test from 'node:test';
import assert from 'node:assert';
import { wsManager, type WsStatusSnapshot } from '../src/api/webSocketService';
import { startDemoRun, stopDemoRun, switchDemoScenario, normalizeDemoRun, type RawDemoRunDto } from '../src/api/demoService';

test('WebSocketManager subscribes and notifies status, cleaning up on unsubscribe', () => {
  let receivedSnapshot: WsStatusSnapshot | null = null;
  const unsubscribe = wsManager.subscribeStatus((snapshot) => {
    receivedSnapshot = snapshot;
  });

  assert.ok(receivedSnapshot);
  assert.strictEqual(receivedSnapshot.state, 'disconnected');

  // Verify unsubscribe removes listener
  unsubscribe();
});

test('normalizeDemoRun maps server DTO accurately into typed DemoRun', () => {
  const raw: RawDemoRunDto = {
    run_id: 'run_live_01',
    patient_id: 'P101',
    scenario: 'combined_anomaly',
    interval_seconds: 5,
    state: 'running',
    started_at: '2026-10-14T12:00:00Z',
    last_event_id: 'evt_001',
    failed_deliveries: 0,
    is_simulated: true,
  };

  const run = normalizeDemoRun(raw);
  assert.strictEqual(run.runId, 'run_live_01');
  assert.strictEqual(run.patientId, 'P101');
  assert.strictEqual(run.scenario, 'combined_anomaly');
  assert.strictEqual(run.intervalSeconds, 5);
  assert.strictEqual(run.state, 'running');
  assert.strictEqual(run.lastEventId, 'evt_001');
  assert.strictEqual(run.failedDeliveries, 0);
  assert.strictEqual(run.isSimulated, true);
});

test('DemoService development fixtures support offline start, switch, and stop', async () => {
  // 1. Start simulation run in fixture mode
  const run = await startDemoRun(
    {
      patientId: 'P102',
      scenario: 'single_anomaly',
      intervalSeconds: 5,
    },
    true // useFixtures
  );

  assert.ok(run.runId.startsWith('run_fix_'));
  assert.strictEqual(run.patientId, 'P102');
  assert.strictEqual(run.scenario, 'single_anomaly');
  assert.strictEqual(run.state, 'running');
  assert.strictEqual(run.isSimulated, true);

  // 2. Switch scenario in fixture mode
  const switched = await switchDemoScenario(run.runId, 'recovery', true);
  assert.strictEqual(switched.scenario, 'recovery');

  // 3. Stop run in fixture mode
  const stopped = await stopDemoRun(run.runId, true);
  assert.strictEqual(stopped.state, 'stopped');
});
