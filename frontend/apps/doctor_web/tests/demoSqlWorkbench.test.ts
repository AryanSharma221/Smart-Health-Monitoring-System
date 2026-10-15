import test from 'node:test';
import assert from 'node:assert';
import {
  workbenchService,
  type SQLWorkbenchExecuteRequest,
  type SQLWorkbenchExecuteResponse,
} from '../src/api/workbenchService';
import { ApiClientError } from '../src/api/client';
import { EXAMPLE_QUERIES } from '../src/features/demo/demoSqlExamples';

test('workbenchService.executeQuery sends structured POST request and receives SELECT results', async () => {
  const originalFetch = globalThis.fetch;

  try {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedBody = '';

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      capturedBody = String(init?.body || '');

      const mockResponse: SQLWorkbenchExecuteResponse = {
        status: 'success',
        statement_type: 'SELECT',
        columns: ['reading_id', 'patient_id', 'heart_rate', 'spo2', 'temperature', 'source'],
        rows: [
          ['DEMO_READ_001', 'P101', 82.5, 98.2, 98.6, 'self_added'],
        ],
        row_count: 1,
        rows_affected: null,
        execution_time_ms: 12.4,
        message: 'Query executed successfully, returning 1 row(s).',
      };

      return new Response(JSON.stringify(mockResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const req: SQLWorkbenchExecuteRequest = {
      sql: 'SELECT * FROM health_reading WHERE patient_id = "P101" ORDER BY timestamp DESC LIMIT 5;',
      is_demo_mode: true,
      patient_id: 'P101',
    };

    const res = await workbenchService.executeQuery(req);

    assert.ok(capturedUrl.includes('/api/v1/evaluation/workbench/execute'));
    assert.strictEqual(capturedMethod, 'POST');
    const parsedBody = JSON.parse(capturedBody);
    assert.strictEqual(parsedBody.sql, req.sql);
    assert.strictEqual(parsedBody.is_demo_mode, true);
    assert.strictEqual(parsedBody.patient_id, 'P101');

    assert.strictEqual(res.status, 'success');
    assert.strictEqual(res.statement_type, 'SELECT');
    assert.strictEqual(res.row_count, 1);
    assert.strictEqual(res.columns?.length, 6);
    assert.strictEqual(res.rows?.[0]?.[0], 'DEMO_READ_001');
    assert.strictEqual(res.rows?.[0]?.[5], 'self_added');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workbenchService.executeQuery handles INSERT with ML assessment and self_added classification', async () => {
  const originalFetch = globalThis.fetch;

  try {
    globalThis.fetch = async () => {
      const mockInsertResponse: SQLWorkbenchExecuteResponse = {
        status: 'success',
        statement_type: 'INSERT',
        columns: [],
        rows: [],
        row_count: 0,
        rows_affected: 3,
        last_inserted_id: 'DEMO_READ_SELF_101',
        execution_time_ms: 28.6,
        ml_assessment: {
          assessed: true,
          patient_id: 'P101',
          anomaly_score: 0.7421,
          result: 'anomaly',
          alert_created: true,
          alert_severity: 'critical',
          message: 'Isolation Forest flagged vital signs anomaly.',
        },
        message: 'Inserted 3 health reading(s) with ML anomaly evaluation.',
      };

      return new Response(JSON.stringify(mockInsertResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const res = await workbenchService.executeQuery({
      sql: 'INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ("P101", "heart_rate", 145.0, "bpm");',
      is_demo_mode: true,
      patient_id: 'P101',
    });

    assert.strictEqual(res.status, 'success');
    assert.strictEqual(res.statement_type, 'INSERT');
    assert.strictEqual(res.last_inserted_id, 'DEMO_READ_SELF_101');
    assert.strictEqual(res.rows_affected, 3);
    assert.ok(res.ml_assessment !== undefined);
    assert.strictEqual(res.ml_assessment?.result, 'anomaly');
    assert.strictEqual(res.ml_assessment?.alert_severity, 'critical');
    assert.strictEqual(res.ml_assessment?.assessed, true);
    assert.ok(res.message?.includes('ML anomaly evaluation'));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workbenchService.executeQuery handles UPDATE and DELETE mutations with rows_affected', async () => {
  const originalFetch = globalThis.fetch;

  try {
    // 1. UPDATE test
    globalThis.fetch = async () => {
      const mockUpdateResponse: SQLWorkbenchExecuteResponse = {
        status: 'success',
        statement_type: 'UPDATE',
        columns: [],
        rows: [],
        row_count: 0,
        rows_affected: 1,
        execution_time_ms: 18.2,
        message: 'Updated 1 row(s) in vitals_readings.',
      };
      return new Response(JSON.stringify(mockUpdateResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const updateRes = await workbenchService.executeQuery({
      sql: 'UPDATE vitals_readings SET value = 148.0 WHERE patient_id = "P101" AND metric_code = "heart_rate";',
      is_demo_mode: true,
    });
    assert.strictEqual(updateRes.statement_type, 'UPDATE');
    assert.strictEqual(updateRes.rows_affected, 1);

    // 2. DELETE test
    globalThis.fetch = async () => {
      const mockDeleteResponse: SQLWorkbenchExecuteResponse = {
        status: 'success',
        statement_type: 'DELETE',
        columns: [],
        rows: [],
        row_count: 0,
        rows_affected: 1,
        execution_time_ms: 15.1,
        message: 'Deleted 1 self-added row(s) and associated demo assessments.',
      };
      return new Response(JSON.stringify(mockDeleteResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const deleteRes = await workbenchService.executeQuery({
      sql: 'DELETE FROM vitals_readings WHERE patient_id = "P101" AND metric_code = "heart_rate";',
      is_demo_mode: true,
    });
    assert.strictEqual(deleteRes.statement_type, 'DELETE');
    assert.strictEqual(deleteRes.rows_affected, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workbenchService.executeQuery translates backend validation and syntax errors into ApiClientError', async () => {
  const originalFetch = globalThis.fetch;

  try {
    // 1. Syntax / DDL rejection error (HTTP 400)
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          detail: 'Rejected SQL statement: DROP TABLE is not permitted in Demo SQL Workbench.',
          statement_type: 'DISALLOWED',
        }),
        {
          status: 400,
          statusText: 'Bad Request',
          headers: { 'Content-Type': 'application/json' },
        }
      );

    await assert.rejects(
      async () => {
        await workbenchService.executeQuery({
          sql: 'DROP TABLE health_reading;',
          is_demo_mode: true,
        });
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.statusCode, 400);
        assert.ok(err.message.includes('DROP TABLE is not permitted'));
        return true;
      }
    );

    // 2. Safety violation: Mutation of Kaggle baseline cohort (HTTP 403)
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          detail: 'Modification of baseline Kaggle cohort P001–P005 is prohibited. Only demo cohort P101–P105 and self_added records may be modified.',
        }),
        {
          status: 403,
          statusText: 'Forbidden',
          headers: { 'Content-Type': 'application/json' },
        }
      );

    await assert.rejects(
      async () => {
        await workbenchService.executeQuery({
          sql: 'DELETE FROM health_reading WHERE patient_id = "P001";',
          is_demo_mode: true,
        });
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.statusCode, 403);
        assert.strictEqual(err.errorType, 'forbidden');
        assert.ok(err.message.includes('baseline Kaggle cohort P001–P005 is prohibited'));
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('EXAMPLE_QUERIES covers all mandatory schema and query operations', () => {
  assert.ok(EXAMPLE_QUERIES.length >= 10, 'Expected at least 10 example queries');

  const categories = new Set(EXAMPLE_QUERIES.map((e) => e.category));
  assert.ok(categories.has('INSERT'), 'Examples must include INSERT');
  assert.ok(categories.has('SELECT'), 'Examples must include SELECT');
  assert.ok(categories.has('UPDATE'), 'Examples must include UPDATE');
  assert.ok(categories.has('DELETE'), 'Examples must include DELETE');
  assert.ok(categories.has('JOIN'), 'Examples must include JOIN');
  assert.ok(categories.has('AGGREGATE'), 'Examples must include AGGREGATE');
  assert.ok(categories.has('VIEW'), 'Examples must include VIEW');

  // Verify all examples target vitals_readings, patient_profiles, or demo views
  for (const example of EXAMPLE_QUERIES) {
    assert.ok(example.name.length > 0);
    assert.ok(example.sql.length > 0);
    assert.ok(example.description.length > 0);
    const upperSql = example.sql.toUpperCase();
    assert.ok(
      upperSql.includes('VITALS_READINGS') ||
        upperSql.includes('PATIENT_PROFILES') ||
        upperSql.includes('V_P101_HIGH_HR'),
      `Example query "${example.name}" must target valid demo tables/views: ${example.sql}`
    );
  }
});
