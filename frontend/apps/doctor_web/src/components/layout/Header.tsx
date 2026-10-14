import React from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth, useDevMode } from '../../hooks';
import { MenuIcon, BellIcon } from '../ui/Icons';
import styles from './Header.module.css';

interface HeaderProps {
  onToggleMenu?: () => void;
  isMenuOpen?: boolean;
}

interface RouteMeta {
  title: string;
  breadcrumb: string;
}

function resolveRouteMeta(pathname: string): RouteMeta {
  if (pathname === '/dashboard') {
    return { title: 'Workstation Overview', breadcrumb: 'Dashboard / Overview' };
  }
  if (pathname === '/patients') {
    return { title: 'Assigned Patients', breadcrumb: 'Directory / Patients' };
  }
  if (pathname.startsWith('/patients/')) {
    const id = pathname.replace('/patients/', '');
    return { title: `Patient ${id}`, breadcrumb: `Patients / ${id}` };
  }
  if (pathname === '/alerts') {
    return { title: 'Clinical Review Alerts', breadcrumb: 'Surveillance / Alerts' };
  }
  if (pathname === '/messages') {
    return { title: 'Patient Consultations', breadcrumb: 'Comms / Messages' };
  }
  if (pathname === '/system-status') {
    return { title: 'System & Gateway Status', breadcrumb: 'Operations / Status' };
  }
  if (pathname === '/settings') {
    return { title: 'Workstation Settings', breadcrumb: 'Config / Settings' };
  }
  return { title: 'Clinical Workstation', breadcrumb: 'System' };
}

export const Header: React.FC<HeaderProps> = ({ onToggleMenu, isMenuOpen }) => {
  const location = useLocation();
  const { currentUser } = useAuth();
  const { isFixtureMode, toggleFixtureMode } = useDevMode();
  const meta = resolveRouteMeta(location.pathname);

  return (
    <header className={styles.header} role="banner">
      <div className={styles.left}>
        {onToggleMenu && (
          <button
            type="button"
            className={styles.menuButton}
            onClick={onToggleMenu}
            aria-label={isMenuOpen ? 'Close navigation drawer' : 'Open navigation drawer'}
            aria-expanded={isMenuOpen}
          >
            <MenuIcon size={18} />
          </button>
        )}

        <div className={styles.breadcrumbGroup}>
          <span className={styles.sectionTitle}>{meta.title}</span>
          <span className={styles.breadcrumbPath} aria-hidden="true">
            ({meta.breadcrumb})
          </span>
        </div>
      </div>

      <div className={styles.right}>
        {/* Explicit Development Mode Toggle */}
        <button
          type="button"
          onClick={toggleFixtureMode}
          className={`${styles.modeButton} ${
            isFixtureMode ? styles.modeButtonFixture : styles.modeButtonLive
          }`}
          title={
            isFixtureMode
              ? 'Demo Mode active (Isolated Kaggle cohort P101–P105, simulated data). Click to switch to Live Gateway mode.'
              : 'Live Gateway Mode active (FastAPI at localhost:8000). Click to switch to Demo Mode.'
          }
        >
          <span
            className={isFixtureMode ? styles.fixtureDot : styles.liveDot}
            aria-hidden="true"
          />
          <span>{isFixtureMode ? 'DEMO MODE — SIMULATED DATA' : 'Live Gateway'}</span>
        </button>

        {/* Backend connectivity indicator (honest offline/unconnected status) */}
        <div
          className={styles.connectivityIndicator}
          role="status"
          title={
            isFixtureMode
              ? 'Demo Mode active: Using isolated Kaggle records. FastAPI gateway offline.'
              : 'FastAPI Backend Gateway (http://localhost:8000) not connected.'
          }
        >
          <span className={styles.offlineDot} aria-hidden="true" />
          <span>Gateway: Disconnected</span>
        </div>

        {/* Notification control placeholder */}
        <button
          type="button"
          className={styles.notificationButton}
          title="Notifications (0 unread)"
          aria-label="Notifications (0 unread)"
        >
          <BellIcon size={16} />
        </button>

        {/* User Identity Chip */}
        {currentUser ? (
          <div className={styles.userBadge}>
            <span className={styles.userName}>{currentUser.name}</span>
            <span className={styles.userRole}>
              {isFixtureMode ? '[DEMO SESSION]' : `[${currentUser.role}]`}
            </span>
          </div>
        ) : (
          <div className={styles.userBadge}>
            <span className={styles.userName}>Unauthenticated</span>
          </div>
        )}
      </div>
    </header>
  );
};
