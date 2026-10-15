/**
 * SMART HEALTH MONITORING SYSTEM — DEMO MODE SQL WORKBENCH FRONTEND
 *
 * Provides an interactive, terminal-style SQL execution environment exclusively in Demo Mode:
 * 1. Restricted strictly to Demo Mode (isDemoMode / isFixtureMode). Locked when in Real-Time Mode.
 * 2. Real SQL execution against smart_health_local.db (SQLite 3).
 * 3. Provenance guarantee: Inserted readings are enforced as source='self_added' by the backend.
 * 4. ML Assessment & Rule Alert feedback displayed directly in results.
 * 5. Command history tracking with one-click editor population.
 * 6. Keyboard shortcut: Ctrl+Enter / Cmd+Enter executes queries.
 * 7. Confirmation modal before destructive UPDATE or DELETE mutations.
 */

import React, { useState, useCallback, useMemo } from 'react';
import {
  workbenchService,
  type SQLWorkbenchExecuteResponse,
  type CommandHistoryItem,
} from '../../api';
import styles from './DemoSQLWorkbench.module.css';

export interface DemoSQLWorkbenchProps {
  isDemoMode: boolean;
  onRefreshHistory?: () => void;
  targetPatientId?: string;
  onSwitchToDemoMode?: () => void;
}

import { EXAMPLE_QUERIES } from './demoSqlExamples';


