import React, { useState, useEffect, useCallback } from 'react';
import {
  API_CONFIG,
  startDemoRun,
  stopDemoRun,
  switchDemoScenario,
  getDemoRunStatus,
  resetFixtureData,
  type DemoScenario,
  type DemoRun,
} from '../api';
import { useDevMode } from '../hooks';
import {
  SimulatedDataBanner,
  PageHeader,
  Button,
  Select,
  TextInput,
  StatusBadge,
  RefreshIcon,
  CheckCircleIcon,
  AlertTriangleIcon,
} from '../components/ui';
import { formatTimestamp } from '../utils/formatters';
import styles from './SettingsPage.module.css';

const SCENARIO_OPTIONS: { value: DemoScenario; label: string; description: string }[] = [
  {
    value: 'normal',
    label: 'Normal Telemetry (Physiological Baseline)',
    description:
      'Emits normal ambulatory vital readings with natural diurnal drift (HR 68–78 bpm, SpO2 97–99%, Temp 98.4–98.8°F). Tests nominal pipeline throughput and baseline graphing.',
  },
  {
    value: 'single_anomaly',
    label: 'Single Anomaly (Acute Threshold Spike)',
    description:
      'Injects an isolated acute threshold breach (e.g. abrupt tachycardia HR > 125 bpm or sudden desaturation SpO2 < 89%). Evaluates deterministic rule engine and priority alert dispatch.',
  },
  {
    value: 'combined_anomaly',
    label: 'Combined Anomaly (Predefined Simulated Pattern)',
    description:
      'Simultaneously drifts multiple metrics (elevated HR + borderline low SpO2 + elevated Temp) without any individual metric crossing hard cutoffs. Predefined simulated pattern designed for testing future multivariate anomaly scoring.',
  },
  {
    value: 'missing_data',
    label: 'Missing Data (Sensor Disconnect / Packet Loss)',
    description:
      'Simulates dropped wireless packets or decoupled leads by omitting sensor values from telemetry payloads. Verifies robust frontend missing-value handling ("—" unavailable indicators).',
  },
  {
    value: 'stale_data',
    label: 'Stale Data (Delayed Timestamps & Latency)',
    description:
      'Transmits readings with artificially delayed timestamps (> 60–120s old). Evaluates frontend data freshness monitors, latency counters, and automated stale warnings.',
  },
  {
    value: 'recovery',
    label: 'Recovery Sequence (Gradual Normalization)',
    description:
      'Progressively steers anomalous vitals back to stable clinical baselines over consecutive intervals. Evaluates resolution workflows and recovery visualization.',
  },
];

const PATIENT_OPTIONS = [
  { value: 'P101', label: 'P101 — Kaggle Cohort (Eleanor Vance, 44M)' },
  { value: 'P102', label: 'P102 — Kaggle Cohort (Arthur Pendelton, 51F)' },
  { value: 'P103', label: 'P103 — Kaggle Cohort (Robert Diaz, 62M)' },
  { value: 'P104', label: 'P104 — Kaggle Cohort (Sophia Chen, 35F)' },
  { value: 'P105', label: 'P105 — Kaggle Cohort (Marcus Brody, 58M)' },
];

