import { useContext } from 'react';
import { DevModeContext, type DevModeContextType } from '../context/devModeContextDefinition';

/**
 * Hook to access and toggle Development Fixture Mode.
 * Throws an explicit error if called outside DevModeProvider.
 */
export function useDevMode(): DevModeContextType {
  const context = useContext(DevModeContext);
  if (!context) {
    throw new Error('useDevMode must be used within a DevModeProvider');
  }
  return context;
}
