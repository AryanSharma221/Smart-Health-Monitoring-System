import { createContext } from 'react';
import type { UserSession } from '../types';
import type { LoginCredentials } from '../api';

export type AuthStatus =
  | 'unauthenticated'
  | 'authenticating'
  | 'authenticated'
  | 'auth_failed'
  | 'session_expired';

export interface AuthContextValue {
  status: AuthStatus;
  isAuthenticated: boolean;
  isLoading: boolean;
  currentUser: UserSession | null;
  authError: string | null;
  login: (credentials: LoginCredentials) => Promise<boolean>;
  loginDemo: () => void;
  logout: () => void;
  clearAuthError: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
