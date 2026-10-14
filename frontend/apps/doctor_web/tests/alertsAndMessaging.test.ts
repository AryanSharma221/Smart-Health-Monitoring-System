import test from 'node:test';
import assert from 'node:assert';
import { normalizeAlert, type RawAlertDto } from '../src/api/patientService';
import { normalizeMessage, type RawMessageDto } from '../src/api/messageService';
import { getAllFixtureAlerts, getFixtureMessages, sendFixtureMessage } from '../src/api/fixtures';

test('normalizeAlert handles various DTO formats and preserves fields', () => {
  const raw1: RawAlertDto = {
    alert_id: 'alt_live_01',
    patient_id: 'P101',
    severity: 'critical',
    reason: 'Severe desaturation',
    status: 'open',
    created_at: '2026-10-14T10:00:00Z',
    assessment_id: 'asm_01',
  };

  const a1 = normalizeAlert(raw1, 'P101');
  assert.strictEqual(a1.alertId, 'alt_live_01');
  assert.strictEqual(a1.patientId, 'P101');
  assert.strictEqual(a1.severity, 'critical');
  assert.strictEqual(a1.status, 'open');
  assert.strictEqual(a1.assessmentId, 'asm_01');

  // Fallback patient ID when DTO omits it
  const raw2: RawAlertDto = {
    id: 'alt_live_02',
    severity: 'advisory',
    message: 'Baseline drift',
  };
  const a2 = normalizeAlert(raw2, 'P102');
  assert.strictEqual(a2.alertId, 'alt_live_02');
  assert.strictEqual(a2.patientId, 'P102');
  assert.strictEqual(a2.reason, 'Baseline drift');
  assert.strictEqual(a2.status, 'open');
});

test('normalizeMessage identifies sender and formats message', () => {
  const rawDoc: RawMessageDto = {
    message_id: 'msg_01',
    sender_id: 'usr_doc_01',
    receiver_id: 'P101',
    content: 'Please adjust your monitor lead',
    created_at: '2026-10-14T11:00:00Z',
  };

  const mDoc = normalizeMessage(rawDoc, 'usr_doc_01', 'P101');
  assert.strictEqual(mDoc.isFromDoctor, true);
  assert.strictEqual(mDoc.content, 'Please adjust your monitor lead');

  const rawPatient: RawMessageDto = {
    message_id: 'msg_02',
    sender_id: 'P101',
    receiver_id: 'usr_doc_01',
    content: 'Lead adjusted, resting now',
    created_at: '2026-10-14T11:05:00Z',
  };

  const mPatient = normalizeMessage(rawPatient, 'usr_doc_01', 'P101');
  assert.strictEqual(mPatient.isFromDoctor, false);
  assert.strictEqual(mPatient.content, 'Lead adjusted, resting now');
});

test('fixtures provide isolated Kaggle cohort P101–P105 records', () => {
  const p101Alerts = getAllFixtureAlerts('P101');
  assert.ok(p101Alerts.length > 0);
  assert.strictEqual(p101Alerts[0].patientId, 'P101');

  const msgs = getFixtureMessages('P101');
  assert.ok(msgs.length > 0);

  const sent = sendFixtureMessage('P101', 'Test consultation inquiry', 'usr_doc_01');
  assert.strictEqual(sent.patientId, 'P101');
  assert.strictEqual(sent.content, 'Test consultation inquiry');
  assert.strictEqual(sent.isFromDoctor, true);
});
