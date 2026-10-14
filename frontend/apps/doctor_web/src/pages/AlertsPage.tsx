/**
 * SMART HEALTH MONITORING SYSTEM — CLINICAL SURVEILLANCE & ALERTS WORKSTATION
 * 
 * Responsibilities:
 * - Real-time surveillance feed across authorized clinician's assigned patients.
 * - Strict alignment with backend contract: aggregates GET /api/v1/patients/{id}/alerts.
 * - Actionable Acknowledge (POST /api/v1/alerts/{id}/acknowledge) and Resolve (POST /api/v1/alerts/{id}/resolve).
 * - Multi-criteria clinical filtering (Status, Severity, Patient, and Search).
 * - Full audit and timeline inspection drawer.
 * - SIMULATED DATA — NOT FOR MEDICAL USE.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import {
  fetchAssignedAlerts,
  acknowledgeAlert,
  resolveAlert,
} from '../api';
import type {
  PatientAlert,
  PatientProfile,
  AlertStatus,
  AlertSeverity,
} from '../types';
import { formatTimestamp } from '../utils';
import { useDevMode } from '../hooks';
import {
  SimulatedDataBanner,
  StatusBadge,
  Button,
  LoadingIndicator,
  InlineError,
  EmptyState,
  ConfirmationDialog,
  SearchIcon,
  RefreshIcon,
  CloseIcon,
  CheckIcon,
  CheckCircleIcon,
} from '../components/ui';
import styles from './AlertsPage.module.css';

export const AlertsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isFixtureMode, toggleFixtureMode } = useDevMode();

  // Primary Data State
  const [alerts, setAlerts] = useState<PatientAlert[]>([]);
  const [patients, setPatients] = useState<PatientProfile[]>([]);
  const [patientMap, setPatientMap] = useState<Map<string, PatientProfile>>(new Map());
  const [partialErrors, setPartialErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  // Filter State (initialized from URL query parameters if present)
  const initialPatient = searchParams.get('patientId') || 'all';
  const initialStatus = (searchParams.get('status') as AlertStatus) || 'all';
  const initialSeverity = (searchParams.get('severity') as AlertSeverity) || 'all';
  const initialAlertId = searchParams.get('alertId') || null;

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | AlertStatus>(initialStatus);
  const [severityFilter, setSeverityFilter] = useState<'all' | AlertSeverity>(initialSeverity);
  const [patientFilter, setPatientFilter] = useState<string>(initialPatient);

  // Selected Alert for Detail Drawer
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(initialAlertId);

  // Alert Mutation State
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [clinicianNote, setClinicianNote] = useState<string>('');
  const [resolveDialogOpen, setResolveDialogOpen] = useState<boolean>(false);
  const [alertToResolve, setAlertToResolve] = useState<PatientAlert | null>(null);

  // Load Data function
  const loadAlertsData = useCallback(async (useFixtures: boolean, targetPatientId?: string) => {
    setError(null);
    try {
      const result = await fetchAssignedAlerts({
        patientId: targetPatientId && targetPatientId !== 'all' ? targetPatientId : undefined,
        useFixtures,
      });

      setAlerts(result.alerts);
      setPatients(result.patients);
      setPatientMap(result.patientMap);
      setPartialErrors(result.partialErrors);
      setLastRefreshed(new Date().toISOString());
      return result;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query clinical alerts feed.';
      setError(msg);
      setAlerts([]);
      throw err;
    }
  }, []);

  // Primary Mount Effect
  useEffect(() => {
    let isCancelled = false;

    async function init() {
      setLoading(true);
      try {
        await loadAlertsData(isFixtureMode, patientFilter);
      } catch {
        // Error state handled in loadAlertsData
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    }

    init();

    return () => {
      isCancelled = true;
    };
  }, [loadAlertsData, isFixtureMode, patientFilter]);

  // Synchronize URL parameters when filters change
  const updateUrlFilters = useCallback(
    (newPatient: string, newStatus: string, newSeverity: string, newAlertId: string | null) => {
      const params = new URLSearchParams();
      if (newPatient !== 'all') params.set('patientId', newPatient);
      if (newStatus !== 'all') params.set('status', newStatus);
      if (newSeverity !== 'all') params.set('severity', newSeverity);
      if (newAlertId) params.set('alertId', newAlertId);
      setSearchParams(params, { replace: true });
    },
    [setSearchParams]
  );

  const handlePatientFilterChange = (val: string) => {
    setPatientFilter(val);
    updateUrlFilters(val, statusFilter, severityFilter, selectedAlertId);
  };

  const handleStatusFilterChange = (val: 'all' | AlertStatus) => {
    setStatusFilter(val);
    updateUrlFilters(patientFilter, val, severityFilter, selectedAlertId);
  };

  const handleSeverityFilterChange = (val: 'all' | AlertSeverity) => {
    setSeverityFilter(val);
    updateUrlFilters(patientFilter, statusFilter, val, selectedAlertId);
  };

  const handleSelectAlert = (alert: PatientAlert) => {
    setSelectedAlertId(alert.alertId);
    setActionError(null);
    setActionSuccess(null);
    updateUrlFilters(patientFilter, statusFilter, severityFilter, alert.alertId);
  };

  const handleCloseDrawer = () => {
    setSelectedAlertId(null);
    setActionError(null);
    setActionSuccess(null);
    updateUrlFilters(patientFilter, statusFilter, severityFilter, null);
  };

  const handleClearFilters = () => {
    setSearchQuery('');
    setStatusFilter('all');
    setSeverityFilter('all');
    setPatientFilter('all');
    setSelectedAlertId(null);
    setSearchParams({}, { replace: true });
  };

  const handleManualRefresh = async () => {
    setRefreshing(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      await loadAlertsData(isFixtureMode, patientFilter);
    } catch {
      // Handled in loadAlertsData
    } finally {
      setRefreshing(false);
    }
  };

  const handleToggleFixtureMode = () => {
    toggleFixtureMode();
    setLoading(true);
    setError(null);
    setActionError(null);
    setActionSuccess(null);
  };

  // Filtered Alerts List (Stable Memo)
  const filteredAlerts = useMemo(() => {
    return alerts.filter((alert) => {
      if (statusFilter !== 'all' && alert.status !== statusFilter) {
        return false;
      }
      if (severityFilter !== 'all' && alert.severity !== severityFilter) {
        return false;
      }
      if (patientFilter !== 'all' && alert.patientId !== patientFilter) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const p = patientMap.get(alert.patientId);
        const matchesReason = alert.reason?.toLowerCase().includes(q);
        const matchesAlertId = alert.alertId?.toLowerCase().includes(q);
        const matchesPatientId = alert.patientId?.toLowerCase().includes(q);
        const matchesPatientName = p?.name?.toLowerCase().includes(q);
        const matchesAssessment = alert.assessmentId?.toLowerCase().includes(q);
        const matchesNotes = alert.notes?.toLowerCase().includes(q);

        if (
          !matchesReason &&
          !matchesAlertId &&
          !matchesPatientId &&
          !matchesPatientName &&
          !matchesAssessment &&
          !matchesNotes
        ) {
          return false;
        }
      }
      return true;
    });
  }, [alerts, statusFilter, severityFilter, patientFilter, searchQuery, patientMap]);

  // Selected Alert for Details Drawer
  const selectedAlert = useMemo(() => {
    if (!selectedAlertId) return null;
    return alerts.find((a) => a.alertId === selectedAlertId) || null;
  }, [alerts, selectedAlertId]);

  // Derived KPI Counts
  const totalCount = alerts.length;
  const openCount = alerts.filter((a) => a.status === 'open').length;
  const criticalElevatedCount = alerts.filter(
    (a) => a.severity === 'critical' || a.severity === 'elevated'
  ).length;
  const resolvedCount = alerts.filter((a) => a.status === 'resolved').length;

  const isFilteringActive =
    searchQuery.trim() !== '' ||
    statusFilter !== 'all' ||
    severityFilter !== 'all' ||
    patientFilter !== 'all';

  // Action: Acknowledge Alert
  const handleAcknowledge = async (alert: PatientAlert) => {
    if (alert.status !== 'open') return;
    setActionLoading(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      const updated = await acknowledgeAlert(
        alert.alertId,
        { note: clinicianNote.trim() || undefined },
        isFixtureMode
      );
      setAlerts((prev) => prev.map((a) => (a.alertId === updated.alertId ? updated : a)));
      setActionSuccess(
        isFixtureMode
          ? `[SIMULATED ACTION] Alert ${alert.alertId} acknowledged in preview memory (Backend not connected — change will not persist to database).`
          : `Alert ${alert.alertId} successfully marked as acknowledged.`
      );
      setClinicianNote('');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to acknowledge alert.';
      setActionError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  // Action: Initiate Resolve Dialog
  const handleInitiateResolve = (alert: PatientAlert) => {
    if (alert.status === 'resolved') return;
    setAlertToResolve(alert);
    setResolveDialogOpen(true);
  };

  // Action: Confirm Resolve
  const handleConfirmResolve = async () => {
    if (!alertToResolve) return;
    setActionLoading(true);
    setActionError(null);
    setActionSuccess(null);
    setResolveDialogOpen(false);

    try {
      const updated = await resolveAlert(
        alertToResolve.alertId,
        { note: clinicianNote.trim() || undefined },
        isFixtureMode
      );
      setAlerts((prev) => prev.map((a) => (a.alertId === updated.alertId ? updated : a)));
      setActionSuccess(
        isFixtureMode
          ? `[SIMULATED ACTION] Alert ${alertToResolve.alertId} resolved in preview memory (Backend not connected — change will not persist to database).`
          : `Alert ${alertToResolve.alertId} successfully marked as resolved.`
      );
      setClinicianNote('');
      setAlertToResolve(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to resolve alert.';
      setActionError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      {/* 1. Persistent Safety Warning */}
      <SimulatedDataBanner detail="Authorization boundary: Surveillance alerts are predefined simulated examples and physiological rules (ML model offline)." />

      {/* Fixture Mode Banner if active */}
      {isFixtureMode && (
        <div className={styles.fixtureNotice} role="alert">
          <div className={styles.fixtureText}>
            <span className={styles.fixtureTag}>Dev Fixture</span>
            <span>
              <strong>Development Fixture Mode Active:</strong> Viewing isolated Kaggle P101–P105 demonstration alerts. FastAPI backend at localhost:8000 is offline.
            </span>
          </div>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Switch to Live Gateway Mode
          </Button>
        </div>
      )}

      {/* 2. Page Header */}
      <header className={styles.headerSection}>
        <div className={styles.headerTopRow}>
          <div className={styles.headerTitleCol}>
            <h1 className={styles.title}>Alerts</h1>
            <p className={styles.subtitle}>
              Surveillance log, rule threshold crossings, and multivariate anomaly triage across assigned patients.
            </p>
          </div>

          <div className={styles.headerActions}>
            <div className={styles.refreshMeta}>
              <span className={styles.lastRefreshedLabel}>Last Successful Refresh</span>
              <span className={styles.lastRefreshedValue}>
                {lastRefreshed ? formatTimestamp(lastRefreshed) : 'Not refreshed'}
              </span>
            </div>

            <Button
              variant="secondary"
              size="sm"
              onClick={handleManualRefresh}
              disabled={loading || refreshing}
              className={styles.refreshBtn}
              aria-label="Refresh alerts surveillance feed"
            >
              <RefreshIcon size={14} className={refreshing ? styles.spinIcon : undefined} />
              <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Partial Feeds Error Notice if some patients failed */}
      {Object.keys(partialErrors).length > 0 && !isFixtureMode && (
        <div className={styles.partialErrorBanner} role="alert">
          <strong>Partial Telemetry Alert Feed Availability:</strong>
          <span>
            Alert queries for {Object.keys(partialErrors).length} patient(s) ({Object.keys(partialErrors).join(', ')}) could not be completed. Remaining assigned feeds are displayed below.
          </span>
        </div>
      )}

      {/* Main Error Banner if total fetch failed */}
      {error && !isFixtureMode && (
        <InlineError
          title="Surveillance Gateway Communication Failure"
          message={error}
          onRetry={() => {
            setLoading(true);
            loadAlertsData(false, patientFilter)
              .catch(() => {})
              .finally(() => setLoading(false));
          }}
        />
      )}

      {/* Development Fixture Switch Offer when offline */}
      {error && !isFixtureMode && (
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
            FastAPI surveillance endpoint is offline. Would you like to inspect isolated Kaggle P101–P105 development fixtures?
          </span>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Inspect with Development Fixtures
          </Button>
        </div>
      )}

      {/* 3. Four-Stat Surveillance KPI Bar */}
      <section className={styles.statsGrid} aria-label="Surveillance Summary Metrics">
        <div className={styles.statCard}>
          <span className={styles.statLabel}>Total Surveillance Alerts</span>
          <span className={styles.statValue}>{loading ? '—' : totalCount}</span>
          <span className={styles.statSubtext}>Across assigned cohort</span>
        </div>

        <div className={styles.statCard}>
          <span className={styles.statLabel}>Open / Awaiting Review</span>
          <span className={`${styles.statValue} ${openCount > 0 ? styles.statValueOpen : ''}`}>
            {loading ? '—' : openCount}
          </span>
          <span className={styles.statSubtext}>Requires clinical triage</span>
        </div>

        <div className={styles.statCard}>
          <span className={styles.statLabel}>Critical / Elevated Risk</span>
          <span
            className={`${styles.statValue} ${
              criticalElevatedCount > 0 ? styles.statValueCritical : ''
            }`}
          >
            {loading ? '—' : criticalElevatedCount}
          </span>
          <span className={styles.statSubtext}>High priority indicators</span>
        </div>

        <div className={styles.statCard}>
          <span className={styles.statLabel}>Resolved Alerts</span>
          <span className={`${styles.statValue} ${styles.statValueResolved}`}>
            {loading ? '—' : resolvedCount}
          </span>
          <span className={styles.statSubtext}>Completed workflows</span>
        </div>
      </section>

      {/* 4. Multi-Criteria Filter & Search Toolbar */}
      <section className={styles.filterBar} aria-label="Surveillance Filtering Controls">
        <div className={styles.filterControlsRow}>
          {/* Search Box */}
          <div className={styles.searchGroup}>
            <label htmlFor="alert-search" className={styles.filterLabel}>
              Search Reason or Reference
            </label>
            <div className={styles.searchInputWrapper}>
              <SearchIcon size={14} className={styles.searchIcon} />
              <input
                id="alert-search"
                type="text"
                className={styles.searchInput}
                placeholder="Search by reason, alert ID, patient name, assessment ID…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          {/* Patient Filter */}
          <div className={styles.filterSelectGroup}>
            <label htmlFor="patient-filter" className={styles.filterLabel}>
              Assigned Patient
            </label>
            <select
              id="patient-filter"
              className={styles.filterSelect}
              value={patientFilter}
              onChange={(e) => handlePatientFilterChange(e.target.value)}
            >
              <option value="all">All Assigned Patients</option>
              {patients.map((p) => (
                <option key={p.patientId} value={p.patientId}>
                  {p.name} ({p.patientId})
                </option>
              ))}
            </select>
          </div>

          {/* Severity Filter */}
          <div className={styles.filterSelectGroup}>
            <label htmlFor="severity-filter" className={styles.filterLabel}>
              Severity
            </label>
            <select
              id="severity-filter"
              className={styles.filterSelect}
              value={severityFilter}
              onChange={(e) => handleSeverityFilterChange(e.target.value as 'all' | AlertSeverity)}
            >
              <option value="all">All Severities</option>
              <option value="critical">Critical</option>
              <option value="elevated">Elevated</option>
              <option value="advisory">Advisory</option>
              <option value="info">Informational</option>
            </select>
          </div>

          {/* Status Filter */}
          <div className={styles.filterSelectGroup}>
            <label htmlFor="status-filter" className={styles.filterLabel}>
              Status
            </label>
            <select
              id="status-filter"
              className={styles.filterSelect}
              value={statusFilter}
              onChange={(e) => handleStatusFilterChange(e.target.value as 'all' | AlertStatus)}
            >
              <option value="all">All Statuses</option>
              <option value="open">Open (Unacknowledged)</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>

          {/* Clear Filters Button */}
          {isFilteringActive && (
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleClearFilters}
                className={styles.clearFiltersBtn}
              >
                Clear Filters
              </Button>
            </div>
          )}
        </div>

        {/* Results Bar */}
        <div className={styles.resultsBar}>
          <div>
            Showing <span className={styles.resultCount}>{filteredAlerts.length}</span> of{' '}
            <span className={styles.resultCount}>{totalCount}</span> surveillance alerts
          </div>

          {isFilteringActive && (
            <div className={styles.activeFiltersTags}>
              {searchQuery && (
                <span className={styles.filterBadge}>Search: &ldquo;{searchQuery}&rdquo;</span>
              )}
              {patientFilter !== 'all' && (
                <span className={styles.filterBadge}>Patient: {patientFilter}</span>
              )}
              {severityFilter !== 'all' && (
                <span className={styles.filterBadge}>Severity: {severityFilter}</span>
              )}
              {statusFilter !== 'all' && (
                <span className={styles.filterBadge}>Status: {statusFilter}</span>
              )}
            </div>
          )}
        </div>
      </section>

      {/* 5. Main Split View: Alerts List on Left, Detail Drawer on Right */}
      {loading ? (
        <div style={{ padding: '64px 0', textAlign: 'center' }}>
          <LoadingIndicator label="Querying surveillance alerts across assigned patients…" />
        </div>
      ) : totalCount === 0 && !error ? (
        <div className={styles.tableCard}>
          <EmptyState
            preset="no_alerts"
            title="No Surveillance Alerts Recorded"
            description="All assigned patient telemetry feeds are currently operating within physiological baselines. No rule crossings or anomaly patterns detected."
          />
        </div>
      ) : filteredAlerts.length === 0 ? (
        <div className={styles.tableCard}>
          <EmptyState
            preset="custom"
            title="No Alerts Match Filter Criteria"
            description="No surveillance records match the active search query, patient, severity, or status filters."
            actionLabel="Reset All Filters"
            onAction={handleClearFilters}
          />
        </div>
      ) : (
        <div
          className={`${styles.contentSplit} ${
            selectedAlert ? styles.contentSplitWithDrawer : ''
          }`}
        >
          {/* Alerts Table / List Card */}
          <div className={styles.tableCard}>
            <div className={styles.tableWrapper}>
              <table className={styles.table} aria-label="Surveillance Alerts Log">
                <thead>
                  <tr>
                    <th scope="col">Severity</th>
                    <th scope="col">Patient</th>
                    <th scope="col">Alert Reason &amp; Assessment</th>
                    <th scope="col">Status</th>
                    <th scope="col">Detected</th>
                    <th scope="col">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAlerts.map((alert) => {
                    const p = patientMap.get(alert.patientId);
                    const isSelected = selectedAlertId === alert.alertId;
                    const rowSeverityClass =
                      alert.severity === 'critical'
                        ? styles.alertRowCritical
                        : alert.severity === 'elevated'
                        ? styles.alertRowElevated
                        : alert.severity === 'advisory'
                        ? styles.alertRowAdvisory
                        : styles.alertRowInfo;

                    return (
                      <tr
                        key={alert.alertId}
                        onClick={() => handleSelectAlert(alert)}
                        className={`${rowSeverityClass} ${
                          isSelected ? styles.alertRowSelected : ''
                        }`}
                        tabIndex={0}
                        role="button"
                        aria-label={`Open alert ${alert.alertId} for ${p?.name || alert.patientId}`}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            handleSelectAlert(alert);
                          }
                        }}
                      >
                        <td>
                          <StatusBadge variant={alert.severity} />
                        </td>

                        <td>
                          <div className={styles.patientCol}>
                            <Link
                              to={`/patients/${encodeURIComponent(alert.patientId)}`}
                              className={styles.patientNameLink}
                              onClick={(e) => e.stopPropagation()}
                            >
                              {p?.name || `Patient ${alert.patientId}`}
                            </Link>
                            <span className={styles.monoTag}>ID: {alert.patientId}</span>
                          </div>
                        </td>

                        <td>
                          <div className={styles.reasonCell}>
                            <span className={styles.reasonText}>{alert.reason}</span>
                            {alert.assessmentId && (
                              <span className={styles.assessmentTag}>
                                Ref: {alert.assessmentId}
                              </span>
                            )}
                          </div>
                        </td>

                        <td>
                          <StatusBadge variant={alert.status} />
                        </td>

                        <td className={styles.timeCol}>
                          {formatTimestamp(alert.createdAt)}
                        </td>

                        <td>
                          <div className={styles.actionsCol} onClick={(e) => e.stopPropagation()}>
                            <Button
                              variant="secondary"
                              size="sm"
                              className={styles.actionBtnSmall}
                              onClick={() => handleSelectAlert(alert)}
                            >
                              Review &rarr;
                            </Button>

                            {alert.status === 'open' && (
                              <Button
                                variant="secondary"
                                size="sm"
                                className={styles.actionBtnSmall}
                                onClick={() => handleAcknowledge(alert)}
                                disabled={actionLoading}
                                title="Acknowledge this alert"
                              >
                                <CheckIcon size={12} />
                                <span>Ack</span>
                              </Button>
                            )}

                            {alert.status !== 'resolved' && (
                              <Button
                                variant="secondary"
                                size="sm"
                                className={styles.actionBtnSmall}
                                onClick={() => handleInitiateResolve(alert)}
                                disabled={actionLoading}
                                title="Resolve this alert"
                              >
                                <CheckCircleIcon size={12} />
                                <span>Resolve</span>
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile Stacked Card View */}
            <div className={styles.mobileCards}>
              {filteredAlerts.map((alert) => {
                const p = patientMap.get(alert.patientId);
                const isSelected = selectedAlertId === alert.alertId;

                return (
                  <div
                    key={alert.alertId}
                    className={`${styles.mobileCard} ${
                      isSelected ? styles.alertRowSelected : ''
                    }`}
                    onClick={() => handleSelectAlert(alert)}
                  >
                    <div className={styles.mobileCardHeader}>
                      <StatusBadge variant={alert.severity} />
                      <StatusBadge variant={alert.status} />
                    </div>

                    <div className={styles.patientCol}>
                      <Link
                        to={`/patients/${encodeURIComponent(alert.patientId)}`}
                        className={styles.patientNameLink}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {p?.name || `Patient ${alert.patientId}`}
                      </Link>
                      <span className={styles.monoTag}>ID: {alert.patientId}</span>
                    </div>

                    <div className={styles.mobileCardBody}>
                      <p style={{ margin: 0 }}>{alert.reason}</p>
                      {alert.assessmentId && (
                        <span className={styles.assessmentTag} style={{ marginTop: '4px' }}>
                          Ref: {alert.assessmentId}
                        </span>
                      )}
                    </div>

                    <div className={styles.mobileCardFooter}>
                      <span>{formatTimestamp(alert.createdAt)}</span>
                      <Button
                        variant="secondary"
                        size="sm"
                        className={styles.actionBtnSmall}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSelectAlert(alert);
                        }}
                      >
                        Review Alert &rarr;
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 6. Alert Detail Drawer / Panel on the Right */}
          {selectedAlert && (
            <aside
              className={styles.detailDrawer}
              aria-label={`Detail panel for alert ${selectedAlert.alertId}`}
            >
              {/* Drawer Header */}
              <div className={styles.drawerHeader}>
                <div className={styles.drawerTitleGroup}>
                  <h2 className={styles.drawerTitle}>Alert Details</h2>
                  <span className={styles.monoTag}>ID: {selectedAlert.alertId}</span>
                </div>
                <button
                  type="button"
                  className={styles.closeDrawerBtn}
                  onClick={handleCloseDrawer}
                  aria-label="Close detail panel"
                >
                  <CloseIcon size={16} />
                </button>
              </div>

              {/* Status and Severity Badges */}
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <StatusBadge variant={selectedAlert.severity} />
                <StatusBadge variant={selectedAlert.status} />
              </div>

              {/* Feedback Notifications */}
              {actionSuccess && (
                <div className={`${styles.feedbackBanner} ${styles.feedbackSuccess}`} role="status">
                  {actionSuccess}
                </div>
              )}
              {actionError && (
                <div className={`${styles.feedbackBanner} ${styles.feedbackError}`} role="alert">
                  {actionError}
                </div>
              )}

              {/* Patient Identity Section */}
              <div className={styles.drawerSection}>
                <h3 className={styles.drawerSectionTitle}>Subject Identity</h3>
                <div className={styles.drawerFieldRow}>
                  <span className={styles.drawerFieldLabel}>Patient:</span>
                  <Link
                    to={`/patients/${encodeURIComponent(selectedAlert.patientId)}`}
                    className={styles.patientNameLink}
                  >
                    {patientMap.get(selectedAlert.patientId)?.name || selectedAlert.patientId} &rarr;
                  </Link>
                </div>
                <div className={styles.drawerFieldRow}>
                  <span className={styles.drawerFieldLabel}>Patient ID:</span>
                  <span className={styles.monoTag}>{selectedAlert.patientId}</span>
                </div>
              </div>

              {/* Trigger Reason */}
              <div className={styles.drawerSection}>
                <h3 className={styles.drawerSectionTitle}>Surveillance Finding</h3>
                <div className={styles.drawerReasonBox}>
                  {selectedAlert.reason}
                </div>
                {selectedAlert.assessmentId && (
                  <div className={styles.drawerFieldRow}>
                    <span className={styles.drawerFieldLabel}>Model / Rule Assessment:</span>
                    <span className={styles.assessmentTag}>{selectedAlert.assessmentId}</span>
                  </div>
                )}
              </div>

              {/* Audit / Timeline History */}
              <div className={styles.drawerSection}>
                <h3 className={styles.drawerSectionTitle}>Surveillance Timeline</h3>
                <div className={styles.timelineList}>
                  <div className={styles.timelineItem}>
                    <span className={styles.timelineTitle}>Alert Detected &amp; Logged</span>
                    <span className={styles.timelineTime}>
                      {formatTimestamp(selectedAlert.createdAt)}
                    </span>
                  </div>

                  {selectedAlert.acknowledgedAt && (
                    <div className={styles.timelineItem}>
                      <span className={styles.timelineTitle}>
                        Acknowledged by {selectedAlert.acknowledgedBy || 'Assigned Clinician'}
                      </span>
                      <span className={styles.timelineTime}>
                        {formatTimestamp(selectedAlert.acknowledgedAt)}
                      </span>
                    </div>
                  )}

                  {selectedAlert.resolvedAt && (
                    <div className={styles.timelineItem}>
                      <span className={styles.timelineTitle}>Alert Resolved</span>
                      <span className={styles.timelineTime}>
                        {formatTimestamp(selectedAlert.resolvedAt)}
                      </span>
                    </div>
                  )}

                  {selectedAlert.notes && (
                    <div className={styles.timelineNote}>
                      <strong>Note:</strong> {selectedAlert.notes}
                    </div>
                  )}
                </div>
              </div>

              {/* Clinical Action Form & Controls */}
              <div className={styles.drawerActionSection}>
                <h3 className={styles.drawerSectionTitle}>Clinician Action</h3>

                {selectedAlert.status !== 'resolved' ? (
                  <>
                    <div className={styles.noteInputGroup}>
                      <label htmlFor="clinician-note-input" className={styles.filterLabel}>
                        Clinical Note / Triage Action (Optional)
                      </label>
                      <textarea
                        id="clinician-note-input"
                        className={styles.noteTextarea}
                        placeholder="Document observations, rationale, or instructions before acknowledging/resolving…"
                        value={clinicianNote}
                        onChange={(e) => setClinicianNote(e.target.value)}
                        disabled={actionLoading}
                      />
                    </div>

                    <div className={styles.drawerActionButtons}>
                      {selectedAlert.status === 'open' && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleAcknowledge(selectedAlert)}
                          disabled={actionLoading}
                        >
                          <CheckIcon size={14} />
                          <span>{actionLoading ? 'Acknowledging…' : 'Acknowledge Alert'}</span>
                        </Button>
                      )}

                      <Button
                        variant={selectedAlert.severity === 'critical' ? 'destructive' : 'primary'}
                        size="sm"
                        onClick={() => handleInitiateResolve(selectedAlert)}
                        disabled={actionLoading}
                      >
                        <CheckCircleIcon size={14} />
                        <span>{actionLoading ? 'Resolving…' : 'Resolve Alert'}</span>
                      </Button>
                    </div>
                  </>
                ) : (
                  <div
                    style={{
                      fontSize: '12px',
                      color: 'var(--color-success-base)',
                      backgroundColor: 'var(--color-success-bg)',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-xs)',
                      border: '1px solid var(--color-success-border)',
                    }}
                  >
                    ✓ This alert is marked as <strong>Resolved</strong>. The surveillance lifecycle for this event is complete.
                  </div>
                )}
              </div>
            </aside>
          )}
        </div>
      )}

      {/* 7. Confirmation Dialog for Resolve Action */}
      <ConfirmationDialog
        isOpen={resolveDialogOpen}
        title="Confirm Alert Resolution"
        message={`Are you sure you want to mark alert "${alertToResolve?.alertId}" for patient "${alertToResolve?.patientId}" as resolved? This records the resolution timestamp and closes the surveillance workflow for this event.`}
        confirmLabel="Confirm Resolution"
        cancelLabel="Cancel"
        isDestructive={alertToResolve?.severity === 'critical'}
        onConfirm={handleConfirmResolve}
        onCancel={() => {
          setResolveDialogOpen(false);
          setAlertToResolve(null);
        }}
      />
    </div>
  );
};