export const SettingsPage: React.FC = () => {
  const { isFixtureMode, toggleFixtureMode } = useDevMode();
  const [patientId, setPatientId] = useState<string>('P101');
  const [scenario, setScenario] = useState<DemoScenario>('normal');
  const [intervalSeconds, setIntervalSeconds] = useState<number>(5);

  const [activeRun, setActiveRun] = useState<DemoRun | null>(null);
  const [actionPending, setActionPending] = useState<boolean>(false);
  const [polling, setPolling] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const selectedScenarioMeta = SCENARIO_OPTIONS.find((s) => s.value === scenario);

  // Poll status when run is in progress
  const checkRunStatus = useCallback(async () => {
    if (!activeRun?.runId) return;
    setPolling(true);
    try {
      const status = await getDemoRunStatus(activeRun.runId, isFixtureMode);
      if (status) {
        setActiveRun(status);
      }
    } catch {
      // Background poll failure is non-fatal
    } finally {
      setPolling(false);
    }
  }, [activeRun, isFixtureMode]);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;
    if (activeRun && activeRun.state === 'running' && !isFixtureMode) {
      interval = setInterval(() => {
        void checkRunStatus();
      }, 5000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [activeRun, isFixtureMode, checkRunStatus]);

  // Handle Starting Demo Run
  const handleStartRun = async () => {
    setActionPending(true);
    setFeedback(null);

    if (isFixtureMode) {
      setActionPending(false);
      setFeedback({
        type: 'error',
        message: `Backend Not Connected: Simulation runs require the active FastAPI backend service (http://localhost:8000). Scenario "${scenario}" parameters for ${patientId} (${intervalSeconds}s interval) are preserved in local preview settings without simulating a background run.`,
      });
      return;
    }

    try {
      const run = await startDemoRun(
        {
          patientId,
          scenario,
          intervalSeconds,
        },
        false
      );
      setActiveRun(run);
      setFeedback({
        type: 'success',
        message: `Simulation run ${run.runId} initiated for ${patientId} (${scenario}) with ${intervalSeconds}s interval.`,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to start demo simulation run.';
      setFeedback({
        type: 'error',
        message: `${msg} (FastAPI gateway at ${API_CONFIG.baseUrl} is not connected).`,
      });
    } finally {
      setActionPending(false);
    }
  };

  // Handle Halting Demo Run
  const handleStopRun = async () => {
    if (!activeRun) return;
    setActionPending(true);
    setFeedback(null);
    try {
      const stopped = await stopDemoRun(activeRun.runId, isFixtureMode);
      setActiveRun(stopped);
      setFeedback({
        type: 'success',
        message: `Simulation run ${activeRun.runId} successfully halted. Telemetry stream stopped.`,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to halt demo simulation run.';
      setFeedback({
        type: 'error',
        message: msg,
      });
    } finally {
      setActionPending(false);
    }
  };

  // Handle Switching Active Scenario
  const handleSwitchScenario = async () => {
    if (!activeRun) return;
    setActionPending(true);
    setFeedback(null);
    try {
      const updated = await switchDemoScenario(activeRun.runId, scenario, isFixtureMode);
      setActiveRun(updated);
      setFeedback({
        type: 'success',
        message: `Scenario switched to "${scenario}" on active run ${activeRun.runId}.`,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to switch demo scenario.';
      setFeedback({
        type: 'error',
        message: msg,
      });
    } finally {
      setActionPending(false);
    }
  };

  // Reset Demo Fixture Data to initial benchmark baseline
  const handleResetDemoData = () => {
    resetFixtureData();
    setFeedback({
      type: 'success',
      message: 'Demonstration baseline reset: All 5 Kaggle cohort alerts (P101–P105) and consultation message threads have been restored to initial presentation states.',
    });
  };

  const isRunActive = activeRun?.state === 'running';

  return (
    <div className={styles.container}>
      {/* 1. Safety Boundary Warning */}
      <SimulatedDataBanner detail="Simulation Workstation: All injected and generated signals are synthetic. NOT FOR MEDICAL USE." />

      {/* Fixture Mode Notification */}
      <div className={styles.fixtureNotice} role="region" aria-label="Development fixture notification">
        <div className={styles.fixtureText}>
          <span className={styles.fixtureTag}>
            {isFixtureMode ? 'Fixtures Active' : 'Live Gateway'}
          </span>
          <span>
            {isFixtureMode ? (
              <>
                <strong>Development Fixture Mode:</strong> Viewing isolated Kaggle demonstration cohort (P101–P105). Live telemetry execution and background simulation runs require the FastAPI service (<code>localhost:8000</code>).
              </>
            ) : (
              <>
                <strong>Live FastAPI Gateway Mode:</strong> Commands are routed directly to <code>{API_CONFIG.baseUrl}/demo/runs</code>. Requires active backend process.
              </>
            )}
          </span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            toggleFixtureMode();
            setFeedback(null);
          }}
        >
          {isFixtureMode ? 'Switch to Live Gateway' : 'Switch to Dev Fixtures'}
        </Button>
      </div>

      {/* Header */}
      <header className={styles.headerSection}>
        <PageHeader
          title="Demo Controls & Workstation Settings"
          subtitle="Direct the telemetry generator, orchestrate clinical anomaly scenarios, and verify architectural parameters."
          breadcrumb="Config / Settings"
        />
      </header>

      {/* Feedback Alert */}
      {feedback && (
        <div
          className={`${styles.feedbackBanner} ${
            feedback.type === 'success' ? styles.feedbackSuccess : styles.feedbackError
          }`}
          role="alert"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {feedback.type === 'success' ? (
              <CheckCircleIcon size={16} />
            ) : (
              <AlertTriangleIcon size={16} />
            )}
            <span>{feedback.message}</span>
          </div>
        </div>
      )}

      {/* 2. Interactive Simulation Workstation Card */}
      <section className={styles.card} aria-labelledby="simulator-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="simulator-heading" className={styles.cardTitle}>
              Telemetry Stream Orchestration
            </h2>
            <p className={styles.cardSubtitle}>
              Select a target patient, configure an anomaly profile, and trigger the telemetry generator.
            </p>
          </div>
          {activeRun && (
            <StatusBadge
              variant={isRunActive ? 'fresh' : 'info'}
              label={isRunActive ? 'RUNNING' : activeRun.state.toUpperCase()}
            />
          )}
        </div>

        {/* Inputs Grid */}
        <div className={styles.controlsGrid}>
          <div className={styles.inputGroup}>
            <Select
              label="Target Patient"
              value={patientId}
              onChange={(e) => setPatientId(e.target.value)}
              disabled={isRunActive || actionPending}
              options={PATIENT_OPTIONS}
            />
          </div>

          <div className={styles.inputGroup}>
            <Select
              label="Simulation Scenario"
              value={scenario}
              onChange={(e) => setScenario(e.target.value as DemoScenario)}
              disabled={actionPending}
              options={SCENARIO_OPTIONS.map((s) => ({ value: s.value, label: s.label }))}
            />
          </div>

          <div className={styles.inputGroup}>
            <TextInput
              label="Push Interval (Seconds)"
              type="number"
              min={1}
              max={60}
              value={intervalSeconds}
              onChange={(e) => setIntervalSeconds(Math.max(1, Math.min(60, Number(e.target.value) || 5)))}
              disabled={isRunActive || actionPending}
              helperText="1–60s cadence (5s default recommended)"
            />
          </div>
        </div>

        {/* Dynamic Scenario Clinical Explanation */}
        {selectedScenarioMeta && (
          <div className={styles.scenarioDescriptionBox}>
            <strong>Clinical Scenario Context:</strong> {selectedScenarioMeta.description}
          </div>
        )}

        {/* Simulation Action Controls */}
        <div className={styles.buttonRow}>
          {!isRunActive ? (
            <Button
              variant="primary"
              size="md"
              onClick={handleStartRun}
              disabled={actionPending}
            >
              {actionPending ? 'Initializing Run…' : 'Start Demo Run'}
            </Button>
          ) : (
            <>
              <Button
                variant="destructive"
                size="md"
                onClick={handleStopRun}
                disabled={actionPending}
              >
                {actionPending ? 'Halting…' : 'Halt Demo Run'}
              </Button>

              <Button
                variant="secondary"
                size="md"
                onClick={handleSwitchScenario}
                disabled={actionPending}
              >
                {actionPending ? 'Switching…' : `Apply Scenario: ${scenario}`}
              </Button>
            </>
          )}

          {activeRun && (
            <Button
              variant="secondary"
              size="md"
              onClick={() => void checkRunStatus()}
              disabled={polling || actionPending}
            >
              <RefreshIcon size={14} className={polling ? styles.spinIcon : undefined} />
              <span>{polling ? 'Polling…' : 'Refresh Telemetry Status'}</span>
            </Button>
          )}
        </div>

        {/* Active Run Telemetry State Card */}
        {activeRun && (
          <div className={styles.runStatusBox}>
            <div className={styles.runStatusHeader}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                Active Run Status ({activeRun.runId})
              </span>
              <StatusBadge
                variant={isRunActive ? 'fresh' : 'info'}
                label={isRunActive ? 'STREAM ACTIVE' : 'STREAM HALTED'}
              />
            </div>

            <div className={styles.runStatusGrid}>
              <div className={styles.statusItem}>
                <span className={styles.statusItemLabel}>Target Patient</span>
                <span className={styles.statusItemValue}>{activeRun.patientId}</span>
              </div>

              <div className={styles.statusItem}>
                <span className={styles.statusItemLabel}>Current Scenario</span>
                <span className={styles.statusItemValue}>{activeRun.scenario}</span>
              </div>

              <div className={styles.statusItem}>
                <span className={styles.statusItemLabel}>Cadence</span>
                <span className={styles.statusItemValue}>{activeRun.intervalSeconds}s</span>
              </div>

              <div className={styles.statusItem}>
                <span className={styles.statusItemLabel}>Last Event ID</span>
                <span className={styles.statusItemValue}>
                  {activeRun.lastEventId || 'Awaiting initial frame'}
                </span>
              </div>

              <div className={styles.statusItem}>
                <span className={styles.statusItemLabel}>Last Event Time</span>
                <span className={styles.statusItemValue}>
                  {formatTimestamp(activeRun.lastEventTime)}
                </span>
              </div>

              <div className={styles.statusItem}>
                <span className={styles.statusItemLabel}>Delivery Health</span>
                <span className={styles.statusItemValue}>
                  {activeRun.failedDeliveries === 0 ? '0 Drops' : `${activeRun.failedDeliveries} Failed`}
                </span>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 3. Workstation Environment Parameters */}
      <section className={styles.card} aria-labelledby="env-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="env-heading" className={styles.cardTitle}>
              Workstation Gateway & Boundary Configuration
            </h2>
            <p className={styles.cardSubtitle}>
              Architectural endpoints, network topology, and security isolation barriers.
            </p>
          </div>
        </div>

        <div className={styles.envGrid}>
          <div className={styles.envCard}>
            <span className={styles.envCardLabel}>REST Gateway Base URL</span>
            <span className={styles.envCardValue}>{API_CONFIG.baseUrl}</span>
            <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
              FastAPI reverse proxy terminating all client HTTP requests
            </span>
          </div>

          <div className={styles.envCard}>
            <span className={styles.envCardLabel}>WebSocket Gateway URL</span>
            <span className={styles.envCardValue}>{API_CONFIG.wsUrl || 'Not configured'}</span>
            <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
              Ticket-authenticated live telemetry event push channel
            </span>
          </div>

          <div className={styles.envCard}>
            <span className={styles.envCardLabel}>Simulated Data Enforcement</span>
            <span className={styles.envCardValue}>
              {API_CONFIG.isSimulated ? 'Mandatory Banner Active' : 'Inactive'}
            </span>
            <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
              Synthetic Kaggle dataset cohort (1,500 continuous ambulatory rows)
            </span>
          </div>

          <div className={styles.envCard}>
            <span className={styles.envCardLabel}>Direct Database Access</span>
            <span className={styles.envCardValue}>Blocked at Gateway</span>
            <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
              MySQL & MongoDB Atlas credentials isolated from doctor web client
            </span>
          </div>
        </div>
      </section>

      {/* 4. Demonstration Data Management */}
      <section className={styles.card} aria-labelledby="demo-mgmt-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="demo-mgmt-heading" className={styles.cardTitle}>
              Demonstration Data Management
            </h2>
            <p className={styles.cardSubtitle}>
              Revert local in-memory modifications made during testing back to initial presentation baselines.
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={handleResetDemoData}>
            Reset Demonstration Baseline
          </Button>
        </div>
        <p style={{ margin: 0, fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
          Restores original Kaggle benchmark cohort alerts (open, acknowledged, resolved) and resets the consultation messaging log. This affects local in-memory preview state only and does not perform network operations.
        </p>
      </section>
    </div>
  );
};
