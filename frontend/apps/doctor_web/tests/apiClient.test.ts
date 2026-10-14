import test from 'node:test';
import assert from 'node:assert';
import { apiRequest, ApiClientError } from '../src/api/client';

test('ApiClientError carries status code, errorType, and responseData', () => {
  const err = new ApiClientError('Invalid scenario', 'not_found', 404, { detail: 'Scenario not allowed' });
  assert.strictEqual(err.statusCode, 404);
  assert.strictEqual(err.errorType, 'not_found');
  assert.deepStrictEqual(err.responseData, { detail: 'Scenario not allowed' });
  assert.strictEqual(err.message, 'Invalid scenario');
});

test('apiRequest handles empty responses and non-2xx statuses via mock fetch', async () => {
  const originalFetch = globalThis.fetch;

  try {
    // 1. Mock 204 No Content
    globalThis.fetch = async () =>
      new Response(null, {
        status: 204,
        statusText: 'No Content',
      });

    const res204 = await apiRequest('/alerts/alt_01/acknowledge', { method: 'POST' });
    assert.strictEqual(res204, null);

    // 2. Mock 401 Unauthorized with FastAPI detail payload
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: 'Token has expired' }), {
        status: 401,
        statusText: 'Unauthorized',
        headers: { 'Content-Type': 'application/json' },
      });

    await assert.rejects(
      async () => {
        await apiRequest('/me');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.statusCode, 401);
        assert.strictEqual(err.errorType, 'unauthorized');
        assert.strictEqual(err.message, 'Token has expired');
        assert.deepStrictEqual(err.responseData, { detail: 'Token has expired' });
        return true;
      }
    );

    // 3. Mock 403 Forbidden with custom detail
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: 'Doctor is not assigned to patient P103' }), {
        status: 403,
        statusText: 'Forbidden',
        headers: { 'Content-Type': 'application/json' },
      });

    await assert.rejects(
      async () => {
        await apiRequest('/patients/P103/vitals');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.statusCode, 403);
        assert.strictEqual(err.errorType, 'forbidden');
        assert.strictEqual(err.message, 'Doctor is not assigned to patient P103');
        return true;
      }
    );

    // 4. Mock 500 Server Error
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: 'Database connection failed' }), {
        status: 500,
        statusText: 'Internal Server Error',
        headers: { 'Content-Type': 'application/json' },
      });

    await assert.rejects(
      async () => {
        await apiRequest('/patients');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.statusCode, 500);
        assert.strictEqual(err.errorType, 'server_error');
        assert.strictEqual(err.message, 'Database connection failed');
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
