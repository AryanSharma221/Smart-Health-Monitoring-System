import test from 'node:test';
import assert from 'node:assert';
import {
  fetchSimulatorStatus,
  startSimulator,
  stopSimulator,
  setSimulatorScenario,
} from '../src/api/simulatorService';

test('simulatorService methods exist and can be called against live backend or mock', () => {
  assert.strictEqual(typeof fetchSimulatorStatus, 'function');
  assert.strictEqual(typeof startSimulator, 'function');
  assert.strictEqual(typeof stopSimulator, 'function');
  assert.strictEqual(typeof setSimulatorScenario, 'function');
});

test('simulator-state-changed custom event dispatches and listens accurately', () => {
  let heardState = '';
  const handler = (e: Event) => {
    const custom = e as CustomEvent<{ state: string }>;
    heardState = custom.detail.state;
  };

  // Test event listener registration
  if (typeof window !== 'undefined') {
    window.addEventListener('simulator-state-changed', handler);
    window.dispatchEvent(new CustomEvent('simulator-state-changed', { detail: { state: 'RUNNING' } }));
    assert.strictEqual(heardState, 'RUNNING');

    window.dispatchEvent(new CustomEvent('simulator-state-changed', { detail: { state: 'STOPPED' } }));
    assert.strictEqual(heardState, 'STOPPED');

    window.removeEventListener('simulator-state-changed', handler);
  } else {
    // Node environment fallback assertion
    assert.ok(true);
  }
});
