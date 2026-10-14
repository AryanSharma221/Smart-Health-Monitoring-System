import React, { useState, useEffect, useMemo, useCallback, type ReactNode } from 'react';
import type { UserSession } from '../types';
import {
  loginWithCredentials,
  getPersistedSession,
  clearStoredSession,
  getClinicianProfile,
  ApiClientError,
  AuthServiceError,
  type LoginCredentials,
} from '../api';
import { useDevMode } from '../hooks';
import { AuthContext, type AuthStatus } from './context';

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { isFixtureMode, setFixtureMode } = useDevMode();

  // Initialize from sessionStorage if a verified session was saved earlier
  const initialSession = getPersistedSession();
  const [currentUser, setCurrentUser] = useState<UserSession | null>(
    initialSession ? initialSession.user : null
  );
  const [status, setStatus] = useState<AuthStatus>(
    initialSession ? 'authenticated' : 'unauthenticated'
  );
  const [authError, setAuthError] = useState<string | null>(null);

  // Invalidate demo session immediately if user switches from Demo Mode to Live Gateway Mode
  useEffect(() => {
    if (!isFixtureMode) {
      const session = getPersistedSession();
      if (session && session.token === 'demo_offline_token_p101_p105') {
        clearStoredSession();
        queueMicrotask(() => {
          setCurrentUser(null);
          setStatus('unauthenticated');
          setAuthError('Demo session invalidated: Live Gateway mode requires verified clinician credentials.');
        });
      }
    }
  }, [isFixtureMode]);

  // Validate existing session against GET /api/v1/me on initial load
  useEffect(() => {
    const session = getPersistedSession();
    if (!session) return;

    // If this is an offline simulated demo session, retain without probing offline gateway
    if (session.token === 'demo_offline_token_p101_p105') {
      return;
    }

    let isCancelled = false;

    async function validateSession() {
      try {
        const liveProfile = await getClinicianProfile();
        if (!isCancelled) {
          setCurrentUser(liveProfile);
          setStatus('authenticated');
        }
      } catch (err: unknown) {
        if (isCancelled) return;
        // If 401 Unauthorized, session token is expired or invalidated
        if (err instanceof ApiClientError && err.statusCode === 401) {
          clearStoredSession();
          setCurrentUser(null);
          setStatus('session_expired');
          setAuthError('Your session has expired. Please sign in again.');
        }
        // If gateway is offline, keep persisted session so visual verification remains functional
      }
    }

    void validateSession();

    return () => {
      isCancelled = true;
    };
  }, []);

  const login = useCallback(async (credentials: LoginCredentials): Promise<boolean> => {
    setStatus('authenticating');
    setAuthError(null);

    try {
      const response = await loginWithCredentials(credentials);
      setCurrentUser(response.user);
      setStatus('authenticated');
      return true;
    } catch (err: unknown) {
      setCurrentUser(null);
      setStatus('auth_failed');

      if (err instanceof AuthServiceError) {
        setAuthError(err.message);
      } else if (err instanceof Error) {
        setAuthError(err.message);
      } else {
        setAuthError('An unexpected error occurred during authentication.');
      }
      return false;
    }
  }, []);

  const loginDemo = useCallback(() => {
    // Ensure Demo Mode is active when demo login is triggered
    setFixtureMode(true);
    const demoUser: UserSession = {
      userId: 'usr_doc_01',
      email: 'dr.demo@hospital.org',
      name: 'Dr. Sarah Jenkins',
      role: 'doctor',
      licenseNumber: 'MD-94821 [DEMO SESSION]',
    };
    sessionStorage.setItem('shm_auth_token', 'demo_offline_token_p101_p105');
    sessionStorage.setItem('shm_user_session', JSON.stringify(demoUser));
    setCurrentUser(demoUser);
    setStatus('authenticated');
    setAuthError(null);
  }, [setFixtureMode]);

  const logout = useCallback(() => {
    clearStoredSession();
    setCurrentUser(null);
    setStatus('unauthenticated');
    setAuthError(null);
  }, []);

  const clearAuthError = useCallback(() => {
    setAuthError(null);
  }, []);

  const value = useMemo(
    () => ({
      status,
      isAuthenticated: status === 'authenticated' && currentUser !== null,
      isLoading: status === 'authenticating',
      currentUser,
      authError,
      login,
      loginDemo,
      logout,
      clearAuthError,
    }),
    [status, currentUser, authError, login, loginDemo, logout, clearAuthError]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
