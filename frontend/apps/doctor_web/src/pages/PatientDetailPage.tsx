import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getPatientById,
  getPatientLatestVitals,
  getPatientAlerts,
  getPatientVitalHistory,
  getFixturePatientById,
  getFixturePatientHistory,
  deriveFeedFreshness,
  resolveLatestMeasurementTime,
  wsManager,
} from '../api';
import type {
  PatientProfile,
  VitalsReading,
  PatientAlert,
  MetricCode,
} from '../types';
import { formatVitalValue, formatTimestamp } from '../utils';
import { useDevMode } from '../hooks';
import {
  SimulatedDataBanner,
  StatusBadge,
  Button,
  LoadingIndicator,
  InlineError,
  EmptyState,
  RefreshIcon,
} from '../components/ui';
import { VitalTimeSeriesChart } from '../components/charts';
import styles from './PatientDetailPage.module.css';

type TimeRangeFilter = 'live_15m' | '1h' | '24h' | '7d' | 'kaggle_archive' | 'all';

const SUPPORTED_METRICS: { code: MetricCode; label: string; unit: string }[] = [
  { code: 'heart_rate', label: 'Heart Rate', unit: 'bpm' },
  { code: 'spo2', label: 'Oxygen Saturation (SpO2)', unit: '%' },
  { code: 'temperature_f', label: 'Body Temperature', unit: '°F' },
];

function getTimeRangeDescription(range: TimeRangeFilter): string {
  switch (range) {
    case 'live_15m':
      return 'Live Stream (Last 15 Minutes)';
    case '1h':
      return 'Last 1 Hour';
    case '24h':
      return 'Last 24 Hours';
    case '7d':
      return 'Last 7 Days';
    case 'kaggle_archive':
      return 'Kaggle Baseline Window (Oct 01 – Oct 12, 2023)';
    case 'all':
    default:
      return 'All Recorded History (Full Archive)';
  }
}

function getTimeRangeBounds(range: TimeRangeFilter): { from?: string; to?: string; limit: number } {
  const now = new Date();
  if (range === 'live_15m') {
    const past15m = new Date(now.getTime() - 15 * 60 * 1000);
    return { from: past15m.toISOString(), to: now.toISOString(), limit: 100 };
  }
  if (range === '1h') {
    const past1h = new Date(now.getTime() - 3600 * 1000);
    return { from: past1h.toISOString(), to: now.toISOString(), limit: 150 };
  }
  if (range === '24h') {
    const past24h = new Date(now.getTime() - 24 * 3600 * 1000);
    return { from: past24h.toISOString(), to: now.toISOString(), limit: 200 };
  }
  if (range === '7d') {
    const past7d = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
    return { from: past7d.toISOString(), to: now.toISOString(), limit: 300 };
  }
  if (range === 'kaggle_archive') {
    return {
      from: '2023-10-01T00:00:00Z',
      to: '2023-10-12T00:00:00Z',
      limit: 250,
    };
  }
  return { from: undefined, to: undefined, limit: 100 };
}

