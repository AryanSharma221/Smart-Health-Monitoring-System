import { Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom';
import { useAuth } from '../hooks';
import { AppLayout } from '../components/layout';
import {
  LoginPage,
  DashboardPage,
  PatientsPage,
  PatientDetailPage,
  AlertsPage,
  MessagesPage,
  SystemStatusPage,
  SettingsPage,
  NotFoundPage,
} from '../pages';

/**
 * Route protection guard.
 * Redirects unauthenticated requests to /login while preserving attempted location.
 */
const ProtectedRoute: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
};

/**
 * Patient detail route wrapper.
 * Providing key={patientId} guarantees complete state reset when switching between patients.
 */
const PatientDetailRoute: React.FC = () => {
  const { patientId } = useParams<{ patientId: string }>();
  return <PatientDetailPage key={patientId} />;
};

/**
 * Root route resolver:
 * - If authenticated -> /dashboard
 * - If unauthenticated -> /login
 */
const RootRedirect: React.FC = () => {
  const { isAuthenticated } = useAuth();
  return <Navigate to={isAuthenticated ? '/dashboard' : '/login'} replace />;
};

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      {/* Root redirect based on auth status */}
      <Route path="/" element={<RootRedirect />} />

      {/* Public Login Route */}
      <Route path="/login" element={<LoginPage />} />

      {/* Authenticated Clinical Workstation Layout & Sub-routes */}
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/patients" element={<PatientsPage />} />
        <Route path="/patients/:patientId" element={<PatientDetailRoute />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/messages" element={<MessagesPage />} />
        <Route path="/system-status" element={<SystemStatusPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      {/* Fallback 404 Route */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
};
