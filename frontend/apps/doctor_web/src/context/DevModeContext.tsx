import React, { useState, useCallback, useMemo } from 'react';
import { DevModeContext, type DevModeContextType } from './devModeContextDefinition';

/**
 * SMART HEALTH MONITORING SYSTEM — FRONTEND DEMO MODE PROVIDER
 * 
 * Provides unified, application-wide configuration for Frontend Demo Mode:
 * 1. Clearly labels application as using simulated demonstration data.
 * 2. Never silently falls back to fixtures after a failed API request.
 * 3. Keeps mock data strictly separate from live API responses.
 * 4. Enables global toggling between Demo Mode (Simulated Data) and Live Gateway.
 * 5. Persists choice across page reloads in sessionStorage.
 */

const STORAGE_KEY = 'shm_dev_fixture_mode';

export const DevModeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Default to false (Live Gateway Mode) as FastAPI backend and ML services are operational
  const [isDemoMode, setIsDemoModeState] = useState<boolean>(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        return saved === 'true';
      }
    } catch {
      // storage unavailable
    }
    return false;
  });

  const setDemoMode = useCallback((value: boolean) => {
    setIsDemoModeState(value);
    try {
      sessionStorage.setItem(STORAGE_KEY, String(value));
    } catch {
      // ignore
    }
  }, []);

  const toggleDemoMode = useCallback(() => {
    setIsDemoModeState((prev) => {
      const next = !prev;
      try {
        sessionStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  const value = useMemo<DevModeContextType>(
    () => ({
      isDemoMode,
      isFixtureMode: isDemoMode,
      setDemoMode,
      setFixtureMode: setDemoMode,
      toggleDemoMode,
      toggleFixtureMode: toggleDemoMode,
    }),
    [isDemoMode, setDemoMode, toggleDemoMode]
  );

  return <DevModeContext.Provider value={value}>{children}</DevModeContext.Provider>;
};
