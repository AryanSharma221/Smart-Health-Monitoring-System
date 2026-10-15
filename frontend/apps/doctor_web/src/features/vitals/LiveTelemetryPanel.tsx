import React, { useState, useEffect, useCallback, useRef } from 'react';
import type {
  VitalsReading,
  AnomalyAssessment,
} from '../../types';
import {
  getPatientLatestVitals,
  getPatientVitalHistory,
  getFixturePatientHistory,
  getFixturePatientById,
  wsManager,
  fetchSimulatorStatus,
  startSimulator,
  stopSimulator,
  setSimulatorScenario,
  type ScenarioUpdateRequest,
  type SimulatorLifecycleState,
  type DashboardPatientRow,
  type WsStatusSnapshot,
} from '../../api';
import { formatVitalValue, formatTimestamp } from '../../utils';
import { VitalTimeSeriesChart } from '../../components/charts';
import { StatusBadge, Button, LoadingIndicator, InlineError, RefreshIcon } from '../../components/ui';
import styles from './LiveTelemetryPanel.module.css';

export type TelemetryTimeRange = 'live_15m' | '1h' | '24h' | 'kaggle_archive' | 'all';
export type TelemetryChartView = 'grid' | 'heart_rate' | 'spo2' | 'temperature_f';

interface LiveTelemetryPanelProps {
  patientRows: DashboardPatientRow[];
  isFixtureMode?: boolean;
  initialPatientId?: string;
  onPatientSelect?: (patientId: string) => void;
  pollIntervalSeconds?: number;
}

function resolveTimeBounds(range: TelemetryTimeRange): { from?: string; to?: string; limit: number } {
  const now = new Date();
  if (range === 'live_15m') {
    const past15m = new Date(now.getTime() - 15 * 60 * 1000);
    return { from: past15m.toISOString(), to: now.toISOString(), limit: 100 };
  }
  if (range === '1h') {
    const past1h = new Date(now.getTime() - 60 * 60 * 1000);
    return { from: past1h.toISOString(), to: now.toISOString(), limit: 150 };
  }
  if (range === '24h') {
    const past24h = new Date(now.getTime() - 24 * 3600 * 1000);
    return { from: past24h.toISOString(), to: now.toISOString(), limit: 200 };
  }
  if (range === 'kaggle_archive') {
    return { from: '2023-10-01T00:00:00Z', to: '2023-10-12T00:00:00Z', limit: 250 };
  }
  return { from: undefined, to: undefined, limit: 100 };
}

function getRangeDescription(range: TelemetryTimeRange): string {
  switch (range) {
    case 'live_15m':
      return 'Live Stream (Last 15 Minutes)';
    case '1h':
      return 'Last 1 Hour';
    case '24h':
      return 'Last 24 Hours';
    case 'kaggle_archive':
      return 'Kaggle Baseline Window (Oct 01 – Oct 12, 2023)';
    case 'all':
    default:
      return 'All Recorded History';
  }
}

