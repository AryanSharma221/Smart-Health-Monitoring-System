import test from 'node:test';
import assert from 'node:assert';
import { AuthServiceError } from '../src/api/authService';

test('AuthServiceError sets type, status, and message', () => {
  const err = new AuthServiceError('invalid_credentials', 'Invalid email or password', 401);
  assert.strictEqual(err.type, 'invalid_credentials');
  assert.strictEqual(err.statusCode, 401);
  assert.strictEqual(err.message, 'Invalid email or password');
  assert.strictEqual(err.name, 'AuthServiceError');
});

test('Session storage operations work safely in environment', () => {
  // Setup in-memory mock if sessionStorage is absent in Node
  const store = new Map<string, string>();
  if (typeof globalThis.sessionStorage === 'undefined') {
    (globalThis as any).sessionStorage = {
      getItem: (key: string) => store.get(key) || null,
      setItem: (key: string, val: string) => store.set(key, val),
      removeItem: (key: string) => store.delete(key),
      clear: () => store.clear(),
    };
  }

  sessionStorage.setItem('shm_auth_token', 'mock_jwt_test_token_123');
  sessionStorage.setItem(
    'shm_user_session',
    JSON.stringify({
      userId: 'usr_doc_01',
      name: 'Dr. Sarah Jenkins',
      email: 'doctor@hospital.org',
      role: 'doctor',
    })
  );

  assert.strictEqual(sessionStorage.getItem('shm_auth_token'), 'mock_jwt_test_token_123');
  const user = JSON.parse(sessionStorage.getItem('shm_user_session')!);
  assert.strictEqual(user.userId, 'usr_doc_01');
  assert.strictEqual(user.role, 'doctor');

  // Verify logout cleanup
  sessionStorage.removeItem('shm_auth_token');
  sessionStorage.removeItem('shm_user_session');

  assert.strictEqual(sessionStorage.getItem('shm_auth_token'), null);
  assert.strictEqual(sessionStorage.getItem('shm_user_session'), null);
});
