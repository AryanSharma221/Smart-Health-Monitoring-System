import React, { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth, useDevMode } from '../hooks';
import {
  fetchLiveDashboardOverview,
  buildFixtureOverviewData,
  getApiUrl,
  wsManager,
  type DashboardOverviewData,
  type WsStatusSnapshot,
} from '../api';
import { formatVitalValue, formatTimestamp } from '../utils';
import {
  SimulatedDataBanner,
  StatusBadge,
  Button,
  LoadingIndicator,
  InlineError,
  EmptyState,
  RefreshIcon,
  AlertTriangleIcon,
} from '../components/ui';
import { LiveTelemetryPanel } from '../features/vitals';
import { DemoSQLWorkbench } from '../features/demo';
import styles from './DashboardPage.module.css';

export const DashboardPage: React.FC = () => {
  const { currentUser } = useAuth();
  const { isFixtureMode, toggleFixtureMode } = useDevMode();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab = searchParams.get('tab') === 'workbench' ? 'workbench' : 'telemetry';

  const handleSelectTab = (tab: 'telemetry' | 'workbench') => {
    if (tab === 'workbench') {
      setSearchParams({ tab: 'workbench' });
    } else {
      setSearchParams({});
      void handleManualRefresh();
    }
  };

  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [data, setData] = useState<DashboardOverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gatewayStatus, setGatewayStatus] = useState<'probing' | 'online' | 'offline'>('probing');
  const [wsSnapshot, setWsSnapshot] = useState<WsStatusSnapshot>(() => wsManager.getSnapshot());

  useEffect(() => {
    const unsubscribe = wsManager.subscribeStatus((snapshot) => {
      setWsSnapshot(snapshot);
    });

    if (!isFixtureMode && currentUser) {
      void wsManager.connect();
    } else if (isFixtureMode) {
      wsManager.disconnect();
    }

    return () => {
      unsubscribe();
    };
  }, [isFixtureMode, currentUser]);

  const probeGateway = useCallback(async () => {
    try {
      const res = await fetch(getApiUrl('/health'), { method: 'GET' });
      setGatewayStatus(res.ok || res.status === 401 || res.status === 403 ? 'online' : 'offline');
    } catch {
      setGatewayStatus('offline');
    }
  }, []);

  const fetchDashboardData = useCallback(async (useFixtures: boolean) => {
    if (useFixtures) {
      try {
        const liveOverview = await fetchLiveDashboardOverview();
        return {
          ...liveOverview,
          isFixtureMode: true,
        };
      } catch (err: unknown) {
        console.warn('Live gateway unavailable in Demo Mode, using isolated fixtures:', err);
        return buildFixtureOverviewData(currentUser);
      }
    }
    return fetchLiveDashboardOverview();
  }, [currentUser]);

  useEffect(() => {
    let isCancelled = false;

    async function loadInitial() {
      setError(null);
      void probeGateway();
      try {
        const result = await fetchDashboardData(isFixtureMode);
        if (!isCancelled) {
          setData(result);
          setLoading(false);
        }
      } catch (err: unknown) {
        if (!isCancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to query dashboard from FastAPI backend.';
          setError(msg);
          setLoading(false);
        }
      }
    }

    loadInitial();

    return () => {
      isCancelled = true;
    };
  }, [fetchDashboardData, isFixtureMode, probeGateway]);

  const handleManualRefresh = async () => {
    setRefreshing(true);
    setError(null);
    void probeGateway();
    try {
      const refreshed = await fetchDashboardData(isFixtureMode);
      setData(refreshed);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query dashboard from FastAPI backend.';
      setError(msg);
    } finally {
      setRefreshing(false);
    }
  };

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    void probeGateway();
    fetchDashboardData(isFixtureMode)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : 'Failed to query dashboard from FastAPI backend.';
        setError(msg);
        setLoading(false);
      });
  };

  const handleToggleFixtureMode = () => {
    toggleFixtureMode();
    setLoading(true);
    setError(null);
  };

  // Derive clinician display name
  const clinicianName = data?.clinician?.name || currentUser?.name || null;

  return (
    <div className={styles.container}>
      {/* 1. Persistent Safety Warning */}
      <SimulatedDataBanner detail="Authorization boundary: Connects exclusively to central FastAPI gateway." />

      {/* Fixture Mode Banner if active */}
      {data?.isFixtureMode && (
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

      {/* 2. Page Header & Brief Context */}
      <header className={styles.headerSection}>
        <div className={styles.headerTopRow}>
          <div className={styles.headerTitleCol}>
            <h1 className={styles.title}>Overview</h1>
            <p className={styles.subtitle}>
              Continuous vital telemetry and anomaly surveillance for assigned patients
              {clinicianName ? ` · Logged in as ${clinicianName}` : ''}.
            </p>
          </div>

          <div className={styles.headerActions}>
            <div className={styles.refreshMeta}>
              <span className={styles.lastRefreshedLabel}>Last Successful Refresh</span>
              <span className={styles.lastRefreshedValue}>
                {data?.lastRefreshed ? formatTimestamp(data.lastRefreshed) : 'Not refreshed'}
              </span>
            </div>

            <Button
              variant="secondary"
              size="sm"
              onClick={handleManualRefresh}
              disabled={loading || refreshing}
              className={styles.refreshBtn}
              aria-label="Refresh dashboard data"
            >
              <RefreshIcon size={14} className={refreshing ? styles.spinIcon : undefined} />
              <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Main Error Banner if live query failed */}
      {error && !data?.isFixtureMode && (
        <InlineError
          title="FastAPI Gateway Communication Failure"
          message={error}
          onRetry={handleRetry}
        />
      )}

      {/* Development Fixture Affordance when live query is down */}
      {error && !data?.isFixtureMode && (
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
            FastAPI service is offline. Would you like to inspect the clinical workstation layout using isolated Kaggle P101–P105 demonstration fixtures?
          </span>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Inspect with Development Fixtures
          </Button>
        </div>
      )}

      {/* 3. Compact Operational Summary Strip */}
      <section aria-label="Operational Summary" className={styles.summaryGrid}>
        {/* Assigned Patients */}
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Assigned Patients</span>
          <div className={styles.summaryValueRow}>
            {loading ? (
              <span className={styles.summaryValueUnavailable}>--</span>
            ) : data?.summary.assignedPatientsCount !== null && data?.summary.assignedPatientsCount !== undefined ? (
              <span className={styles.summaryValue}>{data.summary.assignedPatientsCount}</span>
            ) : (
              <span className={styles.summaryValueUnavailable}>--</span>
            )}
          </div>
          <span className={styles.summaryDetail}>Patients authorized in MySQL</span>
        </div>

        {/* Alerts Requiring Review */}
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Alerts Requiring Review</span>
          <div className={styles.summaryValueRow}>
            {loading ? (
              <span className={styles.summaryValueUnavailable}>--</span>
            ) : data?.summary.openAlertsCount !== null && data?.summary.openAlertsCount !== undefined ? (
              <span className={styles.summaryValue}>{data.summary.openAlertsCount}</span>
            ) : (
              <span className={styles.summaryValueUnavailable}>--</span>
            )}
          </div>
          <span className={styles.summaryDetail}>Open status awaiting triage</span>
        </div>

        {/* Fresh Feeds */}
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Fresh Feeds</span>
          <div className={styles.summaryValueRow}>
            {loading ? (
              <span className={styles.summaryValueUnavailable}>--</span>
            ) : data?.summary.freshFeedsCount !== null && data?.summary.freshFeedsCount !== undefined ? (
              <span className={styles.summaryValue}>{data.summary.freshFeedsCount}</span>
            ) : (
              <span className={styles.summaryValueUnavailable}>--</span>
            )}
          </div>
          <span className={styles.summaryDetail}>Active readings &le;60s</span>
        </div>

        {/* Stale or Unavailable Feeds */}
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Stale / Unavailable Feeds</span>
          <div className={styles.summaryValueRow}>
            {loading ? (
              <span className={styles.summaryValueUnavailable}>--</span>
            ) : data?.summary.staleOrUnavailableCount !== null && data?.summary.staleOrUnavailableCount !== undefined ? (
              <span className={styles.summaryValue}>{data.summary.staleOrUnavailableCount}</span>
            ) : (
              <span className={styles.summaryValueUnavailable}>--</span>
            )}
          </div>
          <span className={styles.summaryDetail}>Historical (&gt;60s) or no data</span>
        </div>
      </section>

      {/* Mode-Aware Navigation Tabs (Exclusively shown in Demo Mode or when Workbench requested) */}
      {(isFixtureMode || activeTab === 'workbench') && (
        <div className={styles.demoTabContainer} role="tablist" aria-label="Demo Mode Sections">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'telemetry'}
            className={`${styles.demoTabBtn} ${activeTab === 'telemetry' ? styles.demoTabBtnActive : ''}`}
            onClick={() => handleSelectTab('telemetry')}
          >
            <span>Assigned Patient Feeds</span>
            <span className={styles.tabBadgeCohort}>P101–P105 Cohort</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'workbench'}
            className={`${styles.demoTabBtn} ${activeTab === 'workbench' ? styles.demoTabBtnActive : ''}`}
            onClick={() => handleSelectTab('workbench')}
          >
            <span>Demo SQL Workbench</span>
            <span className={styles.tabBadgeDemo}>DEMO ONLY</span>
          </button>
        </div>
      )}

      {activeTab === 'workbench' ? (
        <DemoSQLWorkbench
          isDemoMode={isFixtureMode}
          onRefreshHistory={handleManualRefresh}
          targetPatientId="P101"
          onSwitchToDemoMode={handleToggleFixtureMode}
        />
      ) : (
        <>
          {/* 4. Patient Monitoring Section */}
          <section className={styles.sectionCard} aria-label="Assigned Patient Surveillance Feeds">
        <div className={styles.sectionHeaderRow}>
          <div>
            <h2 className={styles.sectionHeading}>Assigned Patient Feeds</h2>
            <p className={styles.sectionSubheading}>
              Continuous telemetry streams and anomaly flags for patients assigned to your clinician account.
            </p>
          </div>
          <Link to="/patients" className={styles.sectionLink}>
            View All Patients &rarr;
          </Link>
        </div>

        {loading ? (
          <div style={{ padding: '24px 0' }}>
            <LoadingIndicator label="Querying patient telemetry from FastAPI gateway…" />
          </div>
        ) : error && !data?.isFixtureMode ? (
          <EmptyState
            preset="failed_request"
            title="Unable to Retrieve Patient Feeds"
            description="The dashboard cannot establish a session with the central FastAPI gateway. Ensure the service is active on port 8000."
            actionLabel="Retry Connection"
            onAction={handleRetry}
          />
        ) : !data || data.patientRows.length === 0 ? (
          <EmptyState
            preset="no_patients"
            title="No Patients Assigned"
            description="No patient accounts are currently linked to your clinician profile in MySQL assignments. Patient assignment is managed server-side."
          />
        ) : (
          <>
            {/* Live Smartwatch Telemetry Surveillance & Time-Series Visualizer */}
            <LiveTelemetryPanel
              patientRows={data.patientRows}
              isFixtureMode={data.isFixtureMode}
            />

            {/* Desktop Table View */}
            <div className={styles.tableResponsive}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Patient Identity</th>
                    <th>Latest Available Readings</th>
                    <th>Data Provenance</th>
                    <th>Feed Freshness</th>
                    <th>Last Measured Time</th>
                    <th>Alert Status</th>
                    <th className={styles.actionCol}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data.patientRows.map((row) => {
                    const hrVital = row.latestVitals.find((v) => v.metricCode === 'heart_rate');
                    const spo2Vital = row.latestVitals.find((v) => v.metricCode === 'spo2');
                    const tempVital = row.latestVitals.find(
                      (v) => v.metricCode === 'temperature_f' || v.metricCode === 'temperature_c'
                    );

                    return (
                      <tr key={row.patient.patientId}>
                        <td>
                          <div className={styles.patientIdentity}>
                            <span className={styles.patientName}>{row.patient.name}</span>
                            <span className={styles.patientIdTag}>
                              ID: {row.patient.patientId}
                              {row.patient.sourcePatientId && row.patient.sourcePatientId !== row.patient.patientId
                                ? ` · Source: ${row.patient.sourcePatientId}`
                                : ''}
                            </span>
                          </div>
                        </td>

                        <td>
                          {row.vitalsError ? (
                            <span style={{ fontSize: '12px', color: 'var(--color-error-base)' }}>
                              Telemetry query error
                            </span>
                          ) : row.latestVitals.length === 0 ? (
                            <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
                              No measurements recorded
                            </span>
                          ) : (
                            <div className={styles.vitalsRow}>
                              {hrVital && (
                                <span className={styles.vitalPill} title="Heart Rate">
                                  <span className={styles.vitalPillLabel}>HR:</span>
                                  <span className={styles.vitalPillValue}>
                                    {formatVitalValue(hrVital.value, hrVital.unit, 0)}
                                  </span>
                                </span>
                              )}
                              {spo2Vital && (
                                <span className={styles.vitalPill} title="Oxygen Saturation">
                                  <span className={styles.vitalPillLabel}>SpO2:</span>
                                  <span className={styles.vitalPillValue}>
                                    {formatVitalValue(spo2Vital.value, spo2Vital.unit, 1)}
                                  </span>
                                </span>
                              )}
                              {tempVital && (
                                <span className={styles.vitalPill} title="Body Temperature">
                                  <span className={styles.vitalPillLabel}>Temp:</span>
                                  <span className={styles.vitalPillValue}>
                                    {formatVitalValue(tempVital.value, tempVital.unit, 1)}
                                  </span>
                                </span>
                              )}
                            </div>
                          )}
                        </td>

                        <td>
                          <span
                            style={{
                              display: 'inline-block',
                              padding: '2px 8px',
                              fontSize: '11px',
                              fontWeight: 700,
                              borderRadius: '4px',
                              backgroundColor: row.isSelfAdded ? '#e0f2fe' : row.isSimulated ? '#eff6ff' : '#f1f5f9',
                              color: row.isSelfAdded ? '#0369a1' : row.isSimulated ? '#1d4ed8' : '#475569',
                              border: row.isSelfAdded ? '1px solid #7dd3fc' : row.isSimulated ? '1px solid #bfdbfe' : '1px solid #cbd5e1',
                            }}
                          >
                            {row.provenanceLabel || (row.isSelfAdded ? 'SELF-ADDED (DEMO)' : row.isSimulated ? 'SIMULATED DEMO DATA' : 'HISTORICAL DATASET')}
                          </span>
                        </td>

                        <td>
                          <StatusBadge variant={row.feedFreshness} />
                        </td>

                        <td className={styles.timestampCol}>
                          {row.mostRecentMeasurementTime
                            ? formatTimestamp(row.mostRecentMeasurementTime)
                            : '— (Unavailable)'}
                        </td>

                        <td>
                          {row.openAlertsCount > 0 ? (
                            <StatusBadge
                              variant="elevated"
                              label={`${row.openAlertsCount} Open Alert${row.openAlertsCount > 1 ? 's' : ''}`}
                            />
                          ) : (
                            <StatusBadge variant="normal_like" label="No Open Alerts" />
                          )}
                        </td>

                        <td className={styles.actionCol}>
                          <Link
                            to={`/patients/${encodeURIComponent(row.patient.patientId)}`}
                            className={styles.viewDetailsBtn}
                            aria-label={`Open telemetry view for ${row.patient.name}`}
                          >
                            Inspect Feed &rarr;
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile Stacked Card View */}
            <div className={styles.mobilePatientCards}>
              {data.patientRows.map((row) => (
                <div key={row.patient.patientId} className={styles.mobileCard}>
                  <div className={styles.mobileCardHeader}>
                    <div className={styles.patientIdentity}>
                      <span className={styles.patientName}>{row.patient.name}</span>
                      <span className={styles.patientIdTag}>ID: {row.patient.patientId}</span>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                      <span
                        style={{
                          fontSize: '10px',
                          fontWeight: 700,
                          padding: '1px 6px',
                          borderRadius: '3px',
                          backgroundColor: row.isSelfAdded ? '#e0f2fe' : row.isSimulated ? '#eff6ff' : '#f1f5f9',
                          color: row.isSelfAdded ? '#0369a1' : row.isSimulated ? '#1d4ed8' : '#475569',
                        }}
                      >
                        {row.isSelfAdded ? 'Self-Added' : row.isSimulated ? 'Simulated' : 'Historical'}
                      </span>
                      <StatusBadge variant={row.feedFreshness} />
                    </div>
                  </div>

                  <div className={styles.vitalsRow}>
                    {row.latestVitals.map((v) => (
                      <span key={v.metricCode} className={styles.vitalPill}>
                        <span className={styles.vitalPillLabel}>{v.label}:</span>
                        <span className={styles.vitalPillValue}>
                          {formatVitalValue(v.value, v.unit)}
                        </span>
                      </span>
                    ))}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: 'var(--color-text-muted)' }}>
                    <span>Measured: {formatTimestamp(row.mostRecentMeasurementTime)}</span>
                    {row.openAlertsCount > 0 ? (
                      <StatusBadge variant="elevated" label={`${row.openAlertsCount} Alert`} />
                    ) : null}
                  </div>

                  <div>
                    <Link
                      to={`/patients/${encodeURIComponent(row.patient.patientId)}`}
                      className={styles.viewDetailsBtn}
                      style={{ display: 'block', textAlign: 'center' }}
                    >
                      Inspect Telemetry Feed &rarr;
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      {/* 5. Alerts Requiring Review Section */}
      <section className={styles.sectionCard} aria-label="Alerts Requiring Review">
        <div className={styles.sectionHeaderRow}>
          <div>
            <h2 className={styles.sectionHeading}>Alerts Requiring Review</h2>
            <p className={styles.sectionSubheading}>
              Physiological threshold crossings and predefined simulated anomaly alerts awaiting clinician triage.
            </p>
          </div>
          <Link to="/alerts" className={styles.sectionLink}>
            Open Alerts Queue &rarr;
          </Link>
        </div>

        {loading ? (
          <div style={{ padding: '16px 0' }}>
            <LoadingIndicator label="Querying alert registry…" />
          </div>
        ) : !data || data.reviewAlerts.length === 0 ? (
          <div
            style={{
              padding: '24px',
              textAlign: 'center',
              backgroundColor: 'var(--color-bg-surface-subtle)',
              borderRadius: 'var(--radius-xs)',
              border: '1px dashed var(--color-border-base)',
              color: 'var(--color-text-secondary)',
              fontSize: '13px',
            }}
          >
            No active alerts currently require review. All assigned patient telemetry streams are operating within baseline thresholds.
          </div>
        ) : (
          <div className={styles.alertsList}>
            {data.reviewAlerts.map((alert) => (
              <div
                key={alert.alertId}
                className={`${styles.alertItem} ${
                  alert.severity === 'critical' ? styles.alertItemCritical : ''
                }`}
              >
                <div className={styles.alertLeft}>
                  <div className={styles.alertTopLine}>
                    <StatusBadge variant={alert.severity} />
                    <span className={styles.alertPatientRef}>
                      Patient Ref: {alert.patientId}
                    </span>
                    <span className={styles.alertTimestamp}>
                      Logged: {formatTimestamp(alert.createdAt)}
                    </span>
                    <StatusBadge variant={alert.status} />
                  </div>
                  <p className={styles.alertReason}>{alert.reason}</p>
                </div>

                <div className={styles.alertRight} style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <Link
                    to={`/alerts?patientId=${encodeURIComponent(alert.patientId)}&alertId=${encodeURIComponent(alert.alertId)}`}
                    className={styles.viewDetailsBtn}
                    aria-label={`Review alert ${alert.alertId} in alerts queue`}
                  >
                    Review Alert &rarr;
                  </Link>
                  <Link
                    to={`/patients/${encodeURIComponent(alert.patientId)}`}
                    className={styles.viewDetailsBtn}
                    style={{ backgroundColor: 'transparent', border: '1px solid var(--color-border-base)', color: 'var(--color-text-secondary)' }}
                    aria-label={`Inspect patient ${alert.patientId} telemetry`}
                  >
                    Vitals
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
        </>
      )}

      {/* 6. Backend and Live-Update Connection Status Strip */}
      <section className={styles.connectionConsole} aria-label="System Connectivity and Gateway Status">
        <div className={styles.consoleHeader}>
          <span className={styles.consoleTitle}>Workstation Infrastructure &amp; Connectivity Status</span>
          <span style={{ fontSize: '11px', color: 'var(--color-nav-text-secondary)', fontFamily: 'var(--font-mono)' }}>
            Architecture: REST / WS / MySQL / MongoDB
          </span>
        </div>

        <div className={styles.consoleGrid}>
          {/* REST API Gateway */}
          <div className={styles.consoleItem}>
            <div className={styles.consoleItemHeader}>
              <span className={styles.consoleItemLabel}>REST API Gateway</span>
              <StatusBadge
                variant={
                  data?.apiConnected || gatewayStatus === 'online'
                    ? 'fresh'
                    : gatewayStatus === 'probing'
                    ? 'info'
                    : 'disconnected'
                }
                label={
                  data?.apiConnected
                    ? 'API Connected'
                    : gatewayStatus === 'online'
                    ? 'Gateway Online'
                    : gatewayStatus === 'probing'
                    ? 'Probing…'
                    : 'Gateway Offline'
                }
              />
            </div>
            <span className={styles.consoleItemValue}>http://localhost:8000/api/v1</span>
            <span className={styles.consoleItemDetail}>
              Authoritative endpoint for authentication, patient profiles, readings, and alerts.
            </span>
          </div>

          {/* WebSocket Status */}
          <div className={styles.consoleItem}>
            <div className={styles.consoleItemHeader}>
              <span className={styles.consoleItemLabel}>Live WebSocket Stream</span>
              <StatusBadge
                variant={
                  wsSnapshot.state === 'connected'
                    ? 'fresh'
                    : wsSnapshot.state === 'connecting'
                    ? 'info'
                    : wsSnapshot.state === 'reconnecting'
                    ? 'advisory'
                    : wsSnapshot.state === 'error'
                    ? 'critical'
                    : !currentUser
                    ? 'advisory'
                    : wsSnapshot.state === 'not_configured'
                    ? 'unavailable'
                    : 'disconnected'
                }
                label={
                  wsSnapshot.state === 'connected'
                    ? 'CONNECTED'
                    : !currentUser
                    ? 'AWAITING LOGIN'
                    : wsSnapshot.state.toUpperCase()
                }
              />
            </div>
            <span className={styles.consoleItemValue}>{wsSnapshot.url}</span>
            <span className={styles.consoleItemDetail}>
              {wsSnapshot.state === 'connected'
                ? `Active real-time telemetry stream. Last event: ${formatTimestamp(wsSnapshot.lastEventReceivedAt)}`
                : !currentUser
                ? 'Ticket-authenticated bidirectional telemetry stream. Clinician login required to open stream.'
                : 'Ticket-authenticated bidirectional telemetry stream. Diagnostics in System Status.'}
            </span>
          </div>

          {/* Dataset Provenance */}
          <div className={styles.consoleItem}>
            <div className={styles.consoleItemHeader}>
              <span className={styles.consoleItemLabel}>Data Provenance</span>
              <StatusBadge
                variant="advisory"
                label="Kaggle Cohort"
              />
            </div>
            <span className={styles.consoleItemValue}>1,500 Historical Events (P101–P105)</span>
            <span className={styles.consoleItemDetail}>
              Continuous ambulatory telemetry: heart rate, SpO2, body temperature.
            </span>
          </div>

          {/* Regulatory Safety Boundary */}
          <div className={styles.consoleItem}>
            <div className={styles.consoleItemHeader}>
              <span className={styles.consoleItemLabel}>Safety Boundary</span>
              <span
                style={{
                  color: '#fbbf24',
                  fontSize: '11px',
                  fontWeight: 600,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                <AlertTriangleIcon size={12} />
                <span>Simulated Only</span>
              </span>
            </div>
            <span className={styles.consoleItemValue}>NOT FOR MEDICAL USE</span>
            <span className={styles.consoleItemDetail}>
              Software evaluation workstation. Readings are synthetic and not diagnostic.
            </span>
          </div>
        </div>
      </section>
    </div>
  );
};
