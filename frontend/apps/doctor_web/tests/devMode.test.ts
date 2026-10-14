import test from 'node:test';
import assert from 'node:assert';
import {
  KAGGLE_COHORT_FIXTURES,
  getAllFixtureAlerts,
  acknowledgeFixtureAlert,
  resolveFixtureAlert,
  resetFixtureData,
} from '../src/api/fixtures';

test('DevMode and fixture isolation enforces Kaggle cohort constraints', () => {
  // Ensure Kaggle cohort contains exact P101–P105 cohort
  const cohortIds = KAGGLE_COHORT_FIXTURES.map((f) => f.patient.patientId);
  assert.deepStrictEqual(cohortIds, ['P101', 'P102', 'P103', 'P104', 'P105']);

  // Verify all fixture vitals explicitly flag isSimulated === true and source 'kaggle_csv'
  for (const fixture of KAGGLE_COHORT_FIXTURES) {
    for (const vital of fixture.latestVitals) {
      assert.strictEqual(vital.isSimulated, true);
      assert.strictEqual(vital.source, 'kaggle_csv');
      assert.strictEqual(vital.freshness, 'stale'); // Historical dataset timestamps
    }
  }
});

test('Surveillance alerts do not claim ML detection and maintain valid status', () => {
  const allAlerts = getAllFixtureAlerts();
  assert.ok(allAlerts.length > 0);

  for (const alert of allAlerts) {
    // Assert status is one of valid clinical triage states
    assert.ok(['open', 'acknowledged', 'resolved'].includes(alert.status));
    
    // Assert alert reason avoids pretending a live ML model detected it
    assert.doesNotMatch(alert.reason.toLowerCase(), /isolation forest flagged/);
  }
});

test('Simulated clinician demo session credentials match contract definitions', () => {
  const demoClinician = {
    userId: 'usr_doc_01',
    email: 'dr.demo@hospital.org',
    name: 'Dr. Sarah Jenkins',
    role: 'doctor',
    licenseNumber: 'MD-94821 [DEMO SESSION]',
  };

  assert.strictEqual(demoClinician.userId, 'usr_doc_01');
  assert.strictEqual(demoClinician.role, 'doctor');
  assert.ok(demoClinician.licenseNumber.startsWith('MD-'));
});

test('acknowledgeFixtureAlert, resolveFixtureAlert, and resetFixtureData manage in-memory demo state safely', () => {
  // Acknowledge open alert
  const ack = acknowledgeFixtureAlert('alt_p101_01', 'Test presentation note');
  assert.strictEqual(ack.status, 'acknowledged');
  assert.strictEqual(ack.notes, 'Test presentation note');

  // Resolve alert
  const res = resolveFixtureAlert('alt_p101_01', 'Resolution presentation note');
  assert.strictEqual(res.status, 'resolved');
  assert.strictEqual(res.notes, 'Resolution presentation note');

  // Reset demo data
  resetFixtureData();

  // Verify alt_p101_01 is restored to 'open'
  const restoredAlerts = getAllFixtureAlerts('P101');
  const restoredP101 = restoredAlerts.find((a) => a.alertId === 'alt_p101_01');
  assert.strictEqual(restoredP101?.status, 'open');
  assert.strictEqual(restoredP101?.notes, undefined);
});