export const PatientDetailPage: React.FC = () => {
  const { patientId } = useParams<{ patientId: string }>();

  // Patient Profile & Vitals State
  const [patientLoading, setPatientLoading] = useState<boolean>(true);
  const [patientError, setPatientError] = useState<string | null>(null);
  const [patient, setPatient] = useState<PatientProfile | null>(null);
  const [latestVitals, setLatestVitals] = useState<VitalsReading[]>([]);
  const [vitalsError, setVitalsError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<PatientAlert[]>([]);
  const [alertsError, setAlertsError] = useState<string | null>(null);

  // History Analysis State
  const [selectedMetric, setSelectedMetric] = useState<MetricCode>('heart_rate');
  const [selectedRange, setSelectedRange] = useState<TimeRangeFilter>('all');
  const [historyReadings, setHistoryReadings] = useState<VitalsReading[]>([]);
  const [historyLoading, setHistoryLoading] = useState<boolean>(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Development Fixture & Refresh State
  const { isFixtureMode, toggleFixtureMode } = useDevMode();
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  // Load Patient Profile, Latest Vitals, and Alerts
  const loadPatientOverview = useCallback(
    async (pid: string, useFixtures: boolean) => {
      setPatientError(null);
      setVitalsError(null);
      setAlertsError(null);

      // Query live API concurrently (works in both Live Mode and Demo Mode)
      try {
        const patientData = await getPatientById(pid);
        setPatient(patientData);

        // Concurrently query latest vitals and alerts
        const [vitalsRes, alertsRes] = await Promise.allSettled([
          getPatientLatestVitals(pid),
          getPatientAlerts(pid),
        ]);

        if (vitalsRes.status === 'fulfilled') {
          setLatestVitals(vitalsRes.value);
        } else {
          setVitalsError(vitalsRes.reason?.message || 'Unable to retrieve latest vitals.');
          setLatestVitals([]);
        }

        if (alertsRes.status === 'fulfilled') {
          setAlerts(alertsRes.value);
        } else {
          setAlertsError(alertsRes.reason?.message || 'Unable to retrieve active alerts.');
          setAlerts([]);
        }

        setLastRefreshed(new Date().toISOString());
        return;
      } catch (err: unknown) {
        if (useFixtures) {
          const fix = getFixturePatientById(pid);
          if (fix) {
            setPatient(fix.patient);
            setLatestVitals(fix.latestVitals);
            setAlerts(fix.alerts);
            setLastRefreshed(new Date().toISOString());
            return;
          }
          setPatient(null);
          setPatientError(`Patient with ID "${pid}" does not exist in development fixtures.`);
          return;
        }

        const msg = err instanceof Error ? err.message : 'Unable to query patient profile.';
        setPatient(null);
        setPatientError(msg);
      }
    },
    []
  );

  // Load Historical Vitals for Selected Metric and Time Range
  const loadHistoryData = useCallback(
    async (pid: string, metric: MetricCode, range: TimeRangeFilter, useFixtures: boolean) => {
      setHistoryLoading(true);
      setHistoryError(null);
      const bounds = getTimeRangeBounds(range);

      try {
        const hist = await getPatientVitalHistory(pid, {
          metricCode: metric,
          from: bounds.from,
          to: bounds.to,
          limit: bounds.limit,
        });
        setHistoryReadings(hist);
      } catch (err: unknown) {
        if (useFixtures) {
          const hist = getFixturePatientHistory(pid, metric as any, bounds.from, bounds.to);
          setHistoryReadings(hist);
          return;
        }
        const msg = err instanceof Error ? err.message : 'Failed to retrieve vital-sign history.';
        setHistoryError(msg);
        setHistoryReadings([]);
      } finally {
        setHistoryLoading(false);
      }
    },
    []
  );

  // Subscribe to patient's channel on backend WebSocket
  useEffect(() => {
    if (!isFixtureMode && patientId) {
      wsManager.subscribePatient(patientId);
    }
    return () => {
      if (!isFixtureMode && patientId) {
        wsManager.unsubscribePatient(patientId);
      }
    };
  }, [patientId, isFixtureMode]);

  // Real-time WebSocket event listener + 5s polling fallback for active streams
  useEffect(() => {
    if (!patientId) return;

    const unsub = !isFixtureMode ? wsManager.subscribeEvents((event) => {
      const evtPatient = (event.payload as any)?.patient_id || event.payload;
      if (!evtPatient || evtPatient === patientId) {
        void loadPatientOverview(patientId, isFixtureMode);
        void loadHistoryData(patientId, selectedMetric, selectedRange, isFixtureMode);
      }
    }) : () => {};

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    if (selectedRange === 'live_15m' || selectedRange === '1h' || selectedRange === '24h' || isFixtureMode) {
      pollTimer = setInterval(() => {
        void loadPatientOverview(patientId, isFixtureMode);
        void loadHistoryData(patientId, selectedMetric, selectedRange, isFixtureMode);
      }, 5000);
    }

    return () => {
      unsub();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [patientId, isFixtureMode, selectedMetric, selectedRange, loadPatientOverview, loadHistoryData]);

  // Primary Effect on patientId or fixtureMode change
  useEffect(() => {
    if (!patientId) return;

    let isCancelled = false;

    async function init() {
      await loadPatientOverview(patientId!, isFixtureMode);
      if (!isCancelled) {
        setPatientLoading(false);
      }
    }

    void init();

    return () => {
      isCancelled = true;
    };
  }, [patientId, isFixtureMode, loadPatientOverview]);

  // Secondary Effect for History Query on Metric or Range change
  useEffect(() => {
    if (!patientId || !patient) return;

    let isCancelled = false;

    async function fetchHistory() {
      if (!isCancelled) {
        await loadHistoryData(patientId!, selectedMetric, selectedRange, isFixtureMode);
      }
    }

    fetchHistory();

    return () => {
      isCancelled = true;
    };
  }, [patientId, patient, selectedMetric, selectedRange, isFixtureMode, loadHistoryData]);

  const handleManualRefresh = async () => {
    if (!patientId) return;
    setRefreshing(true);
    await Promise.all([
      loadPatientOverview(patientId, isFixtureMode),
      loadHistoryData(patientId, selectedMetric, selectedRange, isFixtureMode),
    ]);
    setRefreshing(false);
  };

  const handleToggleFixtureMode = () => {
    toggleFixtureMode();
    setPatientLoading(true);
    setPatientError(null);
  };

  // Derive Patient Metadata
  const feedFreshness = useMemo(() => {
    return deriveFeedFreshness(latestVitals, vitalsError || undefined);
  }, [latestVitals, vitalsError]);

  const mostRecentMeasurementTime = useMemo(() => {
    return resolveLatestMeasurementTime(latestVitals);
  }, [latestVitals]);

  const currentMetricDef = useMemo(() => {
    return (
      SUPPORTED_METRICS.find((m) => m.code === selectedMetric) || {
        code: selectedMetric,
        label: selectedMetric,
        unit: '',
      }
    );
  }, [selectedMetric]);

  const hrVital = latestVitals.find((v) => v.metricCode === 'heart_rate');
  const spo2Vital = latestVitals.find((v) => v.metricCode === 'spo2');
  const tempVital = latestVitals.find(
    (v) => v.metricCode === 'temperature_f' || v.metricCode === 'temperature_c'
  );

  return (
    <div className={styles.container}>
      {/* 1. Persistent Safety Warning */}
      <SimulatedDataBanner detail="Authorization boundary: Connects exclusively to central FastAPI gateway." />

      {/* Fixture Mode Alert if active */}
      {isFixtureMode && (
        <div className={styles.fixtureNotice} role="alert">
          <div className={styles.fixtureText}>
            <span className={styles.fixtureTag}>Dev Fixture</span>
            <span>
              <strong>Development Fixture Mode Active:</strong> Viewing isolated Kaggle P101–P105 demonstration records. Live FastAPI backend at localhost:8000 is currently offline.
            </span>
          </div>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Switch to Live Gateway Mode
          </Button>
        </div>
      )}

      {/* Back Link to Patient Directory */}
      <div className={styles.backLinkRow}>
        <Link to="/patients" className={styles.backLink}>
          &larr; Back to Patient Directory
        </Link>
      </div>

      {/* 2. Page Header & Actions */}
      <header className={styles.headerSection}>
        <div className={styles.headerTopRow}>
          <div className={styles.headerTitleCol}>
            <h1 className={styles.title}>
              {patient ? patient.name : `Patient: ${patientId || 'Unknown'}`}
            </h1>
            <p className={styles.subtitle}>
              Continuous vital sign trajectory, freshness evaluation, and historical analysis.
            </p>
          </div>

          <div className={styles.headerActions}>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleManualRefresh}
              disabled={patientLoading || refreshing}
              aria-label="Refresh patient data"
            >
              <RefreshIcon size={14} className={refreshing ? styles.spinIcon : undefined} />
              <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Error Banner when live API fails */}
      {patientError && !isFixtureMode && (
        <InlineError
          title="Patient Profile Communication Failure"
          message={patientError}
          onRetry={() => {
            setPatientLoading(true);
            loadPatientOverview(patientId!, false).then(() => setPatientLoading(false));
          }}
        />
      )}

      {/* Development Fixture Affordance when offline */}
      {patientError && !isFixtureMode && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: 'var(--color-bg-surface)',
            border: '1px dashed var(--color-border-base)',
            borderRadius: 'var(--radius-xs)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '12px',
            color: 'var(--color-text-secondary)',
          }}
        >
          <span>
            FastAPI service is offline. Would you like to inspect patient {patientId} using isolated Kaggle P101–P105 development fixtures?
          </span>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Inspect with Development Fixtures
          </Button>
        </div>
      )}

      {patientLoading ? (
        <div style={{ padding: '48px 0', textAlign: 'center' }}>
          <LoadingIndicator label={`Querying telemetry records for patient ${patientId}…`} />
        </div>
      ) : !patient ? (
        <EmptyState
          preset="custom"
          title="Patient Not Found"
          description={
            patientError ||
            `No patient record matching ID "${patientId}" was found in ${
              isFixtureMode ? 'the demonstration cohort (available patients: P101, P102, P103, P104, P105)' : 'the authorized clinical database'
            }.`
          }
          actionLabel="Return to Patient Directory"
          onAction={() => window.history.back()}
        />
      ) : (
        <>
          {/* 3. Patient Identity & Overview Card */}
          {patient && (
            <section className={styles.profileCard} aria-label="Patient Profile and Assignment">
              <div className={styles.profileTopRow}>
                <div className={styles.profileIdentityCol}>
                  <h2 className={styles.patientFullName}>{patient.name}</h2>
                  <div className={styles.patientMetaRow}>
                    <span>
                      Patient ID: <span className={styles.monoTag}>{patient.patientId}</span>
                    </span>
                    {patient.sourcePatientId && (
                      <span>
                        Source Cohort: <span className={styles.monoTag}>{patient.sourcePatientId}</span>
                      </span>
                    )}
                    <span>
                      Last Measured:{' '}
                      <span className={styles.monoTag}>
                        {mostRecentMeasurementTime
                          ? formatTimestamp(mostRecentMeasurementTime)
                          : '— (Unavailable)'}
                      </span>
                    </span>
                  </div>
                </div>

                <div className={styles.profileStatusArea}>
                  <StatusBadge variant={feedFreshness} />
                </div>
              </div>

              {/* Supported Demographic & Assignment Data */}
              <div className={styles.demographicsGrid}>
                <div className={styles.demographicItem}>
                  <span className={styles.demographicLabel}>Assigned Doctor</span>
                  <span className={styles.demographicValue}>
                    {patient.assignedDoctorId || 'Assigned in MySQL'}
                  </span>
                </div>

                <div className={styles.demographicItem}>
                  <span className={styles.demographicLabel}>Gender</span>
                  <span className={styles.demographicValue}>{patient.gender || '—'}</span>
                </div>

                <div className={styles.demographicItem}>
                  <span className={styles.demographicLabel}>Date of Birth</span>
                  <span className={styles.demographicValue}>{patient.dateOfBirth || '—'}</span>
                </div>

                <div className={styles.demographicItem}>
                  <span className={styles.demographicLabel}>Height</span>
                  <span className={styles.demographicValue}>
                    {patient.heightCm ? `${patient.heightCm} cm` : '—'}
                  </span>
                </div>

                <div className={styles.demographicItem}>
                  <span className={styles.demographicLabel}>Weight</span>
                  <span className={styles.demographicValue}>
                    {patient.weightKg ? `${patient.weightKg} kg` : '—'}
                  </span>
                </div>
              </div>
            </section>
          )}

          {/* 4. Current Vital Signs Strip */}
          <section className={styles.vitalsGrid} aria-label="Latest Vital Signs">
            {/* Heart Rate */}
            <div className={styles.vitalCard}>
              <div className={styles.vitalCardHeader}>
                <span className={styles.vitalMetricLabel}>Heart Rate</span>
                {hrVital ? (
                  <StatusBadge variant={hrVital.freshness} />
                ) : (
                  <StatusBadge variant="unavailable" />
                )}
              </div>
              <div className={styles.vitalValueRow}>
                <span
                  className={
                    hrVital && hrVital.value !== null
                      ? styles.vitalValue
                      : `${styles.vitalValue} ${styles.vitalValueUnavailable}`
                  }
                >
                  {formatVitalValue(hrVital?.value, undefined, 0)}
                </span>
                <span className={styles.vitalUnit}>bpm</span>
              </div>
              <div className={styles.vitalMetaFooter}>
                <span>
                  Measured:{' '}
                  {hrVital?.measuredAt ? formatTimestamp(hrVital.measuredAt) : '— (No reading)'}
                </span>
                <span>
                  Provenance:{' '}
                  {hrVital?.source === 'self_added' ? (
                    <strong style={{ color: '#0369a1' }}>Self-Added (Demo SQL Workbench)</strong>
                  ) : hrVital?.isSimulated || hrVital?.source === 'smartwatch_simulator' ? (
                    <strong style={{ color: '#d97706' }}>Simulated Smartwatch (Synthetic)</strong>
                  ) : hrVital?.source === 'kaggle_csv' ? (
                    'Kaggle Historical Archive'
                  ) : (
                    hrVital?.source || 'Simulator'
                  )}
                </span>
              </div>
            </div>

            {/* SpO2 Oxygen */}
            <div className={styles.vitalCard}>
              <div className={styles.vitalCardHeader}>
                <span className={styles.vitalMetricLabel}>SpO2 Saturation</span>
                {spo2Vital ? (
                  <StatusBadge variant={spo2Vital.freshness} />
                ) : (
                  <StatusBadge variant="unavailable" />
                )}
              </div>
              <div className={styles.vitalValueRow}>
                <span
                  className={
                    spo2Vital && spo2Vital.value !== null
                      ? styles.vitalValue
                      : `${styles.vitalValue} ${styles.vitalValueUnavailable}`
                  }
                >
                  {formatVitalValue(spo2Vital?.value, undefined, 1)}
                </span>
                <span className={styles.vitalUnit}>%</span>
              </div>
              <div className={styles.vitalMetaFooter}>
                <span>
                  Measured:{' '}
                  {spo2Vital?.measuredAt ? formatTimestamp(spo2Vital.measuredAt) : '— (No reading)'}
                </span>
                <span>
                  Provenance:{' '}
                  {spo2Vital?.source === 'self_added' ? (
                    <strong style={{ color: '#0369a1' }}>Self-Added (Demo SQL Workbench)</strong>
                  ) : spo2Vital?.isSimulated || spo2Vital?.source === 'smartwatch_simulator' ? (
                    <strong style={{ color: '#d97706' }}>Simulated Smartwatch (Synthetic)</strong>
                  ) : spo2Vital?.source === 'kaggle_csv' ? (
                    'Kaggle Historical Archive'
                  ) : (
                    spo2Vital?.source || 'Simulator'
                  )}
                </span>
              </div>
            </div>

            {/* Temperature */}
            <div className={styles.vitalCard}>
              <div className={styles.vitalCardHeader}>
                <span className={styles.vitalMetricLabel}>Body Temperature</span>
                {tempVital ? (
                  <StatusBadge variant={tempVital.freshness} />
                ) : (
                  <StatusBadge variant="unavailable" />
                )}
              </div>
              <div className={styles.vitalValueRow}>
                <span
                  className={
                    tempVital && tempVital.value !== null
                      ? styles.vitalValue
                      : `${styles.vitalValue} ${styles.vitalValueUnavailable}`
                  }
                >
                  {formatVitalValue(tempVital?.value, undefined, 1)}
                </span>
                <span className={styles.vitalUnit}>{tempVital?.unit || '°F'}</span>
              </div>
              <div className={styles.vitalMetaFooter}>
                <span>
                  Measured:{' '}
                  {tempVital?.measuredAt ? formatTimestamp(tempVital.measuredAt) : '— (No reading)'}
                </span>
                <span>
                  Provenance:{' '}
                  {tempVital?.source === 'self_added' ? (
                    <strong style={{ color: '#0369a1' }}>Self-Added (Demo SQL Workbench)</strong>
                  ) : tempVital?.isSimulated || tempVital?.source === 'smartwatch_simulator' ? (
                    <strong style={{ color: '#d97706' }}>Simulated Smartwatch (Synthetic)</strong>
                  ) : tempVital?.source === 'kaggle_csv' ? (
                    'Kaggle Historical Archive'
                  ) : (
                    tempVital?.source || 'Simulator'
                  )}
                </span>
              </div>
            </div>

            {/* Respiratory Rate & Blood Pressure (Optional live simulator metrics) */}
            <div className={styles.vitalCard}>
              <div className={styles.vitalCardHeader}>
                <span className={styles.vitalMetricLabel}>Resp. Rate &amp; BP</span>
                <StatusBadge variant="unavailable" label="Not in Kaggle CSV" />
              </div>
              <div className={styles.vitalValueRow}>
                <span className={`${styles.vitalValue} ${styles.vitalValueUnavailable}`}>—</span>
              </div>
              <div className={styles.vitalMetaFooter}>
                <span>Optional Live Simulator Telemetry</span>
                <span>Historical records contain HR, SpO2, and Temp only.</span>
              </div>
            </div>
          </section>

          {/* 5. Vital-Sign History Section with SVG Chart */}
          <section className={styles.historySectionCard} aria-label="Vital-Sign Historical Trajectory">
            <div className={styles.historyHeaderRow}>
              <div className={styles.historyTitleCol}>
                <h2 className={styles.historyHeading}>Vital-Sign History &amp; Trajectory</h2>
                <p className={styles.historySubheading}>
                  Plot actual historical measurements retrieved from the FastAPI telemetry store.
                </p>
              </div>

              {lastRefreshed && (
                <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                  Refreshed: {formatTimestamp(lastRefreshed)}
                </span>
              )}
            </div>

            {/* Metric & Time Range Selectors Toolbar */}
            <div className={styles.historyToolbar}>
              <div className={styles.selectorGroup}>
                <label htmlFor="metric-selector" className={styles.selectorLabel}>
                  Parameter:
                </label>
                <select
                  id="metric-selector"
                  className={styles.selectInput}
                  value={selectedMetric}
                  onChange={(e) => setSelectedMetric(e.target.value as MetricCode)}
                  aria-label="Select physiological parameter"
                >
                  {SUPPORTED_METRICS.map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.label} ({m.unit})
                    </option>
                  ))}
                </select>
              </div>

              <div className={styles.selectorGroup}>
                <label htmlFor="range-selector" className={styles.selectorLabel}>
                  Time Range:
                </label>
                <select
                  id="range-selector"
                  className={styles.selectInput}
                  value={selectedRange}
                  onChange={(e) => setSelectedRange(e.target.value as TimeRangeFilter)}
                  aria-label="Select history time range"
                >
                  <option value="live_15m">Live Stream (Last 15 Minutes)</option>
                  <option value="1h">Last 1 Hour</option>
                  <option value="24h">Last 24 Hours (Active Stream)</option>
                  <option value="7d">Last 7 Days</option>
                  <option value="kaggle_archive">Kaggle Baseline Window (Oct 2023)</option>
                  <option value="all">All Recorded History (Full Archive)</option>
                </select>
              </div>

              <div className={styles.historySummaryTag}>
                <span>Plotted: {historyReadings.length} readings</span>
              </div>
            </div>

            {/* History Error if request failed */}
            {historyError && (
              <InlineError
                title="Historical Telemetry Request Failed"
                message={historyError}
                onRetry={() =>
                  loadHistoryData(patientId!, selectedMetric, selectedRange, isFixtureMode)
                }
              />
            )}

            {/* Time Series SVG Chart */}
            <VitalTimeSeriesChart
              readings={historyReadings}
              metricCode={selectedMetric}
              metricLabel={currentMetricDef.label}
              metricUnit={currentMetricDef.unit}
              timeRangeDescription={getTimeRangeDescription(selectedRange)}
              isLoading={historyLoading}
            />
          </section>

          {/* 6. Active Alerts Queue for this Patient */}
          <section className={styles.alertsSectionCard} aria-label="Alerts Log for Patient">
            <div className={styles.alertsHeaderRow}>
              <h2 className={styles.alertsHeading}>Alerts Log for {patient.name}</h2>
              {alerts.length > 0 && (
                <StatusBadge
                  variant="elevated"
                  label={`${alerts.filter((a) => a.status === 'open').length} Open Alerts`}
                />
              )}
            </div>

            {alertsError ? (
              <InlineError title="Alert Queue Communication Error" message={alertsError} />
            ) : alerts.length === 0 ? (
              <div
                style={{
                  padding: '20px',
                  textAlign: 'center',
                  backgroundColor: 'var(--color-bg-surface-subtle)',
                  borderRadius: 'var(--radius-xs)',
                  border: '1px dashed var(--color-border-base)',
                  fontSize: '13px',
                  color: 'var(--color-text-secondary)',
                }}
              >
                No active or historical alerts logged for this patient.
              </div>
            ) : (
              <div className={styles.alertList}>
                {alerts.map((alert) => (
                  <div
                    key={alert.alertId}
                    className={`${styles.alertItem} ${
                      alert.severity === 'critical' ? styles.alertItemCritical : ''
                    }`}
                  >
                    <div className={styles.alertHeader}>
                      <StatusBadge variant={alert.severity} />
                      <StatusBadge variant={alert.status} />
                      <span className={styles.alertTimestamp}>
                        Logged: {formatTimestamp(alert.createdAt)}
                      </span>
                      {alert.assessmentId && (
                        <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                          Ref: {alert.assessmentId}
                        </span>
                      )}
                    </div>
                    <p className={styles.alertReason}>{alert.reason}</p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};
