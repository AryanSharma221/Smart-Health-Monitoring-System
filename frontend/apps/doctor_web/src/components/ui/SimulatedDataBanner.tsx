import React from 'react';
import { useDevMode } from '../../hooks';
import styles from './SimulatedDataBanner.module.css';

interface SimulatedDataBannerProps {
  /** Optional supplementary notice */
  detail?: string;
}

/**
 * Reusable, persistent clinical warning banner.
 * Mandatory on all clinical monitoring views per system documentation.
 * Displays both:
 * - 'DEMO MODE — SIMULATED DATA' (when demo mode is active)
 * - 'SIMULATED DATA — NOT FOR MEDICAL USE'
 */
export const SimulatedDataBanner: React.FC<SimulatedDataBannerProps> = ({ detail }) => {
  const { isFixtureMode } = useDevMode();

  const defaultExplanation = isFixtureMode
    ? 'Viewing isolated Kaggle P101–P105 demonstration cohort. FastAPI gateway (http://localhost:8000) and ML inference service not connected.'
    : 'Live Gateway Mode: Configured to FastAPI at http://localhost:8000. Telemetry from simulator or live feed.';

  return (
    <div
      className={styles.banner}
      role="region"
      aria-label="Clinical Simulation Notice"
    >
      <div className={styles.content}>
        <span className={styles.badge}>Advisory</span>
        <span className={styles.message}>
          SIMULATED DATA — NOT FOR MEDICAL USE
        </span>
        <span className={styles.explanation}>{detail || defaultExplanation}</span>
      </div>
      <span className={styles.environment}>
        {isFixtureMode ? 'DEMO MODE — SIMULATED DATA' : 'LIVE GATEWAY'}
      </span>
    </div>
  );
};
