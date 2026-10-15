import test from 'node:test';
import assert from 'node:assert';
import { evaluationService } from '../src/api/evaluationService';
import { ApiClientError } from '../src/api/client';

test('evaluationService methods structure requests correctly and enforce endpoints', async () => {
  const originalFetch = globalThis.fetch;

  try {
    // 1. Test getRecords endpoint formatting
    let capturedUrl = '';
    let capturedMethod = '';
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      return new Response(
        JSON.stringify([
          {
            record_id: 'EVAL_NOTE_01',
            patient_id: 'P101',
            record_type: 'consultation_note',
            title: 'Test Note',
            content: 'Test Content',
            created_by: 'DOC_TEST_01',
            created_at: '2026-10-15T00:00:00Z',
            is_evaluation: true,
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const records = await evaluationService.getRecords('P101');
    assert.strictEqual(records.length, 1);
    assert.strictEqual(records[0].record_id, 'EVAL_NOTE_01');
    assert.ok(capturedUrl.includes('/api/v1/evaluation/crud/records?patient_id=P101'));
    assert.strictEqual(capturedMethod, 'GET');

    // 2. Test createRecord request body and endpoint
    let capturedBody = '';
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      capturedBody = String(init?.body || '');
      return new Response(
        JSON.stringify({
          record_id: 'EVAL_NOTE_99',
          patient_id: 'P102',
          record_type: 'consultation_note',
          title: 'Heart Rate Spike',
          content: 'Observed tachycardia at 128 bpm',
          created_by: 'DOC_TEST_01',
          created_at: '2026-10-15T00:00:00Z',
          is_evaluation: true,
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const created = await evaluationService.createRecord({
      patient_id: 'P102',
      title: 'Heart Rate Spike',
      content: 'Observed tachycardia at 128 bpm',
    });
    assert.strictEqual(created.record_id, 'EVAL_NOTE_99');
    assert.ok(capturedUrl.includes('/api/v1/evaluation/crud/records'));
    assert.strictEqual(capturedMethod, 'POST');
    assert.ok(capturedBody.includes('Heart Rate Spike'));

    // 3. Test Safety Guard: HTTP 403 Forbidden on baseline patient deletion
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          detail: 'Protected Baseline Record: Cannot delete baseline EHR patient record P001. Only designated evaluation fixtures starting with EVAL_ can be deleted.',
        }),
        { status: 403, statusText: 'Forbidden', headers: { 'Content-Type': 'application/json' } }
      );

    await assert.rejects(
      async () => {
        await evaluationService.deleteRecord('P001');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.statusCode, 403);
        assert.strictEqual(err.errorType, 'forbidden');
        assert.ok(err.message.includes('Protected Baseline Record'));
        return true;
      }
    );

    // 4. Test MongoDB aggregate request
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      capturedBody = String(init?.body || '');
      return new Response(
        JSON.stringify({
          pipeline_name: 'dataset_overview',
          description: 'Dataset overview test',
          pipeline_json: '[]',
          execution_time_ms: 2.5,
          result_count: 1,
          results: [{ total_documents: 2955 }],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const aggRes = await evaluationService.aggregateMongo({
      pipeline_name: 'dataset_overview',
      patient_id: 'P101',
    });
    assert.strictEqual(aggRes.pipeline_name, 'dataset_overview');
    assert.strictEqual(aggRes.result_count, 1);
    assert.ok(capturedUrl.includes('/api/v1/evaluation/mongodb/aggregate'));
    assert.strictEqual(capturedMethod, 'POST');
    assert.ok(capturedBody.includes('dataset_overview'));

    // 5. Test getRbacTest request
    globalThis.fetch = async (input: RequestInfo | URL) => {
      capturedUrl = String(input);
      return new Response(
        JSON.stringify({
          caller_role: 'doctor',
          caller_id: 'doc@hospital.org',
          permissions: { view_assigned_patients: true },
          access_matrix: [{ role: 'doctor', view_assigned: true }],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const rbacRes = await evaluationService.getRbacTest();
    assert.strictEqual(rbacRes.caller_role, 'doctor');
    assert.ok(capturedUrl.includes('/api/v1/evaluation/security/rbac-test'));

    // 6. Test demonstrateSecurity request
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      capturedBody = String(init?.body || '');
      return new Response(
        JSON.stringify({
          scenario: 'denied_unassigned_patient',
          title: 'RBAC Access Denial',
          expected_status: 403,
          actual_status: 403,
          outcome: 'DENIED',
          security_layer: 'RBAC Guard',
          security_explanation: 'Access Denied: Not assigned to patient',
          sanitized_response: { error: 'Forbidden', status_code: 403 },
          timestamp: '2026-10-15T00:00:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const secRes = await evaluationService.demonstrateSecurity('denied_unassigned_patient', 'P999');
    assert.strictEqual(secRes.actual_status, 403);
    assert.strictEqual(secRes.outcome, 'DENIED');
    assert.ok(capturedUrl.includes('/api/v1/evaluation/security/demonstrate'));
    assert.strictEqual(capturedMethod, 'POST');
    assert.ok(capturedBody.includes('denied_unassigned_patient'));

    // 7. Test getChallenges request
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      return new Response(
        JSON.stringify([
          {
            challenge_id: 'sql_select_patient_readings',
            category: 'SQL Challenges',
            name: 'Retrieve Patient Telemetry Readings',
            purpose: 'Demonstrate SELECT query',
            operation_type: 'SELECT',
            requires_confirmation: false,
            allowed_parameters: {},
            description: 'Select test',
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const challenges = await evaluationService.getChallenges();
    assert.strictEqual(challenges.length, 1);
    assert.strictEqual(challenges[0].challenge_id, 'sql_select_patient_readings');
    assert.ok(capturedUrl.includes('/api/v1/evaluation/challenges'));
    assert.strictEqual(capturedMethod, 'GET');

    // 8. Test executeChallenge request
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      capturedBody = String(init?.body || '');
      return new Response(
        JSON.stringify({
          challenge_id: 'sql_select_patient_readings',
          name: 'Retrieve Patient Telemetry Readings',
          category: 'SQL Challenges',
          purpose: 'Demonstrate SELECT query',
          operation_demonstrated: 'SELECT * FROM vitals_readings',
          status: 'SUCCESS',
          http_status: 200,
          execution_time_ms: 1.25,
          affected_rows: 10,
          response_data: { count: 10 },
          explanation: 'Indexed SELECT query completed in 1.25ms',
          timestamp_utc: '2026-10-15T00:00:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const chalRes = await evaluationService.executeChallenge({
      challenge_id: 'sql_select_patient_readings',
      parameters: { patient_id: 'P101', limit: 10 },
      confirmed: false,
    });
    assert.strictEqual(chalRes.status, 'SUCCESS');
    assert.strictEqual(chalRes.http_status, 200);
    assert.strictEqual(chalRes.affected_rows, 10);
    assert.ok(capturedUrl.includes('/api/v1/evaluation/challenges/execute'));
    assert.strictEqual(capturedMethod, 'POST');
    assert.ok(capturedBody.includes('sql_select_patient_readings'));
  } finally {
    globalThis.fetch = originalFetch;
  }
});
