import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth, useDevMode } from '../../hooks';
import {
  wsManager,
  type WsStatusSnapshot,
  fetchSimulatorStatus,
  startSimulator,
  stopSimulator,
  type SimulatorLifecycleState,
} from '../../api';
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
  if (pathname === '/evaluation') {
    return { title: 'DA3 Evaluation Console', breadcrumb: 'Academic / DA3 Console' };
  }
  return { title: 'Clinical Workstation', breadcrumb: 'System' };
}

export const Header: React.FC<HeaderProps> = ({ onToggleMenu, isMenuOpen }) => {
  const location = useLocation();
  const { currentUser } = useAuth();
  const { isFixtureMode, toggleFixtureMode } = useDevMode();
  const [wsSnapshot, setWsSnapshot] = useState<WsStatusSnapshot>(() => wsManager.getSnapshot());
  const [simState, setSimState] = useState<SimulatorLifecycleState | 'UNKNOWN'>('UNKNOWN');
  const [simTransitioning, setSimTransitioning] = useState<boolean>(false);
  const meta = resolveRouteMeta(location.pathname);

  // Poll simulator status periodically and sync across components
  const pollSimStatus = React.useCallback(async () => {
    try {
      const res = await fetchSimulatorStatus();
      if (res && res.simulator) {
        setSimState(res.simulator.lifecycle_state || (res.simulator.is_running ? 'RUNNING' : 'STOPPED'));
      }
    } catch {
      setSimState('UNKNOWN');
    }
  }, []);

  useEffect(() => {
    void pollSimStatus();
    const interval = setInterval(() => {
      void pollSimStatus();
    }, 4000);

    const handleCustomChange = (e: Event) => {
      const customEvent = e as CustomEvent<{ state: SimulatorLifecycleState }>;
      if (customEvent.detail?.state) {
        setSimState(customEvent.detail.state);
      } else {
        void pollSimStatus();
      }
    };

    window.addEventListener('simulator-state-changed', handleCustomChange);

    return () => {
      clearInterval(interval);
      window.removeEventListener('simulator-state-changed', handleCustomChange);
    };
  }, [pollSimStatus]);

  const handleToggleSimulator = async () => {
    if (simTransitioning) return;
    setSimTransitioning(true);
    try {
      if (simState === 'RUNNING') {
        const res = await stopSimulator();
        const newState = res.lifecycle_state || 'STOPPED';
        setSimState(newState);
        window.dispatchEvent(new CustomEvent('simulator-state-changed', { detail: { state: newState } }));
      } else {
        const res = await startSimulator();
        const newState = res.lifecycle_state || 'RUNNING';
        setSimState(newState);
        window.dispatchEvent(new CustomEvent('simulator-state-changed', { detail: { state: newState } }));
      }
    } catch (err) {
      console.error('Failed to toggle simulator:', err);
    } finally {
      setSimTransitioning(false);
    }
  };

  useEffect(() => {
    const unsub = wsManager.subscribeStatus((snap) => {
      setWsSnapshot(snap);
    });
    return () => {
      unsub();
    };
  }, []);

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

        {/* Synthetic Telemetry Data Generation Start/Stop Control */}
        <button
          type="button"
          onClick={() => void handleToggleSimulator()}
          disabled={simTransitioning}
          className={`${styles.simButton} ${
            simState === 'RUNNING' ? styles.simButtonRunning : styles.simButtonStopped
          }`}
          title={
            simState === 'RUNNING'
              ? 'Wearable telemetry generator is ACTIVE. Click to stop synthetic data generation.'
              : 'Wearable telemetry generator is STOPPED. Click to start synthetic data generation.'
          }
          aria-label={
            simState === 'RUNNING'
              ? 'Stop synthetic telemetry data generation'
              : 'Start synthetic telemetry data generation'
          }
        >
          <span
            className={simState === 'RUNNING' ? styles.simPulseDot : styles.simStoppedDot}
            aria-hidden="true"
          />
          <span>
            {simTransitioning
              ? simState === 'RUNNING'
                ? 'Stopping…'
                : 'Starting…'
              : simState === 'RUNNING'
              ? 'Stop Data Gen'
              : 'Start Data Gen'}
          </span>
        </button>

        {/* Backend connectivity & WebSocket indicator */}
        <div
          className={styles.connectivityIndicator}
          role="status"
          title={
            isFixtureMode
              ? 'Demo Mode active: Using isolated Kaggle records. FastAPI gateway offline.'
              : wsSnapshot.state === 'connected'
              ? 'FastAPI WebSocket stream connected (ws://localhost:8000/ws/v1/updates).'
              : wsSnapshot.state === 'connecting' || wsSnapshot.state === 'reconnecting'
              ? 'FastAPI WebSocket stream connecting...'
              : 'FastAPI WebSocket stream disconnected. Using HTTP polling fallback.'
          }
        >
          <span
            className={
              isFixtureMode
                ? styles.fixtureDot
                : wsSnapshot.state === 'connected'
                ? styles.liveDot
                : wsSnapshot.state === 'connecting' || wsSnapshot.state === 'reconnecting'
                ? styles.connectingDot
                : styles.offlineDot
            }
            aria-hidden="true"
          />
          <span>
            {isFixtureMode
              ? 'Gateway: Demo'
              : wsSnapshot.state === 'connected'
              ? 'Stream: Live'
              : wsSnapshot.state === 'connecting' || wsSnapshot.state === 'reconnecting'
              ? 'Stream: Connecting…'
              : 'Stream: Polling'}
          </span>
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
