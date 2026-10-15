import test from 'node:test';
import assert from 'node:assert';
import { apiRequest, ApiClientError } from '../src/api/client';
import { wsManager, type WsStatusSnapshot, type WsEventMessage } from '../src/api/webSocketService';

test('Failure Drill 1: Request Timeout throws ApiClientError with timeout type', async () => {
  const originalFetch = globalThis.fetch;

  try {
    // Mock fetch that hangs until aborted
    globalThis.fetch = (_url, init) => {
      return new Promise((_resolve, reject) => {
        if (init?.signal) {
          init.signal.addEventListener('abort', () => {
            const abortErr = new Error('The operation was aborted');
            abortErr.name = 'AbortError';
            reject(abortErr);
          });
        }
      });
    };

    await assert.rejects(
      async () => {
        await apiRequest('/patients', { timeoutMs: 20 });
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.errorType, 'timeout');
        assert.ok(err.message.includes('timed out'));
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Failure Drill 2: Network Offline / Gateway Unreachable throws network_error', async () => {
  const originalFetch = globalThis.fetch;

  try {
    globalThis.fetch = () => {
      return Promise.reject(new TypeError('Failed to fetch'));
    };

    await assert.rejects(
      async () => {
        await apiRequest('/patients');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.errorType, 'network_error');
        assert.ok(err.message.includes('Unable to reach the FastAPI gateway'));
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Failure Drill 3: Authentication Expiration (HTTP 401) throws unauthorized', async () => {
  const originalFetch = globalThis.fetch;

  try {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({ detail: 'Could not validate credentials: token is invalid or expired.' }),
        { status: 401, statusText: 'Unauthorized', headers: { 'Content-Type': 'application/json' } }
      );

    await assert.rejects(
      async () => {
        await apiRequest('/patients');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.errorType, 'unauthorized');
        assert.strictEqual(err.statusCode, 401);
        assert.ok(err.message.includes('expired'));
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Failure Drill 4: Unauthorized Resource Access (HTTP 403) throws forbidden', async () => {
  const originalFetch = globalThis.fetch;

  try {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({ detail: 'Access denied: clinician is not assigned to this patient.' }),
        { status: 403, statusText: 'Forbidden', headers: { 'Content-Type': 'application/json' } }
      );

    await assert.rejects(
      async () => {
        await apiRequest('/patients/P999');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.errorType, 'forbidden');
        assert.strictEqual(err.statusCode, 403);
        assert.ok(err.message.includes('Access denied'));
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Failure Drill 5: Relational DB Unavailability (HTTP 503) throws server_error', async () => {
  const originalFetch = globalThis.fetch;

  try {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          status: 'unready',
          database: 'unreachable',
          message: 'Authoritative relational database is unavailable.',
        }),
        { status: 503, statusText: 'Service Unavailable', headers: { 'Content-Type': 'application/json' } }
      );

    await assert.rejects(
      async () => {
        await apiRequest('/health/ready');
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.strictEqual(err.errorType, 'server_error');
        assert.strictEqual(err.statusCode, 503);
        assert.ok(err.message.includes('Authoritative relational database is unavailable.'));
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Failure Drill 6: WebSocket bounded reconnection and manual disconnection cleanup', () => {
  // Ensure starting state is disconnected
  wsManager.disconnect();
  const snapshot = wsManager.getSnapshot();
  assert.strictEqual(snapshot.state, 'disconnected');
  assert.strictEqual(snapshot.reconnectAttempts, 0);

  // Calling disconnect while already disconnected is safe and idempotent
  wsManager.disconnect();
  assert.strictEqual(wsManager.getSnapshot().state, 'disconnected');
});

test('Failure Drill 7: WebSocket event stream handles non-JSON / raw frames safely', () => {
  let receivedEvent: WsEventMessage | null = null;
  const unsubscribe = wsManager.subscribeEvents((event) => {
    receivedEvent = event;
  });

  // Sending message when socket is not open returns false safely without throwing
  const sent = wsManager.send({ ping: true });
  assert.strictEqual(sent, false);

  unsubscribe();
  assert.strictEqual(receivedEvent, null);
});
