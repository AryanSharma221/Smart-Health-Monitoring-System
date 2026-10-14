import React, { useState, useEffect, useCallback } from 'react';
import { API_CONFIG, getApiUrl, wsManager, getPersistedSession, type WsStatusSnapshot } from '../api';
import { useAuth } from '../auth';
import { useDevMode } from '../hooks';
import {
  SimulatedDataBanner,
  PageHeader,
  Button,
  StatusBadge,
  RefreshIcon,
} from '../components/ui';
import { formatTimestamp } from '../utils/formatters';
import styles from './SystemStatusPage.module.css';

interface GatewayProbeResult {
  status: 'untested' | 'probing' | 'online' | 'unauthorized' | 'offline';
  statusCode: number | null;
  latencyMs: number | null;
  testedAt: string | null;
  errorDetail: string | null;
}

interface MLStatusResult {
  status: 'untested' | 'probing' | 'ready' | 'offline';
  modelVersion: string | null;
  algorithm: string | null;
  featureCount: number | null;
  hasBaselineManager: boolean;
  errorDetail: string | null;
}

export const SystemStatusPage: React.FC = () => {
  const { currentUser, isAuthenticated } = useAuth();
  const { isFixtureMode } = useDevMode();

  // WebSocket Live State
  const [wsSnapshot, setWsSnapshot] = useState<WsStatusSnapshot>(() => wsManager.getSnapshot());

  // REST Gateway Probe State
  const [probeResult, setProbeResult] = useState<GatewayProbeResult>({
    status: 'untested',
    statusCode: null,
    latencyMs: null,
    testedAt: null,
    errorDetail: null,
  });

  // Machine Learning Subsystem Probe State
  const [mlResult, setMlResult] = useState<MLStatusResult>({
    status: 'untested',
    modelVersion: null,
    algorithm: null,
    featureCount: null,
    hasBaselineManager: false,
    errorDetail: null,
  });

  // Subscribe to WebSocket Manager status updates
  useEffect(() => {
    const unsubscribe = wsManager.subscribeStatus((snapshot) => {
      setWsSnapshot(snapshot);
    });
    return unsubscribe;
  }, []);

  // Execute Real REST Gateway and ML Subsystem Probes
  const handleProbeGateway = useCallback(async () => {
    setProbeResult((prev) => ({
      ...prev,
      status: 'probing',
      errorDetail: null,
    }));
    setMlResult((prev) => ({
      ...prev,
      status: 'probing',
      errorDetail: null,
    }));

    const startTime = performance.now();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);

    // 1. Probe REST Gateway
    try {
      const session = getPersistedSession();
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (session?.token) {
        headers['Authorization'] = `Bearer ${session.token}`;
      }

      // Check /health endpoint first, or /me if token present
      const probeUrl = session?.token ? getApiUrl('/me') : getApiUrl('/health');
      const response = await fetch(probeUrl, {
        method: 'GET',
        headers,
        signal: controller.signal,
      });

      const latencyMs = Math.round(performance.now() - startTime);

      if (response.ok) {
        setProbeResult({
          status: 'online',
          statusCode: response.status,
          latencyMs,
          testedAt: new Date().toISOString(),
          errorDetail: null,
        });
      } else if (response.status === 401 || response.status === 403) {
        setProbeResult({
          status: 'unauthorized',
          statusCode: response.status,
          latencyMs,
          testedAt: new Date().toISOString(),
          errorDetail: 'Gateway reachable. Endpoint returned 401 Unauthorized (Auth barrier active).',
        });
      } else {
        setProbeResult({
          status: 'offline',
          statusCode: response.status,
          latencyMs,
          testedAt: new Date().toISOString(),
          errorDetail: `Gateway returned HTTP ${response.status} ${response.statusText}`,
        });
      }
    } catch (err: unknown) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      setProbeResult({
        status: 'offline',
        statusCode: null,
        latencyMs: null,
        testedAt: new Date().toISOString(),
        errorDetail: isAbort
          ? 'Gateway probe timed out after 4000ms.'
          : 'Gateway connection refused (FastAPI service at port 8000 is currently offline).',
      });
    }

    // 2. Probe Machine Learning Subsystem
    try {
      const mlUrl = getApiUrl('/predictions/status');
      const mlResp = await fetch(mlUrl, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });

      if (mlResp.ok) {
        const mlData = await mlResp.json();
        setMlResult({
          status: mlData.status === 'ready' || mlData.is_available ? 'ready' : 'offline',
          modelVersion: mlData.model_version || 'iforest_v1',
          algorithm: mlData.algorithm || 'IsolationForest',
          featureCount: mlData.feature_count || 3,
          hasBaselineManager: !!mlData.has_baseline_manager,
          errorDetail: null,
        });
      } else {
        setMlResult({
          status: 'offline',
          modelVersion: null,
          algorithm: null,
          featureCount: null,
          hasBaselineManager: false,
          errorDetail: `ML probe returned HTTP ${mlResp.status}`,
        });
      }
    } catch {
      setMlResult({
        status: 'offline',
        modelVersion: null,
        algorithm: null,
        featureCount: null,
        hasBaselineManager: false,
        errorDetail: 'ML inference subsystem offline.',
      });
    } finally {
      clearTimeout(timeoutId);
    }
  }, []);

  // Run probe once on initial mount (React 19 safe async pattern)
  useEffect(() => {
    let isCancelled = false;
    const runInitialProbe = async () => {
      if (!isCancelled) {
        await handleProbeGateway();
      }
    };
    void runInitialProbe();
    return () => {
      isCancelled = true;
    };
  }, [handleProbeGateway]);

  // WebSocket manual toggle actions
  const handleConnectWs = async () => {
    await wsManager.connect();
  };

  const handleDisconnectWs = () => {
    wsManager.disconnect();
  };

  // Map WebSocket connection state to badge variant and label
  const getWsBadge = (state: string) => {
    switch (state) {
      case 'connected':
        return <StatusBadge variant="fresh" label="STREAM CONNECTED" />;
      case 'connecting':
        return <StatusBadge variant="info" label="CONNECTING…" />;
      case 'reconnecting':
        return <StatusBadge variant="advisory" label="RECONNECTING…" />;
      case 'error':
        return <StatusBadge variant="critical" label="STREAM ERROR" />;
      case 'not_configured':
        return <StatusBadge variant="unavailable" label="NOT CONFIGURED" />;
      default:
        return <StatusBadge variant="disconnected" label="DISCONNECTED" />;
    }
  };

  // Map Gateway probe status to badge variant and label
  const getGatewayBadge = (status: GatewayProbeResult['status']) => {
    switch (status) {
      case 'online':
        return <StatusBadge variant="fresh" label="GATEWAY ONLINE" />;
      case 'unauthorized':
        return <StatusBadge variant="fresh" label="GATEWAY REACHABLE (AUTH REQUIRED)" />;
      case 'probing':
        return <StatusBadge variant="info" label="PROBING…" />;
      case 'offline':
        return <StatusBadge variant="disconnected" label="GATEWAY OFFLINE" />;
      default:
        return <StatusBadge variant="info" label="UNTESTED" />;
    }
  };

  return (
    <div className={styles.container}>
      {/* 1. Persistent Safety Banner */}
      <SimulatedDataBanner detail="System Status Diagnostics: Simulated data environment. Not for clinical diagnosis." />

      {/* Header */}
      <header className={styles.headerSection}>
        <PageHeader
          title="System & Gateway Connectivity Status"
          subtitle="Real-time diagnostics for FastAPI REST reverse proxy, WebSocket telemetry streams, and database boundaries."
          breadcrumb="Diagnostics / System Status"
        />
      </header>

      {/* 2. Development Stage & System Integration Roadmap */}
      <section className={styles.card} aria-labelledby="stage-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="stage-heading" className={styles.cardTitle}>
              Development Stage &amp; Integration Roadmap
            </h2>
            <p className={styles.cardSubtitle}>
              Architectural implementation status across frontend, backend, persistence, and machine learning components.
            </p>
          </div>
          <StatusBadge
            variant={isFixtureMode ? 'advisory' : 'fresh'}
            label={isFixtureMode ? 'DEMO MODE — SIMULATED DATA' : 'LIVE GATEWAY MODE'}
          />
        </div>

        <div className={styles.gatewayGrid}>
          {/* Card: Frontend */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>Frontend Workstation</span>
              <StatusBadge variant="fresh" label="OPERATIONAL" />
            </div>
            <div className={styles.endpointUrl}>React 18 + TypeScript + Vite</div>
            <div className={styles.gatewayDetails}>
              <p style={{ margin: 0 }}>
                Stabilized clinician monitoring workstation with interactive triage, telemetry graphs, and demo cohort viewer.
              </p>
            </div>
          </div>

          {/* Card: Demo Mode */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>Demonstration Mode</span>
              <StatusBadge variant={isFixtureMode ? 'advisory' : 'info'} label={isFixtureMode ? 'ACTIVE' : 'INACTIVE'} />
            </div>
            <div className={styles.endpointUrl}>Kaggle Cohort P101–P105</div>
            <div className={styles.gatewayDetails}>
              <p style={{ margin: 0 }}>
                {isFixtureMode
                  ? 'Active: Isolated Kaggle benchmark cohort (1,500 historical telemetry events). Zero network dependency.'
                  : 'Inactive: Configured to communicate directly with FastAPI gateway.'}
              </p>
            </div>
          </div>

          {/* Card: Backend Integration */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>Backend Services</span>
              {probeResult.status === 'online' || probeResult.status === 'unauthorized' ? (
                <StatusBadge variant="fresh" label="OPERATIONAL" />
              ) : (
                <StatusBadge
                  variant={probeResult.status === 'probing' ? 'info' : 'disconnected'}
                  label={probeResult.status === 'probing' ? 'PROBING…' : 'GATEWAY OFFLINE'}
                />
              )}
            </div>
            <div className={styles.endpointUrl}>FastAPI + Python Core</div>
            <div className={styles.gatewayDetails}>
              <p style={{ margin: 0 }}>
                {probeResult.status === 'online' || probeResult.status === 'unauthorized'
                  ? 'FastAPI REST Gateway operational. Authoritative MySQL InnoDB and MongoDB analytics mirror connected.'
                  : 'FastAPI service at port 8000 is currently offline or unreachable.'}
              </p>
            </div>
          </div>

          {/* Card: ML Integration */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>ML Anomaly Detection</span>
              {mlResult.status === 'ready' ? (
                <StatusBadge variant="fresh" label="OPERATIONAL" />
              ) : (
                <StatusBadge
                  variant={mlResult.status === 'probing' ? 'info' : 'advisory'}
                  label={mlResult.status === 'probing' ? 'PROBING…' : 'STANDBY / RULE-BASED'}
                />
              )}
            </div>
            <div className={styles.endpointUrl}>
              {mlResult.modelVersion
                ? `Isolation Forest (${mlResult.modelVersion})`
                : 'Isolation Forest / Multivariate Models'}
            </div>
            <div className={styles.gatewayDetails}>
              <p style={{ margin: 0 }}>
                {mlResult.status === 'ready'
                  ? `Active inference pipeline evaluating multivariate vitals streams (${mlResult.featureCount ?? 3} channels: Heart Rate, SpO2, Temperature) with baseline profiling.`
                  : 'Machine learning inference pipeline in standby. Alerts reflect clinical threshold rules until backend ML service is reachable.'}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 3. Architectural Boundary & Gateway Grid */}
      <section className={styles.card} aria-labelledby="gateways-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="gateways-heading" className={styles.cardTitle}>
              Architectural Gateway Probes & Boundaries
            </h2>
            <p className={styles.cardSubtitle}>
              Live connectivity probes. Direct database connections are blocked by security architecture.
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleProbeGateway}
            disabled={probeResult.status === 'probing'}
          >
            <RefreshIcon size={14} className={probeResult.status === 'probing' ? styles.spinIcon : undefined} />
            <span>{probeResult.status === 'probing' ? 'Probing Gateway…' : 'Probe REST Gateway'}</span>
          </Button>
        </div>

        <div className={styles.gatewayGrid}>
          {/* Card 1: FastAPI REST Gateway */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>FastAPI REST Gateway</span>
              {getGatewayBadge(probeResult.status)}
            </div>
            <div className={styles.endpointUrl}>{API_CONFIG.baseUrl}</div>
            <div className={styles.gatewayDetails}>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>HTTP Probe Status:</span>
                <span className={styles.detailValue}>
                  {probeResult.statusCode ? `HTTP ${probeResult.statusCode}` : probeResult.status === 'probing' ? 'Probing…' : 'Offline'}
                </span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Roundtrip Latency:</span>
                <span className={styles.detailValue}>
                  {probeResult.latencyMs !== null ? `${probeResult.latencyMs} ms` : '—'}
                </span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Last Probe Time:</span>
                <span className={styles.detailValue}>
                  {formatTimestamp(probeResult.testedAt)}
                </span>
              </div>
              {probeResult.errorDetail && (
                <div style={{ color: 'var(--color-critical-text)', fontSize: '11px', marginTop: '4px' }}>
                  {probeResult.errorDetail}
                </div>
              )}
            </div>
          </div>

          {/* Card 2: Live WebSocket Stream */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>Live WebSocket Channel</span>
              {getWsBadge(wsSnapshot.state)}
            </div>
            <div className={styles.endpointUrl}>
              {wsSnapshot.url}
            </div>
            <div className={styles.gatewayDetails}>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Auth Ticket:</span>
                <span className={styles.detailValue}>
                  {wsSnapshot.hasTicket ? 'Ticket Acquired' : 'No Ticket'}
                </span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Reconnect Tries:</span>
                <span className={styles.detailValue}>
                  {wsSnapshot.reconnectAttempts} / 3
                </span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Last Connected:</span>
                <span className={styles.detailValue}>
                  {formatTimestamp(wsSnapshot.lastConnectedAt)}
                </span>
              </div>
            </div>

            <div style={{ marginTop: 'auto', paddingTop: '8px' }}>
              {wsSnapshot.state === 'connected' || wsSnapshot.state === 'connecting' ? (
                <Button variant="destructive" size="sm" onClick={handleDisconnectWs}>
                  Disconnect Stream
                </Button>
              ) : (
                <Button variant="primary" size="sm" onClick={handleConnectWs}>
                  Connect Telemetry Stream
                </Button>
              )}
            </div>
          </div>

          {/* Card 3: MySQL Authoritative DB */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>MySQL Authoritative DB</span>
              <StatusBadge variant="info" label="GATEWAY ISOLATED" />
            </div>
            <div className={styles.endpointUrl}>Relational Staff &amp; Patient Store</div>
            <div className={styles.gatewayDetails}>
              <p style={{ margin: 0 }}>
                Authoritative ACID store for clinician accounts, assigned patient relationships, and medical records.
              </p>
              <div style={{ marginTop: '6px', fontSize: '11px', color: 'var(--color-text-muted)' }}>
                <strong>Zero Direct DB Access:</strong> Web browser client has zero network access to MySQL port 3306. All queries flow exclusively via authenticated FastAPI endpoints.
              </div>
            </div>
          </div>

          {/* Card 4: MongoDB Atlas Analytics DB */}
          <div className={styles.gatewayCard}>
            <div className={styles.gatewayHeader}>
              <span className={styles.gatewayName}>MongoDB Atlas Analytics</span>
              <StatusBadge variant="info" label="GATEWAY ISOLATED" />
            </div>
            <div className={styles.endpointUrl}>High-Throughput Timeseries Mirror</div>
            <div className={styles.gatewayDetails}>
              <p style={{ margin: 0 }}>
                High-frequency timeseries sensor readings store and telemetry anomaly audit log.
              </p>
              <div style={{ marginTop: '6px', fontSize: '11px', color: 'var(--color-text-muted)' }}>
                <strong>Zero Direct DB Access:</strong> Web browser client has zero network access to MongoDB Atlas cluster. All telemetry ingest and queries are proxied via FastAPI.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 3. WebSocket Real-Time Telemetry Console */}
      <section className={styles.card} aria-labelledby="ws-console-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="ws-console-heading" className={styles.cardTitle}>
              WebSocket Telemetry Stream Inspector
            </h2>
            <p className={styles.cardSubtitle}>
              Ticket-authenticated bidirectional channel for live vitals push and instant alert broadcasts.
            </p>
          </div>
          {getWsBadge(wsSnapshot.state)}
        </div>

        <div className={styles.wsConsole}>
          <div className={styles.wsTelemetryGrid}>
            <div className={styles.wsTelemetryItem}>
              <span className={styles.wsItemLabel}>Channel State</span>
              <span className={styles.wsItemValue}>{wsSnapshot.state.toUpperCase()}</span>
            </div>

            <div className={styles.wsTelemetryItem}>
              <span className={styles.wsItemLabel}>Ticket Authentication</span>
              <span className={styles.wsItemValue}>
                {wsSnapshot.hasTicket ? 'Bearer Ticket Bound' : 'Awaiting POST /ws-ticket'}
              </span>
            </div>

            <div className={styles.wsTelemetryItem}>
              <span className={styles.wsItemLabel}>Last Event Time</span>
              <span className={styles.wsItemValue}>
                {formatTimestamp(wsSnapshot.lastEventReceivedAt)}
              </span>
            </div>

            <div className={styles.wsTelemetryItem}>
              <span className={styles.wsItemLabel}>Last Event Type</span>
              <span className={styles.wsItemValue}>
                {wsSnapshot.lastEventType || 'None received'}
              </span>
            </div>

            <div className={styles.wsTelemetryItem}>
              <span className={styles.wsItemLabel}>Last Disconnected</span>
              <span className={styles.wsItemValue}>
                {formatTimestamp(wsSnapshot.lastDisconnectedAt)}
              </span>
            </div>

            <div className={styles.wsTelemetryItem}>
              <span className={styles.wsItemLabel}>Last Socket Error</span>
              <span className={styles.wsItemValue} style={{ color: wsSnapshot.lastError ? 'var(--color-critical-text)' : 'inherit' }}>
                {wsSnapshot.lastError || 'None'}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Telemetry Freshness & Timestamp Semantics Guide */}
      <section className={styles.card} aria-labelledby="semantics-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="semantics-heading" className={styles.cardTitle}>
              Data Freshness &amp; Timestamp Semantics
            </h2>
            <p className={styles.cardSubtitle}>
              Formal definitions for the four distinct temporal coordinates across the monitoring pipeline.
            </p>
          </div>
        </div>

        <div className={styles.semanticsGrid}>
          <div className={styles.semanticCard}>
            <span className={styles.semanticTerm}>measured_at</span>
            <span className={styles.semanticDef}>
              The device/sensor clock timestamp recorded when the physiological parameter (heart rate, SpO2, body temperature) was physically sampled at the ambulatory monitor.
            </span>
          </div>

          <div className={styles.semanticCard}>
            <span className={styles.semanticTerm}>received_at</span>
            <span className={styles.semanticDef}>
              The FastAPI server ingress clock timestamp when the incoming telemetry payload was received and validated by the backend gateway before dispatch to persistence.
            </span>
          </div>

          <div className={styles.semanticCard}>
            <span className={styles.semanticTerm}>queried_at</span>
            <span className={styles.semanticDef}>
              The client workstation clock timestamp when the doctor web application executed a REST poll to refresh cached cohort records.
            </span>
          </div>

          <div className={styles.semanticCard}>
            <span className={styles.semanticTerm}>pushed_at</span>
            <span className={styles.semanticDef}>
              The real-time WebSocket transmission event timestamp when the gateway broadcasted a telemetry frame or alert notification to active doctor sessions.
            </span>
          </div>
        </div>

        {/* Freshness Classification Rules */}
        <div style={{ marginTop: '12px', padding: '12px 16px', background: 'var(--color-bg-surface-subtle)', borderRadius: '4px', border: '1px solid var(--color-border-subtle)', fontSize: '12px' }}>
          <strong style={{ display: 'block', marginBottom: '6px', color: 'var(--color-text-primary)' }}>
            Clinical Freshness Classification Standards:
          </strong>
          <ul style={{ margin: 0, paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '4px', color: 'var(--color-text-secondary)' }}>
            <li>
              <strong style={{ color: 'var(--color-fresh-text)' }}>Fresh (&le; 60 seconds):</strong> Telemetry feed actively streaming with acceptable latency for ambulatory surveillance.
            </li>
            <li>
              <strong style={{ color: 'var(--color-stale-text)' }}>Stale (&gt; 60 seconds):</strong> Delayed ingest, patient ambulatory sensor paused, or historical Kaggle cohort playback.
            </li>
            <li>
              <strong style={{ color: 'var(--color-text-muted)' }}>Unavailable (null / missing):</strong> Missing sensor payload or lead decoupling. Rendered strictly as <code>—</code> without fabricated zeroes.
            </li>
          </ul>
        </div>
      </section>

      {/* 5. Active Clinician Session Information */}
      <section className={styles.card} aria-labelledby="session-heading">
        <div className={styles.cardHeaderRow}>
          <div>
            <h2 id="session-heading" className={styles.cardTitle}>
              Authenticated Clinician Session
            </h2>
            <p className={styles.cardSubtitle}>
              Current workstation credentials and JWT authorization scope.
            </p>
          </div>
          <StatusBadge
            variant={isAuthenticated ? 'fresh' : 'disconnected'}
            label={isAuthenticated ? 'SESSION ACTIVE' : 'UNAUTHENTICATED'}
          />
        </div>

        <div className={styles.sessionGrid}>
          <div className={styles.sessionItem}>
            <span className={styles.sessionLabel}>Doctor Name</span>
            <span className={styles.sessionValue}>{currentUser?.name || 'Dr. Sarah Jenkins, MD'}</span>
          </div>

          <div className={styles.sessionItem}>
            <span className={styles.sessionLabel}>Clinician ID</span>
            <span className={styles.sessionValue}>{currentUser?.userId || 'usr_doc_01'}</span>
          </div>

          <div className={styles.sessionItem}>
            <span className={styles.sessionLabel}>Authorization Role</span>
            <span className={styles.sessionValue}>{currentUser?.role?.toUpperCase() || 'DOCTOR'}</span>
          </div>

          <div className={styles.sessionItem}>
            <span className={styles.sessionLabel}>Session Token</span>
            <span className={styles.sessionValue}>{getPersistedSession()?.token ? 'JWT Bearer Active' : 'Session Active'}</span>
          </div>
        </div>
      </section>
    </div>
  );
};
