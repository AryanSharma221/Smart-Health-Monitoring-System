import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  fetchPatientRows,
  type DashboardPatientRow,
} from '../api';
import { useDevMode } from '../hooks';
import { formatVitalValue, formatTimestamp } from '../utils';
import {
  SimulatedDataBanner,
  StatusBadge,
  Button,
  LoadingIndicator,
  InlineError,
  EmptyState,
  RefreshIcon,
  SearchIcon,
  CloseIcon,
  FilterIcon,
} from '../components/ui';
import styles from './PatientsPage.module.css';

type FreshnessFilterOption = 'all' | 'fresh' | 'stale' | 'unavailable';
type AlertFilterOption = 'all' | 'open' | 'none';

export const PatientsPage: React.FC = () => {
  const { isFixtureMode, toggleFixtureMode } = useDevMode();

  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [patientRows, setPatientRows] = useState<DashboardPatientRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);

  // Search & Filter State
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [freshnessFilter, setFreshnessFilter] = useState<FreshnessFilterOption>('all');
  const [alertFilter, setAlertFilter] = useState<AlertFilterOption>('all');

  const loadData = useCallback(async (useFixtures: boolean) => {
    return fetchPatientRows(useFixtures);
  }, []);

  useEffect(() => {
    let isCancelled = false;

    async function init() {
      setError(null);
      try {
        const rows = await loadData(isFixtureMode);
        if (!isCancelled) {
          setPatientRows(rows);
          setLastRefreshed(new Date().toISOString());
          setLoading(false);
        }
      } catch (err: unknown) {
        if (!isCancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to query patient directory from FastAPI backend.';
          setError(msg);
          setLoading(false);
        }
      }
    }

    init();

    return () => {
      isCancelled = true;
    };
  }, [loadData, isFixtureMode]);

  const handleManualRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const rows = await loadData(isFixtureMode);
      setPatientRows(rows);
      setLastRefreshed(new Date().toISOString());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query patient directory from FastAPI backend.';
      setError(msg);
    } finally {
      setRefreshing(false);
    }
  };

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    loadData(isFixtureMode)
      .then((rows) => {
        setPatientRows(rows);
        setLastRefreshed(new Date().toISOString());
        setLoading(false);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : 'Failed to query patient directory from FastAPI backend.';
        setError(msg);
        setLoading(false);
      });
  };

  const handleToggleFixtureMode = () => {
    toggleFixtureMode();
    setLoading(true);
    setError(null);
  };

  const handleClearFilters = () => {
    setSearchQuery('');
    setFreshnessFilter('all');
    setAlertFilter('all');
  };

  const isFiltered =
    searchQuery.trim().length > 0 || freshnessFilter !== 'all' || alertFilter !== 'all';

  // Filtered Patient Rows computation
  const filteredPatients = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();

    return patientRows.filter((row) => {
      // 1. Text Search matching name, patientId, or sourcePatientId
      const matchesSearch =
        !q ||
        row.patient.name.toLowerCase().includes(q) ||
        row.patient.patientId.toLowerCase().includes(q) ||
        (row.patient.sourcePatientId && row.patient.sourcePatientId.toLowerCase().includes(q));

      // 2. Freshness filter
      const matchesFreshness =
        freshnessFilter === 'all' || row.feedFreshness === freshnessFilter;

      // 3. Alert filter
      let matchesAlert = true;
      if (alertFilter === 'open') {
        matchesAlert = row.openAlertsCount > 0;
      } else if (alertFilter === 'none') {
        // Exclude patients whose alert query failed, to avoid false negative
        matchesAlert = !row.alertsError && row.openAlertsCount === 0;
      }

      return matchesSearch && matchesFreshness && matchesAlert;
    });
  }, [patientRows, searchQuery, freshnessFilter, alertFilter]);

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

      {/* 2. Page Header & Brief Context */}
      <header className={styles.headerSection}>
        <div className={styles.headerTopRow}>
          <div className={styles.headerTitleCol}>
            <h1 className={styles.title}>Patient Directory</h1>
            <p className={styles.subtitle}>
              Search, filter, and inspect clinical telemetry streams for patients assigned to your clinician account.
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
              aria-label="Refresh patient directory"
            >
              <RefreshIcon size={14} className={refreshing ? styles.spinIcon : undefined} />
              <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Main Error Banner if live query failed */}
      {error && !isFixtureMode && (
        <InlineError
          title="FastAPI Gateway Communication Failure"
          message={error}
          onRetry={handleRetry}
        />
      )}

      {/* Development Fixture Affordance when live query is down */}
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
            FastAPI service is offline. Would you like to inspect the patient directory layout using isolated Kaggle P101–P105 demonstration fixtures?
          </span>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Inspect with Development Fixtures
          </Button>
        </div>
      )}

      {/* 3. Search and Filter Controls Toolbar */}
      <section className={styles.filterToolbar} aria-label="Patient search and filter controls">
        <div className={styles.filterControlsRow}>
          {/* Search Input */}
          <div className={styles.searchWrapper}>
            <label htmlFor="patient-search-input" className={styles.searchLabel}>
              Search Patients
            </label>
            <div className={styles.searchInputWrapper}>
              <span className={styles.searchIcon} aria-hidden="true">
                <SearchIcon size={16} />
              </span>
              <input
                id="patient-search-input"
                type="text"
                className={styles.searchInput}
                placeholder="Search by name, ID (e.g. P101)..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                autoComplete="off"
                aria-label="Search patients by name or ID"
              />
              {searchQuery && (
                <button
                  type="button"
                  className={styles.clearSearchBtn}
                  onClick={() => setSearchQuery('')}
                  aria-label="Clear search query"
                >
                  <CloseIcon size={14} />
                </button>
              )}
            </div>
          </div>

          {/* Freshness Filter */}
          <div className={styles.filterGroup}>
            <label htmlFor="freshness-filter-select" className={styles.filterLabel}>
              Feed Freshness
            </label>
            <select
              id="freshness-filter-select"
              className={styles.filterSelect}
              value={freshnessFilter}
              onChange={(e) => setFreshnessFilter(e.target.value as FreshnessFilterOption)}
              aria-label="Filter by telemetry freshness"
            >
              <option value="all">All Freshness States</option>
              <option value="fresh">Fresh / Live (&le;60s)</option>
              <option value="stale">Stale (&gt;60s)</option>
              <option value="unavailable">Unavailable / No Feed</option>
            </select>
          </div>

          {/* Alert Status Filter */}
          <div className={styles.filterGroup}>
            <label htmlFor="alert-filter-select" className={styles.filterLabel}>
              Alert Status
            </label>
            <select
              id="alert-filter-select"
              className={styles.filterSelect}
              value={alertFilter}
              onChange={(e) => setAlertFilter(e.target.value as AlertFilterOption)}
              aria-label="Filter by alert status"
            >
              <option value="all">All Alert Statuses</option>
              <option value="open">Has Open Alerts</option>
              <option value="none">No Open Alerts</option>
            </select>
          </div>

          {/* Clear Filters Button */}
          {isFiltered && (
            <div className={styles.clearFiltersCol}>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleClearFilters}
                className={styles.clearAllBtn}
              >
                Clear Filters
              </Button>
            </div>
          )}
        </div>

        {/* 4. Results Count and Filter Status Bar */}
        {!loading && !error && patientRows.length > 0 && (
          <div className={styles.resultsBar}>
            <div>
              Showing <span className={styles.resultCount}>{filteredPatients.length}</span> of{' '}
              <span className={styles.resultCount}>{patientRows.length}</span> assigned patients
              {isFiltered ? ' (filtered)' : ''}
            </div>

            {isFiltered && (
              <div className={styles.activeFiltersTags}>
                <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
                  <FilterIcon size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />
                  Active filters:
                </span>
                {searchQuery.trim() && (
                  <span className={styles.filterBadge}>Query: &ldquo;{searchQuery.trim()}&rdquo;</span>
                )}
                {freshnessFilter !== 'all' && (
                  <span className={styles.filterBadge}>Freshness: {freshnessFilter}</span>
                )}
                {alertFilter !== 'all' && (
                  <span className={styles.filterBadge}>
                    Alerts: {alertFilter === 'open' ? 'Open Alerts' : 'No Open Alerts'}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      {/* 5. Patient Directory Content */}
      <section className={styles.directoryCard} aria-label="Assigned Patient Directory Table">
        {loading ? (
          <div style={{ padding: '32px 0' }}>
            <LoadingIndicator label="Querying patient directory from FastAPI gateway…" />
          </div>
        ) : error && !isFixtureMode ? (
          <EmptyState
            preset="failed_request"
            title="Unable to Retrieve Patient Directory"
            description="The workstation cannot communicate with the FastAPI backend gateway. Ensure the service is active on port 8000."
            actionLabel="Retry Connection"
            onAction={handleRetry}
          />
        ) : patientRows.length === 0 ? (
          <EmptyState
            preset="no_patients"
            title="No Patients Assigned"
            description="No patient records are currently assigned to your clinician account in MySQL assignments. Patient assignment is managed server-side."
          />
        ) : filteredPatients.length === 0 ? (
          <EmptyState
            preset="custom"
            title="No Matching Patients"
            description="No assigned patients match your current search query and filter selection. Try adjusting or clearing your filters."
            actionLabel="Clear Filters"
            onAction={handleClearFilters}
          />
        ) : (
          <>
            {/* Desktop Table View */}
            <div className={styles.tableResponsive}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Patient Identity</th>
                    <th>Latest Available Readings</th>
                    <th>Feed Status</th>
                    <th>Last Measured Time</th>
                    <th>Alert Status</th>
                    <th className={styles.actionCol}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPatients.map((row) => {
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
                          <StatusBadge variant={row.feedFreshness} />
                        </td>

                        <td className={styles.timestampCol}>
                          {row.mostRecentMeasurementTime
                            ? formatTimestamp(row.mostRecentMeasurementTime)
                            : '— (Unavailable)'}
                        </td>

                        <td>
                          {row.alertsError ? (
                            <StatusBadge variant="unavailable" label="Alerts Unavailable" />
                          ) : row.openAlertsCount > 0 ? (
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
                            Inspect Telemetry &rarr;
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
              {filteredPatients.map((row) => (
                <div key={row.patient.patientId} className={styles.mobileCard}>
                  <div className={styles.mobileCardHeader}>
                    <div className={styles.patientIdentity}>
                      <span className={styles.patientName}>{row.patient.name}</span>
                      <span className={styles.patientIdTag}>ID: {row.patient.patientId}</span>
                    </div>
                    <StatusBadge variant={row.feedFreshness} />
                  </div>

                  <div className={styles.vitalsRow}>
                    {row.latestVitals.length === 0 ? (
                      <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
                        No measurements recorded
                      </span>
                    ) : (
                      row.latestVitals.map((v) => (
                        <span key={v.metricCode} className={styles.vitalPill}>
                          <span className={styles.vitalPillLabel}>{v.label}:</span>
                          <span className={styles.vitalPillValue}>
                            {formatVitalValue(v.value, v.unit)}
                          </span>
                        </span>
                      ))
                    )}
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      fontSize: '11px',
                      color: 'var(--color-text-muted)',
                    }}
                  >
                    <span>Measured: {formatTimestamp(row.mostRecentMeasurementTime)}</span>
                    {row.alertsError ? (
                      <StatusBadge variant="unavailable" label="Alerts Unavailable" />
                    ) : row.openAlertsCount > 0 ? (
                      <StatusBadge variant="elevated" label={`${row.openAlertsCount} Alert`} />
                    ) : (
                      <StatusBadge variant="normal_like" label="No Alerts" />
                    )}
                  </div>

                  <div>
                    <Link
                      to={`/patients/${encodeURIComponent(row.patient.patientId)}`}
                      className={styles.viewDetailsBtn}
                      style={{ display: 'block', textAlign: 'center' }}
                    >
                      Inspect Telemetry &rarr;
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
};