export const DemoSQLWorkbench: React.FC<DemoSQLWorkbenchProps> = ({
  isDemoMode,
  onRefreshHistory,
  targetPatientId = 'P101',
  onSwitchToDemoMode,
}) => {
  const [sqlText, setSqlText] = useState<string>(EXAMPLE_QUERIES[0].sql);
  const [selectedExampleId, setSelectedExampleId] = useState<string>(EXAMPLE_QUERIES[0].id);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [result, setResult] = useState<SQLWorkbenchExecuteResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<string | null>(null);
  const [history, setHistory] = useState<CommandHistoryItem[]>([]);

  // Selected example metadata
  const currentExample = useMemo(
    () => EXAMPLE_QUERIES.find((q) => q.id === selectedExampleId),
    [selectedExampleId]
  );

  // Line numbers calculation
  const lineCount = useMemo(() => {
    return Math.max(1, sqlText.split('\n').length);
  }, [sqlText]);

  // Select example handler
  const handleSelectExample = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    setSelectedExampleId(id);
    const ex = EXAMPLE_QUERIES.find((q) => q.id === id);
    if (ex) {
      setSqlText(ex.sql);
      setErrorMsg(null);
    }
  };

  // Raw execution call
  const executeQueryInternal = useCallback(async (queryToRun: string) => {
    if (!isDemoMode) {
      setErrorMsg('Execution blocked: SQL Workbench is restricted exclusively to Demo Mode.');
      return;
    }

    if (!queryToRun.trim()) {
      setErrorMsg('Please enter a SQL statement to execute.');
      return;
    }

    setIsRunning(true);
    setErrorMsg(null);
    setResult(null);

    const startTime = performance.now();

    try {
      const resp = await workbenchService.executeQuery({
        sql: queryToRun,
        is_demo_mode: isDemoMode,
        patient_id: targetPatientId,
      });

      const elapsed = Math.round(performance.now() - startTime);

      setResult(resp);

      // Add to session history
      const historyItem: CommandHistoryItem = {
        id: `cmd_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        sql: queryToRun,
        status: resp.status,
        statementType: resp.statement_type,
        timestamp: new Date().toLocaleTimeString(),
        executionTimeMs: resp.execution_time_ms || elapsed,
        rowsAffected: resp.rows_affected,
        rowCount: resp.row_count,
        lastInsertedId: resp.last_inserted_id,
        errorMessage: null,
      };

      setHistory((prev) => [historyItem, ...prev.slice(0, 19)]);

      // Auto-trigger history refresh if it was an insert/update/delete
      if (['INSERT', 'UPDATE', 'DELETE'].includes(resp.statement_type) && onRefreshHistory) {
        onRefreshHistory();
      }
    } catch (err: any) {
      const elapsed = Math.round(performance.now() - startTime);
      const msg = err?.message || (typeof err === 'string' ? err : 'SQL execution failed.');
      setErrorMsg(msg);

      // Add failed attempt to history
      const historyItem: CommandHistoryItem = {
        id: `cmd_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        sql: queryToRun,
        status: 'error',
        statementType: 'ERROR',
        timestamp: new Date().toLocaleTimeString(),
        executionTimeMs: elapsed,
        errorMessage: msg,
      };
      setHistory((prev) => [historyItem, ...prev.slice(0, 19)]);
    } finally {
      setIsRunning(false);
    }
  }, [isDemoMode, targetPatientId, onRefreshHistory]);

  // Execute button click with safety modal check
  const handleExecute = () => {
    const trimmed = sqlText.trim().toUpperCase();
    if (trimmed.startsWith('DELETE') || trimmed.startsWith('UPDATE')) {
      setPendingConfirmation(sqlText);
    } else {
      void executeQueryInternal(sqlText);
    }
  };

  // Keyboard shortcut listener (Ctrl+Enter / Cmd+Enter)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (!isRunning && isDemoMode) {
        handleExecute();
      }
    }
  };

  // Load previous command from history
  const handleSelectHistoryItem = (item: CommandHistoryItem) => {
    setSqlText(item.sql);
    setErrorMsg(null);
  };

  return (
    <section className={styles.workbenchContainer} aria-label="Demo SQL Workbench Terminal">
      {/* 1. Header */}
      <div className={styles.workbenchHeader}>
        <div className={styles.titleGroup}>
          <h2 className={styles.workbenchTitle}>
            <span>⚡ Demo SQL Workbench</span>
          </h2>
          <p className={styles.workbenchSubtitle}>
            Interactive SQLite terminal for querying, creating, and modifying demo health readings.
          </p>
        </div>

        <div className={styles.modeBadgeGroup}>
          {isDemoMode ? (
            <span className={styles.modeBadgeDemo}>
              <span className={styles.dotLive} aria-hidden="true" />
              DEMO MODE — SQLite Sandbox Active
            </span>
          ) : (
            <span className={styles.modeBadgeRealtime}>
              <span className={styles.dotLock} aria-hidden="true" />
              REAL-TIME MODE ACTIVE — WORKBENCH LOCKED
            </span>
          )}
        </div>
      </div>

      {/* 2. Real-Time Mode Locked Warning */}
      {!isDemoMode && (
        <div className={styles.lockedBanner} role="alert">
          <div className={styles.lockedTextGroup}>
            <h3 className={styles.lockedTitle}>Workbench Locked During Real-Time Telemetry Streaming</h3>
            <p className={styles.lockedDescription}>
              The SQL Workbench is restricted exclusively to Demo Mode to prevent telemetry collisions and protect baseline data. Switch to Demo Mode to execute queries.
            </p>
          </div>
          {onSwitchToDemoMode && (
            <button
              type="button"
              className={styles.executeButton}
              onClick={onSwitchToDemoMode}
              style={{ backgroundColor: '#b45309' }}
            >
              Switch to Demo Mode
            </button>
          )}
        </div>
      )}

      {/* 3. Server Provenance Assurance Note */}
      <div className={styles.provenanceNote}>
        <span>
          🛡️ <strong>Server-Side Provenance Assurance:</strong> All newly inserted vital signs are strictly categorized as <code className={styles.provenanceCode}>source='self_added'</code> and <code className={styles.provenanceCode}>is_simulated=false</code> by backend logic. Kaggle baseline cohorts (<code className={styles.provenanceCode}>P001–P005</code>) are read-only.
        </span>
      </div>

      {/* 4. Example Query Dropdown */}
      <div className={styles.examplesBar}>
        <label htmlFor="sql-example-select" className={styles.examplesLabel}>
          Load Example Query:
        </label>
        <select
          id="sql-example-select"
          className={styles.examplesSelect}
          value={selectedExampleId}
          onChange={handleSelectExample}
          disabled={!isDemoMode || isRunning}
        >
          {EXAMPLE_QUERIES.map((q) => (
            <option key={q.id} value={q.id}>
              {q.name}
            </option>
          ))}
        </select>
        {currentExample && (
          <span style={{ fontSize: '11px', color: '#64748b', fontStyle: 'italic' }}>
            {currentExample.description}
          </span>
        )}
      </div>

      {/* 5. Terminal SQL Editor Window */}
      <div className={styles.terminalWindow}>
        <div className={styles.terminalHeader}>
          <div className={styles.terminalDots}>
            <span className={styles.dotRed} />
            <span className={styles.dotYellow} />
            <span className={styles.dotGreen} />
          </div>
          <span className={styles.terminalTitle}>DEMO SQL WORKBENCH TERMINAL</span>
          <span className={styles.terminalDbTarget}>smart_health_local.db (SQLite 3)</span>
        </div>

        <div className={styles.terminalBody}>
          <div className={styles.terminalGutter} aria-hidden="true">
            {Array.from({ length: lineCount }).map((_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>
          <textarea
            className={styles.terminalTextarea}
            value={sqlText}
            onChange={(e) => setSqlText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!isDemoMode || isRunning}
            placeholder="Enter SQL statement here (e.g. SELECT * FROM vitals_readings LIMIT 10;)..."
            spellCheck={false}
            autoCapitalize="off"
            autoComplete="off"
            aria-label="SQL Query Input Area"
          />
        </div>
      </div>

      {/* 6. Controls Bar */}
      <div className={styles.controlsBar}>
        <div className={styles.buttonGroupLeft}>
          <button
            type="button"
            className={styles.executeButton}
            onClick={handleExecute}
            disabled={!isDemoMode || isRunning || !sqlText.trim()}
          >
            {isRunning ? (
              <span>Executing Query…</span>
            ) : (
              <>
                <span>▶ Execute SQL</span>
                <span className={styles.shortcutHint}>Ctrl+Enter</span>
              </>
            )}
          </button>

          <button
            type="button"
            className={styles.clearButton}
            onClick={() => {
              setSqlText('');
              setErrorMsg(null);
            }}
            disabled={isRunning || !sqlText}
          >
            Clear Editor
          </button>
        </div>

        {onRefreshHistory && (
          <button
            type="button"
            className={styles.clearButton}
            onClick={onRefreshHistory}
            title="Refresh patient feeds on dashboard"
          >
            🔄 Refresh Dashboard Feeds
          </button>
        )}
      </div>

      {/* 7. Destructive Mutation Confirmation Modal */}
      {pendingConfirmation && (
        <div className={styles.modalOverlay} role="dialog" aria-modal="true">
          <div className={styles.modalContent}>
            <h3 className={styles.modalTitle}>⚠️ Confirm Database Mutation</h3>
            <p className={styles.modalBody}>
              You are about to execute a destructive mutation statement (<strong>{pendingConfirmation.trim().split(' ')[0].toUpperCase()}</strong>).
              This will directly alter or remove records in the local demo database.
            </p>
            <div className={styles.modalSqlSnippet}>
              {pendingConfirmation}
            </div>
            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.clearButton}
                onClick={() => setPendingConfirmation(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.executeButton}
                style={{ backgroundColor: '#dc2626' }}
                onClick={() => {
                  const q = pendingConfirmation;
                  setPendingConfirmation(null);
                  void executeQueryInternal(q);
                }}
              >
                Proceed & Execute Mutation
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 8. Error Feedback Banner */}
      {errorMsg && (
        <div className={styles.errorBanner} role="alert">
          <span className={styles.errorTitle}>SQL Execution Error:</span>
          <span className={styles.errorMessage}>{errorMsg}</span>
        </div>
      )}

      {/* 9. ML Assessment & Rule Alert Feedback Card */}
      {result?.ml_assessment && (
        <div className={styles.mlAssessmentCard}>
          <div className={styles.mlCardHeader}>
            <span className={styles.mlTitle}>
              🧠 Machine Learning Telemetry Assessment
            </span>
            {result.ml_assessment.result === 'anomaly' ? (
              <span className={styles.mlResultAnomaly}>
                🚨 ANOMALY DETECTED (Score: {result.ml_assessment.anomaly_score?.toFixed(4)})
              </span>
            ) : result.ml_assessment.result === 'normal' ? (
              <span className={styles.mlResultNormal}>
                ✅ NORMAL OBSERVATION (Score: {result.ml_assessment.anomaly_score?.toFixed(4)})
              </span>
            ) : (
              <span className={styles.mlResultInconclusive}>
                ⚠️ INCONCLUSIVE (Missing Triad Features — No Values Fabricated)
              </span>
            )}
          </div>

          <div className={styles.mlGrid}>
            <div className={styles.mlMetricBox}>
              <span className={styles.mlMetricLabel}>Target Patient</span>
              <span className={styles.mlMetricValue}>{result.ml_assessment.patient_id || targetPatientId}</span>
            </div>
            <div className={styles.mlMetricBox}>
              <span className={styles.mlMetricLabel}>Discrete Event ID</span>
              <span className={styles.mlMetricValue}>{result.ml_assessment.event_id || '—'}</span>
            </div>
            <div className={styles.mlMetricBox}>
              <span className={styles.mlMetricLabel}>Provenance Source</span>
              <span className={styles.mlMetricValue} style={{ color: '#047857' }}>self_added (is_simulated: false)</span>
            </div>
            <div className={styles.mlMetricBox}>
              <span className={styles.mlMetricLabel}>Alert Generation</span>
              <span className={styles.mlMetricValue}>
                {result.ml_assessment.alert_created
                  ? `Triggered (${result.ml_assessment.alert_severity || 'HIGH'})`
                  : 'None Generated'}
              </span>
            </div>
          </div>

          <div style={{ fontSize: '12px', color: '#166534', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>{result.ml_assessment.message}</span>
            {onRefreshHistory && (
              <button
                type="button"
                className={styles.refreshHistoryButton}
                onClick={onRefreshHistory}
              >
                🔄 Refresh Demo History
              </button>
            )}
          </div>
        </div>
      )}

      {/* 10. Results Table & Metadata */}
      {result && (
        <div className={styles.resultsSection}>
          <div className={styles.resultsHeader}>
            <div className={styles.resultsMetaGroup}>
              <span className={result.status === 'success' ? styles.statusPillSuccess : styles.statusPillError}>
                {result.status.toUpperCase()}
              </span>
              <span className={styles.metaTag}>Type: {result.statement_type}</span>
              <span className={styles.metaTag}>Duration: {result.execution_time_ms} ms</span>
              {result.rows_affected !== null && result.rows_affected !== undefined && (
                <span className={styles.metaTag}>Rows Affected: {result.rows_affected}</span>
              )}
              {result.row_count !== null && result.row_count !== undefined && (
                <span className={styles.metaTag}>Rows Returned: {result.row_count}</span>
              )}
              {result.last_inserted_id && (
                <span className={styles.metaTag}>Inserted ID: #{result.last_inserted_id}</span>
              )}
            </div>
            {result.message && (
              <span style={{ fontSize: '11px', color: '#475569' }}>{result.message}</span>
            )}
          </div>

          {/* Tabular Output */}
          {result.columns && result.columns.length > 0 ? (
            <div className={styles.tableContainer}>
              <table className={styles.resultsTable}>
                <thead>
                  <tr>
                    {result.columns.map((col, idx) => (
                      <th key={idx}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows && result.rows.length > 0 ? (
                    result.rows.map((row, rIdx) => (
                      <tr key={rIdx}>
                        {row.map((cell, cIdx) => (
                          <td key={cIdx}>
                            {cell === null || cell === undefined ? (
                              <span className={styles.nullValue}>NULL</span>
                            ) : (
                              String(cell)
                            )}
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={result.columns.length} className={styles.emptyState}>
                        Query executed successfully, returning 0 rows.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : result.statement_type !== 'INSERT' && (
            <div className={styles.emptyState}>
              {result.message || `${result.statement_type} operation completed successfully.`}
            </div>
          )}
        </div>
      )}

      {/* 11. Command History Section */}
      {history.length > 0 && (
        <div className={styles.historySection}>
          <div className={styles.historyHeader}>
            <h3 className={styles.historyTitle}>📜 Command History (Current Session)</h3>
            <button
              type="button"
              className={styles.clearButton}
              style={{ fontSize: '11px', padding: '4px 8px' }}
              onClick={() => setHistory([])}
            >
              Clear History
            </button>
          </div>

          <div className={styles.historyList}>
            {history.map((item) => (
              <div
                key={item.id}
                className={styles.historyItem}
                onClick={() => handleSelectHistoryItem(item)}
                title="Click to load into SQL editor"
                role="button"
                tabIndex={0}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                  <span
                    className={item.status === 'success' ? styles.statusPillSuccess : styles.statusPillError}
                    style={{ fontSize: '10px', padding: '1px 6px' }}
                  >
                    {item.statementType}
                  </span>
                  <span className={styles.historySql}>{item.sql}</span>
                </div>

                <div className={styles.historyMeta}>
                  {item.rowsAffected !== null && item.rowsAffected !== undefined && (
                    <span>{item.rowsAffected} affected</span>
                  )}
                  {item.rowCount !== null && item.rowCount !== undefined && (
                    <span>{item.rowCount} rows</span>
                  )}
                  <span>{item.executionTimeMs}ms</span>
                  <span>{item.timestamp}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
};
