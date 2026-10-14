import { createContext } from 'react';

/**
 * SMART HEALTH MONITORING SYSTEM — FRONTEND DEMO MODE CONTEXT DEFINITION
 *
 * Separated context definition to ensure Fast Refresh compliance
 * and clean decoupling between context, provider, and consumer hook.
 */

export interface DevModeContextType {
  /** Indicates whether the application is running in isolated Frontend Demo Mode */
  isDemoMode: boolean;
  /** Backwards-compatible alias for isDemoMode */
  isFixtureMode: boolean;
  /** Explicitly enables or disables Frontend Demo Mode */
  setDemoMode: (enabled: boolean) => void;
  /** Backwards-compatible alias for setDemoMode */
  setFixtureMode: (enabled: boolean) => void;
  /** Toggles between Frontend Demo Mode and Live Gateway Mode */
  toggleDemoMode: () => void;
  /** Backwards-compatible alias for toggleDemoMode */
  toggleFixtureMode: () => void;
}

export const DevModeContext = createContext<DevModeContextType | undefined>(undefined);