export const LiveTelemetryPanel: React.FC<LiveTelemetryPanelProps> = ({
  patientRows,
  isFixtureMode = false,
  initialPatientId,
  onPatientSelect,
  pollIntervalSeconds = 5,
}) => {
  // Determine available patient IDs
  const patientIds = patientRows.map((r) => r.patient.patientId);
  const defaultPid = initialPatientId && patientIds.includes(initialPatientId)
    ? initialPatientId
    : patientIds[0] || 'P101';

  const [selectedPatientId, setSelectedPatientId] = useState<string>(defaultPid);
  const [selectedRange, setSelectedRange] = useState<TelemetryTimeRange>('live_15m');
  const [chartView, setChartView] = useState<TelemetryChartView>('grid');

  // Telemetry data states
  const [latestVitals, setLatestVitals] = useState<VitalsReading[]>([]);
  const [historyReadings, setHistoryReadings] = useState<VitalsReading[]>([]);
  const [latestAssessment, setLatestAssessment] = useState<AnomalyAssessment | null>(null);

  // Loading & error states
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);

  // WebSocket status tracking
  const [wsSnapshot, setWsSnapshot] = useState<WsStatusSnapshot>(() => wsManager.getSnapshot());

  // Simulator lifecycle state tracking
  const [simState, setSimState] = useState<SimulatorLifecycleState | 'UNKNOWN'>('UNKNOWN');
  const [simLatestGen, setSimLatestGen] = useState<string | null>(null);
  const [simTransitioning, setSimTransitioning] = useState<boolean>(false);
  const [simActionError, setSimActionError] = useState<string | null>(null);

  // Scenario presets state tracking (Part 6O)
  const [activeScenario, setActiveScenario] = useState<string>('normal');
  const [scenarioTarget, setScenarioTarget] = useState<'active' | 'cohort'>('active');
  const [scenarioApplying, setScenarioApplying] = useState<boolean>(false);
  const [scenarioFeedback, setScenarioFeedback] = useState<string | null>(null);

  // Prevent overlapping concurrent requests
  const inFlightRef = useRef<boolean>(false);
  const mountedRef = useRef<boolean>(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Determine effective patient ID (falls back cleanly if list changes)
  const effectivePatientId =
    patientIds.length > 0 && !patientIds.includes(selectedPatientId)
      ? patientIds[0]
      : selectedPatientId;

  // WebSocket status subscription
  useEffect(() => {
    const unsub = wsManager.subscribeStatus((snap) => {
      if (mountedRef.current) {
        setWsSnapshot(snap);
      }
    });
    return () => {
      unsub();
    };
  }, []);

  // Subscribe to patient's channel on the backend WebSocket
  useEffect(() => {
    if (!isFixtureMode && effectivePatientId && wsSnapshot.state === 'connected') {
      wsManager.subscribePatient(effectivePatientId);
    }
    return () => {
      if (!isFixtureMode && effectivePatientId) {
        wsManager.unsubscribePatient(effectivePatientId);
      }
    };
  }, [effectivePatientId, isFixtureMode, wsSnapshot.state]);

  // Unified telemetry fetching function (latest + historical for charts)
  const fetchTelemetry = useCallback(
    async (isManual: boolean = false, showLoading: boolean = false) => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;

      if (isManual) {
        setRefreshing(true);
      }
      if (showLoading) {
        setLoading(true);
      }

      const pid = effectivePatientId;
      const bounds = resolveTimeBounds(selectedRange);

      try {
        if (isFixtureMode) {
          const fix = getFixturePatientById(pid);
          const hrHist = getFixturePatientHistory(pid, 'heart_rate', bounds.from, bounds.to);
          const spo2Hist = getFixturePatientHistory(pid, 'spo2', bounds.from, bounds.to);
          const tempHist = getFixturePatientHistory(pid, 'temperature_f', bounds.from, bounds.to);

          if (mountedRef.current) {
            setLatestVitals(fix ? fix.latestVitals : []);
            setHistoryReadings([...hrHist, ...spo2Hist, ...tempHist]);
            setLatestAssessment(null);
            setLastRefreshedAt(new Date().toISOString());
            setError(null);
          }
          return;
        }

        // Live API concurrent query
        const [vitalsRes, historyRes] = await Promise.allSettled([
          getPatientLatestVitals(pid),
          getPatientVitalHistory(pid, {
            from: bounds.from,
            to: bounds.to,
            limit: bounds.limit,
          }),
        ]);

        if (!mountedRef.current) return;

        if (vitalsRes.status === 'fulfilled') {
          setLatestVitals(vitalsRes.value);
          setError(null);
        } else {
          setError(vitalsRes.reason?.message || 'Unable to retrieve latest patient vitals.');
        }

        if (historyRes.status === 'fulfilled') {
          setHistoryReadings(historyRes.value);
        } else {
          // Non-fatal if history query failed
          setHistoryReadings([]);
        }

        setLastRefreshedAt(new Date().toISOString());
      } catch (err: unknown) {
        if (mountedRef.current) {
          const msg = err instanceof Error ? err.message : 'Telemetry request failed.';
          setError(msg);
        }
      } finally {
        inFlightRef.current = false;
        if (mountedRef.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [effectivePatientId, selectedRange, isFixtureMode]
  );

  // Primary load effect on patient or range change
  useEffect(() => {
    void fetchTelemetry(false, true);
  }, [fetchTelemetry]);

  // Periodic bounded HTTP polling fallback (every 5 seconds)
  useEffect(() => {
    if (pollIntervalSeconds <= 0) return;

    const intervalMs = Math.max(2, pollIntervalSeconds) * 1000;
    const timer = setInterval(() => {
      void fetchTelemetry(false);
    }, intervalMs);

    return () => {
      clearInterval(timer);
    };
  }, [fetchTelemetry, pollIntervalSeconds]);

  // Real-time WebSocket event listener
  useEffect(() => {
    if (isFixtureMode) return;

    const unsub = wsManager.subscribeEvents((event) => {
      // If the incoming notification matches our active patient or cohort, refresh immediately
      const evtPatient = (event.payload as any)?.patient_id || event.payload;
      if (!evtPatient || evtPatient === selectedPatientId) {
        void fetchTelemetry(false);
      }
    });

    return () => {
      unsub();
    };
  }, [selectedPatientId, isFixtureMode, fetchTelemetry]);

  // Poll simulator status periodically
  const refreshSimulator = useCallback(async () => {
    if (isFixtureMode) return;
    try {
      const res = await fetchSimulatorStatus();
      if (mountedRef.current && res && res.simulator) {
        setSimState(res.simulator.lifecycle_state || (res.simulator.is_running ? 'RUNNING' : 'STOPPED'));
        setSimLatestGen(res.simulator.latest_generation_at || null);
        if (res.simulator.current_scenario) {
          setActiveScenario(res.simulator.current_scenario);
        }
        setSimActionError(null);
      }
    } catch {
      if (mountedRef.current) {
        setSimState('UNKNOWN');
      }
    }
  }, [isFixtureMode]);

  useEffect(() => {
    void refreshSimulator();
    if (pollIntervalSeconds <= 0 || isFixtureMode) return;
    const intervalMs = Math.max(3, pollIntervalSeconds) * 1000;
    const timer = setInterval(() => {
      void refreshSimulator();
    }, intervalMs);
    return () => clearInterval(timer);
  }, [refreshSimulator, pollIntervalSeconds, isFixtureMode]);

  const handleStartSim = async () => {
    if (simTransitioning) return;
    setSimTransitioning(true);
    setSimActionError(null);
    try {
      const res = await startSimulator();
      if (mountedRef.current) {
        setSimState(res.lifecycle_state || 'RUNNING');
        void fetchTelemetry(false);
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        setSimActionError(err instanceof Error ? err.message : 'Failed to start simulator.');
      }
    } finally {
      if (mountedRef.current) {
        setSimTransitioning(false);
      }
    }
  };

  const handleStopSim = async () => {
    if (simTransitioning) return;
    setSimTransitioning(true);
    setSimActionError(null);
    try {
      const res = await stopSimulator();
      if (mountedRef.current) {
        setSimState(res.lifecycle_state || 'STOPPED');
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        setSimActionError(err instanceof Error ? err.message : 'Failed to stop simulator.');
      }
    } finally {
      if (mountedRef.current) {
        setSimTransitioning(false);
      }
    }
  };

  const handleApplyScenario = async (scenario: ScenarioUpdateRequest['scenario']) => {
    if (scenarioApplying) return;
    setScenarioApplying(true);
    setScenarioFeedback(null);
    setSimActionError(null);

    const targetPatientId = scenarioTarget === 'active' ? effectivePatientId : null;
    const alertMetric =
      scenario === 'elevated_hr' ? 'heart_rate' : scenario === 'low_spo2' ? 'spo2' : 'all';

    try {
      const res = await setSimulatorScenario({
        scenario,
        target_patient_id: targetPatientId,
        alert_metric: alertMetric,
        reason: `Presenter applied ${scenario} demonstration scenario`,
      });
      if (mountedRef.current) {
        setActiveScenario(scenario);
        setScenarioFeedback(res.message);
        void fetchTelemetry(false);
        void refreshSimulator();
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        setSimActionError(err instanceof Error ? err.message : 'Failed to apply demo scenario.');
      }
    } finally {
      if (mountedRef.current) {
        setScenarioApplying(false);
      }
    }
  };

  // Handle patient switch
  const handleSelectPatient = (pid: string) => {
    setSelectedPatientId(pid);
    if (onPatientSelect) {
      onPatientSelect(pid);
    }
  };

  // Find latest readings by metric
  const hrReading = latestVitals.find((v) => v.metricCode === 'heart_rate');
  const spo2Reading = latestVitals.find((v) => v.metricCode === 'spo2');
  const tempReading = latestVitals.find(
    (v) => v.metricCode === 'temperature_f' || v.metricCode === 'temperature_c'
  );

  // Active patient object from props
  const activeRow = patientRows.find((r) => r.patient.patientId === selectedPatientId);
  const patientName = activeRow?.patient.name || `Patient ${selectedPatientId}`;

  // Filter readings by metric for charts
  const hrReadings = historyReadings.filter((r) => r.metricCode === 'heart_rate');
  const spo2Readings = historyReadings.filter((r) => r.metricCode === 'spo2');
  const tempReadings = historyReadings.filter(
    (r) => r.metricCode === 'temperature_f' || r.metricCode === 'temperature_c'
  );

  // Determine overall simulated provenance for display
  const isSimulated = latestVitals.some((v) => v.isSimulated);
  const provenanceLabel = isSimulated
    ? 'SIMULATED SMARTWATCH'
    : latestVitals.length > 0
    ? 'HISTORICAL KAGGLE DATASET'
    : 'NO DATA';

  // Determine stream display state
  const isWsLive = !isFixtureMode && wsSnapshot.state === 'connected';
  const isPolling = !isWsLive && !isFixtureMode && wsSnapshot.state !== 'error';

  return (
    <section className={styles.panelContainer} aria-label="Live Smartwatch Telemetry Surveillance">
      {/* 1. Panel Header */}
      <div className={styles.panelHeader}>
        <div className={styles.headerTitleCol}>
          <div className={styles.headerTitleRow}>
            <h2 className={styles.title}>Live Smartwatch Telemetry Surveillance</h2>
            {isSimulated && (
              <span className={styles.simulatedBadge} title="Generated synthetic data for clinical simulation. Not for diagnostic use.">
                SIMULATED DEMO DATA
              </span>
            )}
          </div>
          <p className={styles.subtitle}>
            Real-time physiologic telemetry streamed from wearable simulator to FastAPI gateway and persistent MySQL store.
          </p>
        </div>

        {/* Real-Time Connection & Refresh Controls */}
        <div className={styles.headerActions}>
          <div className={styles.streamStatusBadge}>
            <span
              className={`${styles.statusDot} ${
                isWsLive
                  ? styles.dotConnected
                  : isPolling
                  ? styles.dotPolling
                  : wsSnapshot.state === 'error'
                  ? styles.dotError
                  : styles.dotDisconnected
              }`}
              aria-hidden="true"
            />
            <span>
              {isFixtureMode
                ? 'Development Fixture Feed'
                : isWsLive
                ? 'WebSocket: Live Stream'
                : isPolling
                ? `HTTP Polling (${pollIntervalSeconds}s)`
                : 'Stream Disconnected'}
            </span>
          </div>

          <div className={styles.refreshMeta}>
            <span className={styles.lastUpdateLabel}>Last Updated</span>
            <span className={styles.lastUpdateValue}>
              {lastRefreshedAt ? formatTimestamp(lastRefreshedAt) : 'Never'}
            </span>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => void fetchTelemetry(true)}
            disabled={loading || refreshing}
            aria-label="Refresh telemetry stream"
          >
            <RefreshIcon size={14} className={refreshing ? styles.spinIcon : undefined} />
            <span>{refreshing ? 'Polling…' : 'Refresh'}</span>
          </Button>
        </div>
      </div>

      {/* Error banner if telemetry failed */}
      {error && !isFixtureMode && (
        <InlineError
          title="Telemetry Stream Notice"
          message={error}
          onRetry={() => void fetchTelemetry(true)}
        />
      )}

      {/* Simulator Lifecycle Control Bar */}
      {!isFixtureMode && (
        <div className={styles.simulatorControlBar}>
          <div className={styles.simulatorInfo}>
            <span className={styles.simulatorLabel}>Simulator Engine:</span>
            <StatusBadge
              variant={
                simState === 'RUNNING'
                  ? 'fresh'
                  : simState === 'STOPPED' || simState === 'STOPPING'
                  ? 'advisory'
                  : 'unavailable'
              }
              label={
                simState === 'RUNNING'
                  ? 'GENERATING TELEMETRY'
                  : simState === 'STOPPED'
                  ? 'PAUSED / STOPPED'
                  : simState === 'STOPPING'
                  ? 'STOPPING...'
                  : simState === 'UNKNOWN'
                  ? 'NOT REACHABLE'
                  : simState
              }
            />
            {simLatestGen && (
              <span className={styles.simulatorTimestamp}>
                Last Generated: {formatTimestamp(simLatestGen)}
              </span>
            )}
            <span className={styles.simulatorHint}>
              (Controls wearable sensor feed only; backend &amp; clinical DB remain active)
            </span>
          </div>

          <div className={styles.simulatorActions}>
            {simState === 'RUNNING' ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void handleStopSim()}
                disabled={simTransitioning}
                aria-label="Pause simulated telemetry generation"
              >
                {simTransitioning ? 'Pausing…' : 'Pause Simulator'}
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                onClick={() => void handleStartSim()}
                disabled={simTransitioning}
                aria-label="Resume simulated telemetry generation"
              >
                {simTransitioning ? 'Resuming…' : 'Resume Simulator'}
              </Button>
            )}
          </div>

          {simActionError && (
            <div className={styles.controlError}>
              Warning: {simActionError}
            </div>
          )}
        </div>
      )}

      {/* Demonstration Scenario Presets (Part 6O) */}
      {!isFixtureMode && (
        <div className={styles.scenarioPresetsBar}>
          <div className={styles.scenarioHeaderRow}>
            <div className={styles.scenarioTitleGroup}>
              <span className={styles.scenarioSectionTitle}>Demo Scenarios</span>
              <span className={styles.scenarioDisclaimerPill}>Synthetic Scenario — Not Medical Advice</span>
            </div>
            <div className={styles.activeScenarioBadge}>
              Active Mode: <strong>{activeScenario.toUpperCase()}</strong>
            </div>
          </div>

          <div className={styles.scenarioControlsRow}>
            <div className={styles.scenarioTargetGroup}>
              <span className={styles.scenarioTargetLabel}>Target:</span>
              <div className={styles.targetButtonGroup}>
                <button
                  type="button"
                  className={`${styles.targetBtn} ${scenarioTarget === 'active' ? styles.targetBtnActive : ''}`}
                  onClick={() => setScenarioTarget('active')}
                >
                  Selected ({selectedPatientId})
                </button>
                <button
                  type="button"
                  className={`${styles.targetBtn} ${scenarioTarget === 'cohort' ? styles.targetBtnActive : ''}`}
                  onClick={() => setScenarioTarget('cohort')}
                >
                  All Cohort (P101–P105)
                </button>
              </div>
            </div>

            <div className={styles.presetButtonsRow}>
              <button
                type="button"
                className={`${styles.presetBtn} ${styles.btnNormal} ${activeScenario === 'normal' || activeScenario === 'resting' ? styles.btnPresetActive : ''}`}
                onClick={() => void handleApplyScenario('normal')}
                disabled={scenarioApplying}
                title="Scenario A: Stable physiological baseline drift (0 threshold alerts)"
              >
                A: Normal Baseline
              </button>
              <button
                type="button"
                className={`${styles.presetBtn} ${styles.btnElevatedHr} ${activeScenario === 'elevated_hr' ? styles.btnPresetActive : ''}`}
                onClick={() => void handleApplyScenario('elevated_hr')}
                disabled={scenarioApplying}
                title="Scenario B: Controlled tachycardia (HR > 130 bpm -> CRITICAL alert)"
              >
                B: Elevated HR (&gt;130 bpm)
              </button>
              <button
                type="button"
                className={`${styles.presetBtn} ${styles.btnLowSpo2} ${activeScenario === 'low_spo2' ? styles.btnPresetActive : ''}`}
                onClick={() => void handleApplyScenario('low_spo2')}
                disabled={scenarioApplying}
                title="Scenario C: Controlled hypoxemia (SpO2 < 85% -> CRITICAL alert)"
              >
                C: Low SpO₂ (&lt;85%)
              </button>
              <button
                type="button"
                className={`${styles.presetBtn} ${styles.btnRecovery} ${activeScenario === 'recovering' ? styles.btnPresetActive : ''}`}
                onClick={() => void handleApplyScenario('recovering')}
                disabled={scenarioApplying}
                title="Scenario D: Exponential decay back toward resting baseline (preserves existing alerts)"
              >
                D: Baseline Recovery
              </button>
            </div>
          </div>

          {scenarioFeedback && (
            <div className={styles.scenarioFeedbackMessage}>
              ✓ {scenarioFeedback}
            </div>
          )}
        </div>
      )}

      {/* 2. Patient Selector Bar */}
      <div className={styles.patientSelectBar}>
        <div className={styles.patientSelectorGroup}>
          <span className={styles.selectorLabel}>Select Patient Cohort:</span>
          <div className={styles.patientChips}>
            {patientIds.map((pid) => {
              const row = patientRows.find((r) => r.patient.patientId === pid);
              const isSelected = pid === selectedPatientId;
              return (
                <button
                  key={pid}
                  type="button"
                  className={`${styles.patientChip} ${isSelected ? styles.patientChipActive : ''}`}
                  onClick={() => handleSelectPatient(pid)}
                  aria-pressed={isSelected}
                  title={`View telemetry for ${row?.patient.name || pid}`}
                >
                  {pid} {row?.patient.name ? `(${row.patient.name.split(' ')[0]})` : ''}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
          Active Target: <strong>{patientName}</strong> ({selectedPatientId})
        </div>
      </div>

      {/* 3. Latest Telemetry Cards */}
      <div className={styles.vitalsCardsGrid}>
        {/* Heart Rate Card */}
        <div className={styles.vitalCard}>
          <div className={styles.cardHeader}>
            <span className={styles.vitalLabel}>Heart Rate</span>
            <span
              className={`${styles.vitalProvenance} ${
                hrReading?.isSimulated ? styles.provenanceSimulated : styles.provenanceHistorical
              }`}
            >
              {hrReading?.isSimulated ? 'Simulated' : 'Historical'}
            </span>
          </div>
          <div className={styles.vitalValueRow}>
            <span className={styles.vitalValue}>
              {formatVitalValue(hrReading?.value, hrReading?.unit || 'bpm', 0)}
            </span>
            <span className={styles.vitalUnit}>{hrReading?.unit || 'bpm'}</span>
          </div>
          <div className={styles.cardMeta}>
            <span className={styles.baselineRange}>Baseline: 60–100 bpm</span>
            {hrReading && <StatusBadge variant={hrReading.freshness} />}
          </div>
        </div>

        {/* SpO2 Card */}
        <div className={styles.vitalCard}>
          <div className={styles.cardHeader}>
            <span className={styles.vitalLabel}>Oxygen Saturation</span>
            <span
              className={`${styles.vitalProvenance} ${
                spo2Reading?.isSimulated ? styles.provenanceSimulated : styles.provenanceHistorical
              }`}
            >
              {spo2Reading?.isSimulated ? 'Simulated' : 'Historical'}
            </span>
          </div>
          <div className={styles.vitalValueRow}>
            <span className={styles.vitalValue}>
              {formatVitalValue(spo2Reading?.value, spo2Reading?.unit || '%', 1)}
            </span>
            <span className={styles.vitalUnit}>{spo2Reading?.unit || '%'}</span>
          </div>
          <div className={styles.cardMeta}>
            <span className={styles.baselineRange}>Baseline: 95–100 %</span>
            {spo2Reading && <StatusBadge variant={spo2Reading.freshness} />}
          </div>
        </div>

        {/* Temperature Card */}
        <div className={styles.vitalCard}>
          <div className={styles.cardHeader}>
            <span className={styles.vitalLabel}>Body Temperature</span>
            <span
              className={`${styles.vitalProvenance} ${
                tempReading?.isSimulated ? styles.provenanceSimulated : styles.provenanceHistorical
              }`}
            >
              {tempReading?.isSimulated ? 'Simulated' : 'Historical'}
            </span>
          </div>
          <div className={styles.vitalValueRow}>
            <span className={styles.vitalValue}>
              {formatVitalValue(tempReading?.value, tempReading?.unit || '°F', 1)}
            </span>
            <span className={styles.vitalUnit}>{tempReading?.unit || '°F'}</span>
          </div>
          <div className={styles.cardMeta}>
            <span className={styles.baselineRange}>Baseline: 97.5–99.0 °F</span>
            {tempReading && <StatusBadge variant={tempReading.freshness} />}
          </div>
        </div>

        {/* Provenance & Surveillance Summary Card */}
        <div className={styles.vitalCard} style={{ backgroundColor: 'var(--color-bg-surface-subtle)' }}>
          <div className={styles.cardHeader}>
            <span className={styles.vitalLabel}>Data Provenance</span>
            <span className={styles.vitalProvenance} style={{ backgroundColor: '#e2e8f0', color: '#334155' }}>
              Authoritative
            </span>
          </div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            {provenanceLabel}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
            {latestVitals[0]?.measuredAt
              ? `Observed: ${formatTimestamp(latestVitals[0].measuredAt)}`
              : 'Awaiting initial telemetry'}
          </div>
          <div className={styles.cardMeta}>
            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>
              Source: {latestVitals[0]?.source || 'smartwatch_simulator'}
            </span>
          </div>
        </div>
      </div>

      {/* ML Anomaly Assessment Banner if present */}
      {latestAssessment && (
        <div
          className={`${styles.mlAssessmentBanner} ${
            latestAssessment.result === 'anomalous' ? styles.mlAnomaly : styles.mlNormal
          }`}
        >
          <div>
            <strong>Isolation Forest ML Assessment: </strong>
            <span>
              Result: {latestAssessment.result.toUpperCase()} (Anomaly Score: {latestAssessment.anomalyScore.toFixed(3)})
            </span>
          </div>
          <div style={{ fontSize: '11px' }}>
            Model v{latestAssessment.modelVersion} · Synthetic Evaluation
          </div>
        </div>
      )}

      {/* 4. Chart Filter & View Controls */}
      <div className={styles.chartControlsRow}>
        {/* Time Window Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text-secondary)' }}>
            Time Window:
          </span>
          <div className={styles.buttonGroup}>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${selectedRange === 'live_15m' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setSelectedRange('live_15m')}
            >
              Live (15m)
            </button>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${selectedRange === '1h' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setSelectedRange('1h')}
            >
              1 Hour
            </button>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${selectedRange === '24h' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setSelectedRange('24h')}
            >
              24 Hours
            </button>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${selectedRange === 'kaggle_archive' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setSelectedRange('kaggle_archive')}
            >
              Kaggle Archive
            </button>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${selectedRange === 'all' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setSelectedRange('all')}
            >
              All Recorded
            </button>
          </div>
        </div>

        {/* View Switcher */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text-secondary)' }}>
            View:
          </span>
          <div className={styles.buttonGroup}>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${chartView === 'grid' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setChartView('grid')}
            >
              Tri-Vital Grid
            </button>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${chartView === 'heart_rate' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setChartView('heart_rate')}
            >
              Heart Rate
            </button>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${chartView === 'spo2' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setChartView('spo2')}
            >
              SpO2
            </button>
            <button
              type="button"
              className={`${styles.segmentedBtn} ${chartView === 'temperature_f' ? styles.segmentedBtnActive : ''}`}
              onClick={() => setChartView('temperature_f')}
            >
              Temperature
            </button>
          </div>
        </div>
      </div>

      {/* 5. Render Charts with Strict Scale Separation */}
      {loading ? (
        <div style={{ padding: '36px 0', textAlign: 'center' }}>
          <LoadingIndicator label={`Querying ${patientName} telemetry stream…`} />
        </div>
      ) : (
        <div className={styles.chartsGrid}>
          {/* Heart Rate Chart */}
          {(chartView === 'grid' || chartView === 'heart_rate') && (
            <div className={styles.chartCard}>
              <VitalTimeSeriesChart
                readings={hrReadings}
                metricCode="heart_rate"
                metricLabel="Heart Rate"
                metricUnit="bpm"
                timeRangeDescription={getRangeDescription(selectedRange)}
                isLoading={false}
              />
            </div>
          )}

          {/* SpO2 Chart */}
          {(chartView === 'grid' || chartView === 'spo2') && (
            <div className={styles.chartCard}>
              <VitalTimeSeriesChart
                readings={spo2Readings}
                metricCode="spo2"
                metricLabel="Oxygen Saturation (SpO2)"
                metricUnit="%"
                timeRangeDescription={getRangeDescription(selectedRange)}
                isLoading={false}
              />
            </div>
          )}

          {/* Body Temperature Chart */}
          {(chartView === 'grid' || chartView === 'temperature_f') && (
            <div className={styles.chartCard}>
              <VitalTimeSeriesChart
                readings={tempReadings}
                metricCode="temperature_f"
                metricLabel="Body Temperature"
                metricUnit="°F"
                timeRangeDescription={getRangeDescription(selectedRange)}
                isLoading={false}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
};
