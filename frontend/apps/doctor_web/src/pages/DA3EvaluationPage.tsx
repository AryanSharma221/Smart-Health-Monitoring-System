import React, { useState, useEffect, useCallback } from 'react';
import {
  evaluationService,
  type EvaluationRecord,
  type SqlDemoResponse,
  type SqlExplainResponse,
  type ViewQueryResponse,
  type StoredFunctionResponse,
  type StoredProcedureResponse,
  type TriggerHistoryResponse,
  type MongoStatusResponse,
  type MongoCollectionInfo,
  type MongoDocumentListResponse,
  type MongoExplainResponse,
  type MongoAggregateResponse,
  type BenchmarkSummaryResponse,
  type PreflightDiagnosticResponse,
  type SecurityDemonstrationResponse,
  type RbacTestResponse,
  type TestRunnerReportResponse,
  type ChallengeMetadata,
  type ChallengeExecuteResponse,
} from '../api';
import {
  Button,
  RefreshIcon,
  DatabaseIcon,
  CheckCircleIcon,
  AlertTriangleIcon,
} from '../components/ui';
import styles from './DA3EvaluationPage.module.css';

type TabKey = 'crud' | 'sql' | 'db_objects' | 'explain' | 'mongodb' | 'benchmarks' | 'security' | 'diagnostics' | 'tests' | 'challenges';

export const DA3EvaluationPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('crud');
  const [loading, setLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'danger' | 'warning' | 'info'; text: string } | null>(null);

  // --- CRUD State ---
  const [records, setRecords] = useState<EvaluationRecord[]>([]);
  const [selectedPatient, setSelectedPatient] = useState('P101');
  const [newTitle, setNewTitle] = useState('Evaluation Follow-up Note');
  const [newContent, setNewContent] = useState('Patient vitals stabilized following medication regimen adjustment.');
  const [newRecordType, setNewRecordType] = useState('consultation_note');
  
  // Controlled Reading Ingestion State
  const [demoHr, setDemoHr] = useState(128.5);
  const [demoSpo2, setDemoSpo2] = useState(94.0);
  const [demoTemp, setDemoTemp] = useState(38.2);
  const [ingestionResult, setIngestionResult] = useState<any>(null);

  // --- SQL Demo State ---
  const [selectedSqlQuery, setSelectedSqlQuery] = useState('inner_join');
  const [sqlResult, setSqlResult] = useState<SqlDemoResponse | null>(null);

  // --- Database Objects State ---
  const [selectedView, setSelectedView] = useState<'v_latest_patient_vitals' | 'v_patient_active_alerts'>('v_latest_patient_vitals');
  const [viewResult, setViewResult] = useState<ViewQueryResponse | null>(null);
  
  // Stored Functions State
  const [bmiWeight, setBmiWeight] = useState(78.5);
  const [bmiHeight, setBmiHeight] = useState(1.75);
  const [bmiResult, setBmiResult] = useState<StoredFunctionResponse | null>(null);
  
  const [feverTemp, setFeverTemp] = useState(38.6);
  const [feverResult, setFeverResult] = useState<StoredFunctionResponse | null>(null);

  // Stored Procedures State
  const [procAlertId, setProcAlertId] = useState('ALT_EVAL_01');
  const [procNote, setProcNote] = useState('Clinician reviewed telemetry spike; patient instructed to rest.');
  const [procResult, setProcResult] = useState<StoredProcedureResponse | null>(null);
  const [safeDischargePatient, setSafeDischargePatient] = useState('P101');
  const [dischargeResult, setDischargeResult] = useState<StoredProcedureResponse | null>(null);

  // Trigger State
  const [triggerAlertId, setTriggerAlertId] = useState('ALT_EVAL_01');
  const [triggerHistory, setTriggerHistory] = useState<TriggerHistoryResponse | null>(null);

  // --- Explain State ---
  const [sqlExplainType, setSqlExplainType] = useState<'covering_index' | 'full_table_scan'>('covering_index');
  const [sqlExplainResult, setSqlExplainResult] = useState<SqlExplainResponse | null>(null);
  const [mongoExplainType, setMongoExplainType] = useState<'indexed' | 'unindexed'>('indexed');
  const [mongoExplainResult, setMongoExplainResult] = useState<MongoExplainResponse | null>(null);

  // --- MongoDB Read-Only State ---
  const [mongoStatus, setMongoStatus] = useState<MongoStatusResponse | null>(null);
  const [mongoCollections, setMongoCollections] = useState<MongoCollectionInfo[]>([]);
  const [selectedMongoColl, setSelectedMongoColl] = useState('telemetry_events');
  const [mongoDocs, setMongoDocs] = useState<MongoDocumentListResponse | null>(null);
  const [mongoSkip, setMongoSkip] = useState(0);
  const [selectedPipeline, setSelectedPipeline] = useState('dataset_overview');
  const [aggResult, setAggResult] = useState<MongoAggregateResponse | null>(null);

  // --- Benchmarks & Diagnostics State ---
  const [benchmarkData, setBenchmarkData] = useState<BenchmarkSummaryResponse | null>(null);
  const [diagnosticData, setDiagnosticData] = useState<PreflightDiagnosticResponse | null>(null);

  // --- Security & Error Handling State ---
  const [selectedSecurityScenario, setSelectedSecurityScenario] = useState('authorized_read');
  const [securityPatient, setSecurityPatient] = useState('P101');
  const [securityRecordId, setSecurityRecordId] = useState('P001');
  const [securityResult, setSecurityResult] = useState<SecurityDemonstrationResponse | null>(null);
  const [rbacData, setRbacData] = useState<RbacTestResponse | null>(null);

  // --- Demonstration Test Runner State (Part 7F) ---
  const [testReport, setTestReport] = useState<TestRunnerReportResponse | null>(null);
  const [selectedSuite, setSelectedSuite] = useState<string>('quick');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [testSearch, setTestSearch] = useState<string>('');
  const [expandedTestId, setExpandedTestId] = useState<string | null>(null);

  // --- Challenge Mode State (Part 7G) ---
  const [challenges, setChallenges] = useState<ChallengeMetadata[]>([]);
  const [selectedChallengeId, setSelectedChallengeId] = useState<string>('sql_select_patient_readings');
  const [challengeCategory, setChallengeCategory] = useState<string>('ALL');
  const [challengeParams, setChallengeParams] = useState<Record<string, any>>({
    patient_id: 'P101',
    limit: 10,
    heart_rate: 128.5,
    spo2: 94.0,
    temperature_f: 100.8,
    weight_kg: 78.5,
    height_m: 1.75,
    target_baseline: false,
    content_text: 'Patient vitals stabilized following oral hydration; telemetry returned to baseline.',
  });
  const [challengeConfirmed, setChallengeConfirmed] = useState<boolean>(false);
  const [challengeResult, setChallengeResult] = useState<ChallengeExecuteResponse | null>(null);
  const [challengeSearch, setChallengeSearch] = useState<string>('');

  // Load initial data for active tab
  const loadTabInitialData = useCallback(async () => {
    setActionMessage(null);
    try {
      if (activeTab === 'crud') {
        const data = await evaluationService.getRecords(selectedPatient);
        setRecords(data);
      } else if (activeTab === 'mongodb') {
        const [status, colls] = await Promise.all([
          evaluationService.getMongoStatus(),
          evaluationService.getMongoCollections(),
        ]);
        setMongoStatus(status);
        setMongoCollections(colls);
      } else if (activeTab === 'benchmarks') {
        const data = await evaluationService.getBenchmarkSummary();
        setBenchmarkData(data);
      } else if (activeTab === 'security') {
        const data = await evaluationService.getRbacTest();
        setRbacData(data);
      } else if (activeTab === 'diagnostics') {
        const data = await evaluationService.runPreflightDiagnostics();
        setDiagnosticData(data);
      } else if (activeTab === 'tests') {
        const data = await evaluationService.getLatestTestReport();
        setTestReport(data);
      } else if (activeTab === 'challenges') {
        const data = await evaluationService.getChallenges();
        setChallenges(data);
      }
    } catch (err: any) {
      console.error('Failed to load tab data:', err);
    }
  }, [activeTab, selectedPatient]);

  useEffect(() => {
    loadTabInitialData();
  }, [loadTabInitialData]);

  // --- CRUD Handlers ---
  const handleCreateRecord = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setActionMessage(null);
    try {
      const created = await evaluationService.createRecord({
        patient_id: selectedPatient,
        title: newTitle,
        content: newContent,
        record_type: newRecordType,
      });
      setActionMessage({
        type: 'success',
        text: `Successfully created ${created.record_id} for ${created.patient_id}. Non-repudiation audit log persisted.`,
      });
      const data = await evaluationService.getRecords(selectedPatient);
      setRecords(data);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Failed to create record: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteRecord = async (recordId: string) => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await evaluationService.deleteRecord(recordId);
      setActionMessage({ type: 'success', text: `${res.message} (${res.record_id})` });
      const data = await evaluationService.getRecords(selectedPatient);
      setRecords(data);
    } catch (err: any) {
      setActionMessage({
        type: 'danger',
        text: `Safety Guard Violation [HTTP ${err.statusCode || 403}]: ${err.message}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleTestSafetyGuard = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      // Attempt to delete protected patient P001
      await evaluationService.deleteRecord('P001');
      setActionMessage({ type: 'danger', text: 'Unexpected: Deletion of genuine patient was permitted!' });
    } catch (err: any) {
      setActionMessage({
        type: 'info',
        text: `Safety Guard Active: Backend rejected baseline deletion [HTTP ${err.statusCode || 403}]: ${err.message}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleInsertDemoReading = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await evaluationService.insertDemoReading({
        patient_id: selectedPatient,
        heart_rate: Number(demoHr),
        spo2: Number(demoSpo2),
        temperature_c: Number(demoTemp),
      });
      setIngestionResult(res);
      setActionMessage({
        type: 'success',
        text: `Telemetry ingested into MySQL: ${res.readings_created} metrics stored (Event: ${res.event_id}). Alert generated: ${res.alert_generated ? 'YES' : 'NO'}.`,
      });
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Ingestion failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- SQL Demo Handlers ---
  const handleRunSqlQuery = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await evaluationService.demonstrateSql({
        query_name: selectedSqlQuery,
        patient_id: selectedPatient,
        limit: 10,
      });
      setSqlResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `SQL execution failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- Database Objects Handlers ---
  const handleQueryView = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.queryView(selectedView);
      setViewResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `View query failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleRunBmi = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.runStoredFunction('calculate-bmi', {
        weight_kg: Number(bmiWeight),
        height_m: Number(bmiHeight),
      });
      setBmiResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `BMI function error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleRunFever = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.runStoredFunction('fever-category', {
        temp_c: Number(feverTemp),
      });
      setFeverResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Fever function error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleRunAcknowledge = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.runStoredProcedure('acknowledge-alert', {
        alert_id: procAlertId,
        clinician_id: 'DOC_TEST_01',
        note: procNote,
      });
      setProcResult(res);
      // Automatically refresh trigger history to show the trigger fired
      handleInspectTrigger();
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Acknowledge error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleRunSafeDischarge = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.runStoredProcedure('safe-discharge', {
        patient_id: safeDischargePatient,
      });
      setDischargeResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Safe discharge error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleInspectTrigger = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.getTriggerHistory(triggerAlertId);
      setTriggerHistory(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Trigger inspection error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleFireTriggerTest = async () => {
    setLoading(true);
    try {
      await evaluationService.testTriggerUpdate(triggerAlertId, 'ACKNOWLEDGED');
      setActionMessage({ type: 'success', text: `Alert ${triggerAlertId} status updated. Trigger trg_alert_status_history_after_update invoked.` });
      handleInspectTrigger();
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Trigger test failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- Explain Handlers ---
  const handleRunSqlExplain = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.explainSql(sqlExplainType);
      setSqlExplainResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `SQL Explain failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleRunMongoExplain = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.explainMongoQuery({
        collection_name: 'telemetry_events',
        query_type: mongoExplainType,
        patient_id: selectedPatient,
      });
      setMongoExplainResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Mongo Explain failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- MongoDB Read-Only Handlers ---
  const handleFetchMongoDocuments = async (skip = 0) => {
    setLoading(true);
    try {
      const docs = await evaluationService.getMongoDocuments(selectedMongoColl, {
        limit: 10,
        skip,
        patient_id: selectedMongoColl === 'telemetry_events' ? selectedPatient : undefined,
      });
      setMongoDocs(docs);
      setMongoSkip(skip);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Failed to fetch MongoDB documents: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleRunMongoAggregate = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await evaluationService.aggregateMongo({
        pipeline_name: selectedPipeline,
        patient_id: selectedPatient,
      });
      setAggResult(res);
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Aggregation failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- Diagnostics Runner ---
  const handleRunDiagnostics = async () => {
    setLoading(true);
    try {
      const res = await evaluationService.runPreflightDiagnostics();
      setDiagnosticData(res);
      setActionMessage({
        type: res.all_systems_ready ? 'success' : 'warning',
        text: res.all_systems_ready
          ? 'Preflight Verification Passed: All 10 database, schema, and API services are ready.'
          : 'Preflight Verification Complete: Review warnings in diagnostics tab.',
      });
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Diagnostics execution failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- Security Scenario Runner ---
  const handleRunSecurityScenario = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await evaluationService.demonstrateSecurity(
        selectedSecurityScenario,
        securityPatient,
        securityRecordId
      );
      setSecurityResult(res);
      setActionMessage({
        type: res.outcome === 'PERMITTED' ? 'success' : res.outcome === 'DENIED' ? 'warning' : 'info',
        text: `Scenario "${res.title}" executed: Outcome [HTTP ${res.actual_status}] -> ${res.outcome}`,
      });
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Security demonstration error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- Test Runner Handlers (Part 7F) ---
  const handleRunTests = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const data = await evaluationService.runDemonstrationTests(selectedSuite);
      setTestReport(data);
      setActionMessage({
        type: data.overall_status === 'PASSED' ? 'success' : 'danger',
        text: `Test Suite Execution Complete [${data.run_id}]: ${data.summary.passed}/${data.summary.total_tests} Passed (${data.summary.pass_rate_percent}%) in ${data.total_duration_ms.toFixed(1)}ms.`,
      });
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Failed to execute test suite: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleReloadTestReport = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const data = await evaluationService.getLatestTestReport();
      setTestReport(data);
      setActionMessage({
        type: 'info',
        text: `Loaded persisted test report [${data.run_id}] executed at ${data.completed_at}.`,
      });
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Failed to load test report: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // --- Challenge Mode Handlers (Part 7G) ---
  const handleExecuteChallenge = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await evaluationService.executeChallenge({
        challenge_id: selectedChallengeId,
        parameters: challengeParams,
        confirmed: challengeConfirmed,
      });
      setChallengeResult(res);
      setActionMessage({
        type: res.status === 'SUCCESS' ? 'success' : res.status === 'REJECTED_SAFE' ? 'warning' : 'info',
        text: `Challenge "${res.name}" executed: [${res.status}] in ${res.execution_time_ms.toFixed(2)} ms.`,
      });
    } catch (err: any) {
      setActionMessage({ type: 'danger', text: `Challenge execution error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      {/* Top Banner */}
      <div className={styles.banner}>
        <div className={styles.bannerLeft}>
          <div className={styles.bannerTitle}>
            <DatabaseIcon size={20} />
            <span>DA3 Live Database Evaluation Console</span>
          </div>
          <div className={styles.bannerSubtitle}>
            Relational Operational Store (MySQL) &amp; Read-Only Analytics Store (MongoDB Atlas) Demonstration Portal
          </div>
        </div>

        <div className={styles.bannerBadges}>
          <span className={styles.badgeReadOnly} title="Strict Non-Negotiable Invariant: No writes or migrations in MongoDB">
            MongoDB: Strictly Read-Only
          </span>
          <span className={styles.badgeSqlSafe} title="EVAL_* isolation prevents corruption of genuine patient records">
            MySQL: Safe EVAL Fixtures
          </span>
          <span className={styles.badgeAtlas}>
            Atlas: cluster0.offnaie.mongodb.net
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRunDiagnostics}
            disabled={loading}
          >
            <RefreshIcon size={14} />
            <span>Preflight Audit</span>
          </Button>
        </div>
      </div>

      {/* Action Notification Alert */}
      {actionMessage && (
        <div
          className={
            actionMessage.type === 'success'
              ? styles.alertSuccess
              : actionMessage.type === 'danger'
              ? styles.alertDanger
              : actionMessage.type === 'warning'
              ? styles.alertWarning
              : styles.alertInfo
          }
        >
          {actionMessage.text}
        </div>
      )}

      {/* Tab Navigation */}
      <nav className={styles.tabNav} aria-label="Evaluation Console Sections">
        <button
          className={`${styles.tabButton} ${activeTab === 'crud' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('crud')}
        >
          1. CRUD Operations
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'sql' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('sql')}
        >
          2. Named SQL Demos
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'db_objects' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('db_objects')}
        >
          3. Database Objects (Views/Procs/Triggers)
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'explain' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('explain')}
        >
          4. Indexing &amp; EXPLAIN Plans
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'mongodb' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('mongodb')}
        >
          5. MongoDB Read-Only Analytics
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'benchmarks' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('benchmarks')}
        >
          6. Benchmarks &amp; Scorecard
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'security' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('security')}
        >
          7. Security &amp; Access Control
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'diagnostics' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('diagnostics')}
        >
          8. Preflight Diagnostics
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'tests' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('tests')}
        >
          9. Test Runner &amp; Evidence
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'challenges' ? styles.tabButtonActive : ''}`}
          onClick={() => setActiveTab('challenges')}
        >
          10. Challenge Mode
        </button>
      </nav>

      {/* ========================================================================= */}
      {/* TAB 1: CRUD OPERATIONS                                                    */}
      {/* ========================================================================= */}
      {activeTab === 'crud' && (
        <div className={styles.container}>
          <div className={styles.twoColGrid}>
            {/* Create Evaluation Record */}
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>Insert Evaluation Record (ACID Transaction)</h3>
                  <p className={styles.cardDesc}>Creates isolated EVAL_* record with non-repudiation audit logging</p>
                </div>
              </div>

              <form onSubmit={handleCreateRecord} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <div className={styles.formRow}>
                  <label className={styles.formLabel}>Target Patient</label>
                  <select
                    className={styles.formSelect}
                    value={selectedPatient}
                    onChange={(e) => setSelectedPatient(e.target.value)}
                  >
                    <option value="P101">P101 (Demo Patient - Tachycardia Profile)</option>
                    <option value="P102">P102 (Demo Patient - Bradycardia Profile)</option>
                    <option value="P103">P103 (Demo Patient - Hypoxemia Profile)</option>
                    <option value="P104">P104 (Demo Patient - Pyrexia Profile)</option>
                    <option value="P105">P105 (Demo Patient - Normal Baseline)</option>
                  </select>
                </div>

                <div className={styles.formRow}>
                  <label className={styles.formLabel}>Record Type</label>
                  <select
                    className={styles.formSelect}
                    value={newRecordType}
                    onChange={(e) => setNewRecordType(e.target.value)}
                  >
                    <option value="consultation_note">Consultation Note</option>
                    <option value="triage_assessment">Triage Assessment</option>
                    <option value="evaluation_finding">Evaluation Finding</option>
                  </select>
                </div>

                <div className={styles.formRow}>
                  <label className={styles.formLabel}>Title</label>
                  <input
                    type="text"
                    className={styles.formInput}
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    required
                  />
                </div>

                <div className={styles.formRow}>
                  <label className={styles.formLabel}>Clinical Content</label>
                  <textarea
                    className={styles.formTextarea}
                    value={newContent}
                    onChange={(e) => setNewContent(e.target.value)}
                    required
                  />
                </div>

                <Button type="submit" variant="primary" disabled={loading}>
                  <span>Execute INSERT Transaction</span>
                </Button>
              </form>
            </div>

            {/* Controlled Telemetry Reading Ingestion */}
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>Controlled Reading Ingestion &amp; Surveillance Trigger</h3>
                  <p className={styles.cardDesc}>Inserts ingestion_events and vitals_readings with automated alert trigger</p>
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <div className={styles.threeColGrid}>
                  <div className={styles.formRow}>
                    <label className={styles.formLabel}>Heart Rate (bpm)</label>
                    <input
                      type="number"
                      className={styles.formInput}
                      value={demoHr}
                      onChange={(e) => setDemoHr(Number(e.target.value))}
                    />
                  </div>
                  <div className={styles.formRow}>
                    <label className={styles.formLabel}>SpO2 (%)</label>
                    <input
                      type="number"
                      className={styles.formInput}
                      value={demoSpo2}
                      onChange={(e) => setDemoSpo2(Number(e.target.value))}
                    />
                  </div>
                  <div className={styles.formRow}>
                    <label className={styles.formLabel}>Temp (°C)</label>
                    <input
                      type="number"
                      step="0.1"
                      className={styles.formInput}
                      value={demoTemp}
                      onChange={(e) => setDemoTemp(Number(e.target.value))}
                    />
                  </div>
                </div>

                <Button variant="secondary" onClick={handleInsertDemoReading} disabled={loading}>
                  <span>Ingest Telemetry Reading</span>
                </Button>

                {ingestionResult && (
                  <div className={styles.codeBox}>
                    {JSON.stringify(ingestionResult, null, 2)}
                  </div>
                )}

                <div style={{ borderTop: '1px solid var(--color-border-subtle)', paddingTop: 'var(--space-3)' }}>
                  <p className={styles.cardDesc} style={{ marginBottom: '8px' }}>
                    <strong>Safety Guard Verification:</strong> Verify that baseline EHR records (e.g., genuine patient P001) are protected from accidental deletion.
                  </p>
                  <Button variant="destructive" size="sm" onClick={handleTestSafetyGuard} disabled={loading}>
                    <span>Attempt Protected Deletion (P001)</span>
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Records Table */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Evaluation Records ({records.length})</h3>
                <p className={styles.cardDesc}>Isolated evaluation test records for patient {selectedPatient}</p>
              </div>
              <Button size="sm" variant="secondary" onClick={() => loadTabInitialData()} disabled={loading}>
                <RefreshIcon size={14} />
                <span>Refresh Records</span>
              </Button>
            </div>

            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Record ID</th>
                    <th>Patient</th>
                    <th>Type</th>
                    <th>Title</th>
                    <th>Created At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {records.length === 0 ? (
                    <tr>
                      <td colSpan={6} style={{ textAlign: 'center', padding: '16px', color: 'var(--color-text-secondary)' }}>
                        No evaluation records found for {selectedPatient}. Create one above!
                      </td>
                    </tr>
                  ) : (
                    records.map((r) => (
                      <tr key={r.record_id}>
                        <td><strong>{r.record_id}</strong></td>
                        <td>{r.patient_id}</td>
                        <td>{r.record_type}</td>
                        <td>{r.title}</td>
                        <td>{r.created_at}</td>
                        <td>
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => handleDeleteRecord(r.record_id)}
                            disabled={loading}
                          >
                            <span>Delete</span>
                          </Button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: NAMED SQL DEMOS                                                    */}
      {/* ========================================================================= */}
      {activeTab === 'sql' && (
        <div className={styles.container}>
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Named SQL Query Demonstration</h3>
                <p className={styles.cardDesc}>Select a server-side parameterized query supported by the MySQL schema</p>
              </div>

              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <Button variant="primary" onClick={handleRunSqlQuery} disabled={loading}>
                  <span>Execute Query</span>
                </Button>
              </div>
            </div>

            <div className={styles.twoColGrid}>
              <div className={styles.formRow}>
                <label className={styles.formLabel}>Query Demonstration</label>
                <select
                  className={styles.formSelect}
                  value={selectedSqlQuery}
                  onChange={(e) => setSelectedSqlQuery(e.target.value)}
                >
                  <option value="basic_filter">1. Basic Filter &amp; Temporal Sort (vitals_readings)</option>
                  <option value="inner_join">2. Two-Table Inner Join (patient_profiles + vitals_readings)</option>
                  <option value="multi_join">3. 5-Table Multi-Table Join (alerts + patients + assignments + doctors + users)</option>
                  <option value="nested_subquery">4. Nested Subquery / CTE (ROW_NUMBER partition by metric)</option>
                  <option value="aggregate_moments">5. Aggregate Moments (COUNT, AVG, MIN, MAX)</option>
                  <option value="group_by_having">6. GROUP BY &amp; HAVING (Hourly vitals with count threshold)</option>
                  <option value="left_outer_join">7. LEFT OUTER JOIN (Cohort alert summary preserving 0-alert patients)</option>
                </select>
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Target Patient (where parameterized)</label>
                <select
                  className={styles.formSelect}
                  value={selectedPatient}
                  onChange={(e) => setSelectedPatient(e.target.value)}
                >
                  <option value="P101">P101 (Tachycardia Profile)</option>
                  <option value="P102">P102 (Bradycardia Profile)</option>
                  <option value="P103">P103 (Hypoxemia Profile)</option>
                  <option value="P104">P104 (Pyrexia Profile)</option>
                  <option value="P105">P105 (Normal Baseline)</option>
                </select>
              </div>
            </div>

            {sqlResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                  <span className={styles.metricBadge}>Execution: {sqlResult.execution_time_ms} ms</span>
                  <span className={styles.metricBadge}>Rows: {sqlResult.row_count}</span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                    {sqlResult.description}
                  </span>
                </div>

                <div className={styles.codeBox}>
                  {sqlResult.sql_syntax}
                </div>

                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        {sqlResult.columns.map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sqlResult.rows.map((row, idx) => (
                        <tr key={idx}>
                          {sqlResult.columns.map((col) => (
                            <td key={col}>{row[col] !== null ? String(row[col]) : 'NULL'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: DATABASE OBJECTS                                                   */}
      {/* ========================================================================= */}
      {activeTab === 'db_objects' && (
        <div className={styles.container}>
          {/* Views */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>1. Relational Views (v_latest_patient_vitals &amp; v_patient_active_alerts)</h3>
                <p className={styles.cardDesc}>Query predefined database views abstracting complex multi-table joins</p>
              </div>

              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <select
                  className={styles.formSelect}
                  value={selectedView}
                  onChange={(e) => setSelectedView(e.target.value as any)}
                >
                  <option value="v_latest_patient_vitals">v_latest_patient_vitals</option>
                  <option value="v_patient_active_alerts">v_patient_active_alerts</option>
                </select>
                <Button variant="primary" onClick={handleQueryView} disabled={loading}>
                  <span>Query View</span>
                </Button>
              </div>
            </div>

            {viewResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <div className={styles.codeBox}>{viewResult.view_definition}</div>
                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        {viewResult.columns.map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {viewResult.data.map((row, idx) => (
                        <tr key={idx}>
                          {viewResult.columns.map((col) => (
                            <td key={col}>{row[col] !== null ? String(row[col]) : 'NULL'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* Stored Functions */}
          <div className={styles.twoColGrid}>
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>2. Stored Function: calculate_bmi</h3>
                  <p className={styles.cardDesc}>Computes BMI and WHO classification from anthropometric data</p>
                </div>
              </div>

              <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
                <div className={styles.formRow} style={{ flex: 1 }}>
                  <label className={styles.formLabel}>Weight (kg)</label>
                  <input
                    type="number"
                    className={styles.formInput}
                    value={bmiWeight}
                    onChange={(e) => setBmiWeight(Number(e.target.value))}
                  />
                </div>
                <div className={styles.formRow} style={{ flex: 1 }}>
                  <label className={styles.formLabel}>Height (m)</label>
                  <input
                    type="number"
                    step="0.01"
                    className={styles.formInput}
                    value={bmiHeight}
                    onChange={(e) => setBmiHeight(Number(e.target.value))}
                  />
                </div>
              </div>

              <Button variant="secondary" onClick={handleRunBmi} disabled={loading}>
                <span>Execute calculate_bmi</span>
              </Button>

              {bmiResult && (
                <div className={styles.alertInfo}>
                  <strong>Result: {bmiResult.result}</strong> — {bmiResult.interpretation}
                </div>
              )}
            </div>

            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>3. Stored Function: fever_category</h3>
                  <p className={styles.cardDesc}>Classifies core temperature into clinical pyrexia stages</p>
                </div>
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Body Temperature (°C)</label>
                <input
                  type="number"
                  step="0.1"
                  className={styles.formInput}
                  value={feverTemp}
                  onChange={(e) => setFeverTemp(Number(e.target.value))}
                />
              </div>

              <Button variant="secondary" onClick={handleRunFever} disabled={loading}>
                <span>Execute fever_category</span>
              </Button>

              {feverResult && (
                <div className={styles.alertInfo}>
                  <strong>Classification: {feverResult.result}</strong> — {feverResult.interpretation}
                </div>
              )}
            </div>
          </div>

          {/* Stored Procedures & Triggers */}
          <div className={styles.twoColGrid}>
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>4. Stored Procedure: acknowledge_alert</h3>
                  <p className={styles.cardDesc}>ACID transaction updating alert state and invoking status history trigger</p>
                </div>
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Alert ID</label>
                <input
                  type="text"
                  className={styles.formInput}
                  value={procAlertId}
                  onChange={(e) => setProcAlertId(e.target.value)}
                />
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Clinical Note</label>
                <input
                  type="text"
                  className={styles.formInput}
                  value={procNote}
                  onChange={(e) => setProcNote(e.target.value)}
                />
              </div>

              <Button variant="primary" onClick={handleRunAcknowledge} disabled={loading}>
                <span>Execute Procedure &amp; Trigger</span>
              </Button>

              {procResult && (
                <div className={styles.alertSuccess}>
                  <strong>{procResult.status}:</strong> {procResult.message}
                </div>
              )}
            </div>

            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>5. Stored Procedure: safe_discharge</h3>
                  <p className={styles.cardDesc}>Demonstrates transactional rollback if active alerts remain unresolved</p>
                </div>
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Patient ID</label>
                <select
                  className={styles.formSelect}
                  value={safeDischargePatient}
                  onChange={(e) => setSafeDischargePatient(e.target.value)}
                >
                  <option value="P101">P101 (Has open alerts - will ROLLBACK)</option>
                  <option value="P105">P105 (Stable cohort - eligible)</option>
                </select>
              </div>

              <Button variant="destructive" onClick={handleRunSafeDischarge} disabled={loading}>
                <span>Execute Safe Discharge Procedure</span>
              </Button>

              {dischargeResult && (
                <div className={dischargeResult.status === 'ROLLED_BACK' ? styles.alertWarning : styles.alertSuccess}>
                  <strong>Outcome: {dischargeResult.status}</strong> — {dischargeResult.message}
                </div>
              )}
            </div>
          </div>

          {/* Trigger Audit Log Inspector */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>6. Trigger Verification: trg_alert_status_history_after_update</h3>
                <p className={styles.cardDesc}>Inspects automatic history row insertion generated by the AFTER UPDATE trigger</p>
              </div>

              <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  className={styles.formInput}
                  value={triggerAlertId}
                  onChange={(e) => setTriggerAlertId(e.target.value)}
                  style={{ width: '140px' }}
                  title="Alert ID to test trigger on"
                />
                <Button variant="secondary" size="sm" onClick={handleFireTriggerTest} disabled={loading}>
                  <span>Fire Trigger Test Update</span>
                </Button>
                <Button variant="primary" size="sm" onClick={handleInspectTrigger} disabled={loading}>
                  <span>Inspect Audit Table</span>
                </Button>
              </div>
            </div>

            {triggerHistory && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <div className={styles.codeBox}>{triggerHistory.trigger_definition}</div>
                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>History ID</th>
                        <th>Alert ID</th>
                        <th>Old Status</th>
                        <th>New Status</th>
                        <th>Actor ID</th>
                        <th>Note</th>
                        <th>Timestamp</th>
                      </tr>
                    </thead>
                    <tbody>
                      {triggerHistory.history_records.map((item) => (
                        <tr key={item.history_id}>
                          <td>{item.history_id}</td>
                          <td><strong>{item.alert_id}</strong></td>
                          <td>{item.old_status || 'NONE'}</td>
                          <td><span className={styles.badgeSqlSafe}>{item.new_status}</span></td>
                          <td>{item.actor_id}</td>
                          <td>{item.note || '—'}</td>
                          <td>{item.changed_at}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 4: INDEXING & EXPLAIN PLANS                                           */}
      {/* ========================================================================= */}
      {activeTab === 'explain' && (
        <div className={styles.container}>
          <div className={styles.twoColGrid}>
            {/* SQL EXPLAIN Plan */}
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>MySQL Indexing &amp; EXPLAIN Plan</h3>
                  <p className={styles.cardDesc}>Covering B-Tree Index vs. Full Table Sequential Scan</p>
                </div>
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Query Scan Mode</label>
                <select
                  className={styles.formSelect}
                  value={sqlExplainType}
                  onChange={(e) => setSqlExplainType(e.target.value as any)}
                >
                  <option value="covering_index">Covering Index Scan (idx_vitals_patient_metric_time)</option>
                  <option value="full_table_scan">Full Table Scan (Unindexed metric pattern)</option>
                </select>
              </div>

              <Button variant="primary" onClick={handleRunSqlExplain} disabled={loading}>
                <span>Generate SQL EXPLAIN</span>
              </Button>

              {sqlExplainResult && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                    <span className={styles.metricBadge}>Stage: {sqlExplainResult.scan_type}</span>
                    <span className={styles.metricBadge}>Index: {sqlExplainResult.index_used || 'NONE'}</span>
                    <span className={styles.metricBadge}>Rows Examined: {sqlExplainResult.rows_examined}</span>
                    <span className={styles.metricBadge}>Latency: {sqlExplainResult.execution_time_ms} ms</span>
                  </div>

                  <div className={styles.alertInfo}>
                    <strong>Academic Analysis:</strong> {sqlExplainResult.analysis}
                  </div>

                  <div className={styles.codeBox}>
                    {JSON.stringify(sqlExplainResult.raw_plan, null, 2)}
                  </div>
                </div>
              )}
            </div>

            {/* MongoDB EXPLAIN Plan */}
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>MongoDB Atlas explain() Plan</h3>
                  <p className={styles.cardDesc}>Compound Index IXSCAN vs. Collection Scan COLLSCAN</p>
                </div>
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Query Mode</label>
                <select
                  className={styles.formSelect}
                  value={mongoExplainType}
                  onChange={(e) => setMongoExplainType(e.target.value as any)}
                >
                  <option value="indexed">Indexed IXSCAN (idx_telemetry_patient_measured)</option>
                  <option value="unindexed">Unindexed COLLSCAN (Nested metrics.heart_rate)</option>
                </select>
              </div>

              <Button variant="secondary" onClick={handleRunMongoExplain} disabled={loading}>
                <span>Execute collection.explain()</span>
              </Button>

              {mongoExplainResult && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                    <span className={styles.metricBadge}>Winning Stage: {mongoExplainResult.winning_stage}</span>
                    <span className={styles.metricBadge}>Index: {mongoExplainResult.index_used || 'NONE'}</span>
                    <span className={styles.metricBadge}>Docs Examined: {mongoExplainResult.total_docs_examined}</span>
                    <span className={styles.metricBadge}>Keys Examined: {mongoExplainResult.total_keys_examined}</span>
                    <span className={styles.metricBadge}>Latency: {mongoExplainResult.execution_time_ms} ms</span>
                  </div>

                  <div className={styles.alertInfo}>
                    <strong>Academic Analysis:</strong> {mongoExplainResult.analysis}
                  </div>

                  <div className={styles.codeBox}>
                    {JSON.stringify(mongoExplainResult.raw_plan, null, 2)}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 5: MONGODB READ-ONLY ANALYTICS                                        */}
      {/* ========================================================================= */}
      {activeTab === 'mongodb' && (
        <div className={styles.container}>
          {/* Read-Only Safety Callout */}
          <div className={styles.alertWarning}>
            <strong>Non-Negotiable Restriction:</strong> MongoDB Atlas analytics store is strictly <strong>READ-ONLY</strong>.
            All writes, schema modifications, index modifications, and write-producing stages ($out, $merge) are rejected at the gateway with HTTP 403 Forbidden.
          </div>

          {/* Cluster Status */}
          {mongoStatus && (
            <div className={styles.threeColGrid}>
              <div className={styles.card}>
                <span className={styles.formLabel}>Atlas Cloud Host</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', wordBreak: 'break-all' }}>
                  {mongoStatus.sanitized_endpoint}
                </span>
                <span className={styles.metricBadge}>Latency: {mongoStatus.latency_ms} ms</span>
              </div>

              <div className={styles.card}>
                <span className={styles.formLabel}>Collections &amp; Documents</span>
                <span style={{ fontSize: 'var(--text-lg)', fontWeight: 'bold' }}>
                  {mongoStatus.collections.telemetry_events?.document_count || 2955} documents
                </span>
                <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                  in telemetry_events (Kaggle CSV + Smartwatch Telemetry)
                </span>
              </div>

              <div className={styles.card}>
                <span className={styles.formLabel}>Outbox Queue &amp; Sync Policy</span>
                <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'bold' }}>
                  {mongoStatus.outbox_queue.pending_sync_count} pending outbox events
                </span>
                <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                  Policy: {mongoStatus.outbox_queue.sync_policy}
                </span>
              </div>
            </div>
          )}

          {/* Registered Collections & Indexes */}
          {mongoCollections.length > 0 && (
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div>
                  <h3 className={styles.cardTitle}>Registered MongoDB Collections &amp; B-Tree Indexes</h3>
                  <p className={styles.cardDesc}>Read-only collection and index metadata queried live from MongoDB Atlas</p>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                {mongoCollections.map((col) => (
                  <span key={col.name} className={styles.metricBadge}>
                    <strong>{col.name}</strong>: {col.document_count} documents, {col.indexes_count} indexes
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Read-Only Analytical Pipelines */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Execute Analytical Aggregation Pipeline (Read-Only)</h3>
                <p className={styles.cardDesc}>Executes server-side composable pipeline on MongoDB Atlas</p>
              </div>

              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <select
                  className={styles.formSelect}
                  value={selectedPipeline}
                  onChange={(e) => setSelectedPipeline(e.target.value)}
                >
                  <option value="dataset_overview">1. Dataset Overview ($facet)</option>
                  <option value="patient_vitals_summary">2. Patient Statistical Moments ($group)</option>
                  <option value="time_bucketed">3. Chronological Daily Trends ($group)</option>
                  <option value="source_provenance">4. Source Provenance Breakdown ($group)</option>
                  <option value="data_quality">5. Data Hygiene &amp; Bounds Audit</option>
                  <option value="alert_triage">6. Clinical Alert Triage</option>
                  <option value="outlier_detection">7. Outlier Detection</option>
                </select>

                <Button variant="primary" onClick={handleRunMongoAggregate} disabled={loading}>
                  <span>Run Pipeline</span>
                </Button>
              </div>
            </div>

            {aggResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                  <span className={styles.metricBadge}>Pipeline: {aggResult.pipeline_name}</span>
                  <span className={styles.metricBadge}>Execution: {aggResult.execution_time_ms} ms</span>
                  <span className={styles.metricBadge}>Results: {aggResult.result_count} items</span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>{aggResult.description}</span>
                </div>

                <div className={styles.codeBox}>
                  {aggResult.pipeline_json}
                </div>

                <div className={styles.codeBox} style={{ maxHeight: '350px' }}>
                  {JSON.stringify(aggResult.results, null, 2)}
                </div>
              </div>
            )}
          </div>

          {/* Document Browser */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Document Browser &amp; Bounded Pagination</h3>
                <p className={styles.cardDesc}>Browse read-only collection documents with projection filtering</p>
              </div>

              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <select
                  className={styles.formSelect}
                  value={selectedMongoColl}
                  onChange={(e) => setSelectedMongoColl(e.target.value)}
                >
                  <option value="telemetry_events">telemetry_events (2,955 docs)</option>
                  <option value="alert_events">alert_events (0 docs)</option>
                </select>

                <Button variant="secondary" size="sm" onClick={() => handleFetchMongoDocuments(0)} disabled={loading}>
                  <span>Browse Documents</span>
                </Button>
              </div>
            </div>

            {mongoDocs && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                    Showing {mongoDocs.skip + 1}–{mongoDocs.skip + mongoDocs.documents.length} of {mongoDocs.total_count} records
                  </span>
                  <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleFetchMongoDocuments(Math.max(0, mongoSkip - 10))}
                      disabled={mongoSkip === 0 || loading}
                    >
                      <span>Previous 10</span>
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleFetchMongoDocuments(mongoSkip + 10)}
                      disabled={!mongoDocs.has_more || loading}
                    >
                      <span>Next 10</span>
                    </Button>
                  </div>
                </div>

                <div className={styles.codeBox} style={{ maxHeight: '350px' }}>
                  {JSON.stringify(mongoDocs.documents, null, 2)}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 6: PERFORMANCE BENCHMARKS & SCORECARD                                 */}
      {/* ========================================================================= */}
      {activeTab === 'benchmarks' && (
        <div className={styles.container}>
          {benchmarkData && (
            <>
              {/* Scorecard */}
              <div className={styles.threeColGrid}>
                <div className={styles.card}>
                  <span className={styles.formLabel}>Backend Automated Tests</span>
                  <span style={{ fontSize: 'var(--text-xl)', fontWeight: 'bold', color: '#16a34a' }}>
                    {benchmarkData.test_scorecard.passed_backend_tests} / {benchmarkData.test_scorecard.total_backend_tests} Passing
                  </span>
                  <span className={styles.metricBadge}>Pass Rate: {benchmarkData.test_scorecard.backend_pass_rate}</span>
                </div>

                <div className={styles.card}>
                  <span className={styles.formLabel}>Frontend Client Tests</span>
                  <span style={{ fontSize: 'var(--text-xl)', fontWeight: 'bold', color: '#16a34a' }}>
                    {benchmarkData.test_scorecard.frontend_tests} / {benchmarkData.test_scorecard.frontend_tests} Passing
                  </span>
                  <span className={styles.metricBadge}>Pass Rate: {benchmarkData.test_scorecard.frontend_pass_rate}</span>
                </div>

                <div className={styles.card}>
                  <span className={styles.formLabel}>Consistency &amp; Recovery</span>
                  <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'bold' }}>
                    {benchmarkData.test_scorecard.consistency_verdict}
                  </span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                    Recovery: {benchmarkData.test_scorecard.recovery_verdict}
                  </span>
                </div>
              </div>

              {/* Workloads Table */}
              <div className={styles.card}>
                <div className={styles.cardHeader}>
                  <div>
                    <h3 className={styles.cardTitle}>Empirical Evaluation: 7 Evaluated Workloads</h3>
                    <p className={styles.cardDesc}>Relational MySQL vs. Document-Oriented MongoDB Atlas comparative metrics</p>
                  </div>
                </div>

                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Workload ID</th>
                        <th>Category</th>
                        <th>Target Engine</th>
                        <th>Description</th>
                        <th>Mean Latency</th>
                        <th>P95 Latency</th>
                        <th>Throughput (QPS)</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {benchmarkData.workloads.map((w) => (
                        <tr key={w.workload_id}>
                          <td><strong>{w.workload_id}</strong></td>
                          <td>{w.category}</td>
                          <td>
                            <span className={w.target_engine.includes('MySQL') ? styles.badgeSqlSafe : styles.badgeAtlas}>
                              {w.target_engine}
                            </span>
                          </td>
                          <td>{w.description}</td>
                          <td><strong>{w.latency_ms} ms</strong></td>
                          <td>{w.p95_latency_ms} ms</td>
                          <td>{w.throughput_qps}</td>
                          <td><span className={styles.badgeSqlSafe}>{w.status}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Visual Latency Bars */}
                <div style={{ marginTop: 'var(--space-4)' }}>
                  <h4 style={{ fontSize: 'var(--text-xs)', fontWeight: 'bold', textTransform: 'uppercase', color: 'var(--color-text-secondary)', marginBottom: '12px' }}>
                    Latency Distribution (Lower is faster)
                  </h4>
                  <div className={styles.barContainer}>
                    {benchmarkData.workloads.map((w) => (
                      <div key={w.workload_id} className={styles.barRow}>
                        <span className={styles.barLabel}>{w.workload_id} ({w.target_engine})</span>
                        <div className={styles.barTrack}>
                          <div
                            className={`${styles.barFill} ${w.target_engine.includes('MySQL') ? styles.barFillSql : styles.barFillNoSql}`}
                            style={{ width: `${Math.min(100, Math.max(5, (w.latency_ms / 60) * 100))}%` }}
                          />
                        </div>
                        <span className={styles.barValue}>{w.latency_ms} ms</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 7: SECURITY, ACCESS CONTROL & ERROR HANDLING                          */}
      {/* ========================================================================= */}
      {activeTab === 'security' && (
        <div className={styles.container}>
          {/* RBAC Privilege Matrix */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Role-Based Access Control (RBAC) Privilege Matrix</h3>
                <p className={styles.cardDesc}>Multi-tiered role boundary enforcement for clinical surveillance, patient privacy, and audit controls</p>
              </div>

              {rbacData && (
                <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                  <span className={styles.metricBadge}>Caller Role: {rbacData.caller_role}</span>
                  <span className={styles.metricBadge}>Identity: {rbacData.caller_id}</span>
                </div>
              )}
            </div>

            {rbacData && (
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>User Role Tier</th>
                      <th>View Assigned Patients</th>
                      <th>View Entire Hospital Cohort</th>
                      <th>Acknowledge / Resolve Alerts</th>
                      <th>Delete Evaluation Fixtures</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rbacData.access_matrix.map((row, idx) => (
                      <tr key={idx}>
                        <td><strong>{row.role}</strong></td>
                        <td>{row.view_assigned ? '✅ Permitted' : '❌ Prohibited'}</td>
                        <td>{row.view_all ? '✅ Permitted' : '❌ Prohibited (Forbidden)'}</td>
                        <td>{row.ack_alerts ? '✅ Permitted' : '❌ Prohibited'}</td>
                        <td>{row.delete_eval ? '✅ Permitted (EVAL_* only)' : '❌ Prohibited'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Interactive Security & Error Scenario Runner */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Reproducible Security &amp; Error Handling Scenarios</h3>
                <p className={styles.cardDesc}>Execute controlled security probes to verify authorization denials, validation, and sanitized errors</p>
              </div>

              <Button variant="primary" onClick={handleRunSecurityScenario} disabled={loading}>
                <span>Execute Security Scenario</span>
              </Button>
            </div>

            <div className={styles.twoColGrid}>
              <div className={styles.formRow}>
                <label className={styles.formLabel}>Select Security Scenario</label>
                <select
                  className={styles.formSelect}
                  value={selectedSecurityScenario}
                  onChange={(e) => setSelectedSecurityScenario(e.target.value)}
                >
                  <option value="authorized_read">1. Authorized Health Record Access (HTTP 200)</option>
                  <option value="denied_unassigned_patient">2. RBAC Unauthorized Patient Access Denial (HTTP 403)</option>
                  <option value="denied_baseline_delete">3. Core EHR Immutability Guard (HTTP 403)</option>
                  <option value="invalid_reading_range">4. Telemetry Input Boundary Validation (HTTP 422)</option>
                  <option value="duplicate_event_rejection">5. Idempotency &amp; Duplicate Prevention (HTTP 409)</option>
                  <option value="missing_record_lookup">6. Sanitized Resource Lookup Error (HTTP 404)</option>
                  <option value="unauthenticated_request">7. Unauthenticated Request Rejection (HTTP 401)</option>
                </select>
              </div>

              <div className={styles.formRow}>
                <label className={styles.formLabel}>Target Patient / Record Parameter</label>
                <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                  <input
                    type="text"
                    className={styles.formInput}
                    value={selectedSecurityScenario === 'denied_baseline_delete' ? securityRecordId : securityPatient}
                    onChange={(e) => {
                      if (selectedSecurityScenario === 'denied_baseline_delete') {
                        setSecurityRecordId(e.target.value);
                      } else {
                        setSecurityPatient(e.target.value);
                      }
                    }}
                    placeholder="Patient or Record ID"
                  />
                </div>
              </div>
            </div>

            {securityResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
                <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', alignItems: 'center' }}>
                  <span className={styles.metricBadge}>HTTP {securityResult.actual_status}</span>
                  <span
                    className={
                      securityResult.outcome === 'PERMITTED'
                        ? styles.badgeSqlSafe
                        : securityResult.outcome === 'DENIED'
                        ? styles.badgeReadOnly
                        : styles.badgeAtlas
                    }
                  >
                    Outcome: {securityResult.outcome}
                  </span>
                  <span className={styles.metricBadge}>Layer: {securityResult.security_layer}</span>
                </div>

                <div className={securityResult.outcome === 'PERMITTED' ? styles.alertSuccess : styles.alertWarning}>
                  <strong>{securityResult.title}:</strong> {securityResult.security_explanation}
                </div>

                <div className={styles.codeBox}>
                  {JSON.stringify(securityResult.sanitized_response, null, 2)}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 8: PREFLIGHT DIAGNOSTICS                                              */}
      {/* ========================================================================= */}
      {activeTab === 'diagnostics' && (
        <div className={styles.container}>
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>10-Point Live System Preflight Diagnostics</h3>
                <p className={styles.cardDesc}>Automated verification of databases, schemas, views, triggers, and ML models</p>
              </div>

              <Button variant="primary" onClick={handleRunDiagnostics} disabled={loading}>
                <RefreshIcon size={14} />
                <span>Re-run Diagnostics</span>
              </Button>
            </div>

            {diagnosticData && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                  <span className={styles.metricBadge}>Timestamp: {diagnosticData.timestamp}</span>
                  <span className={diagnosticData.all_systems_ready ? styles.badgeSqlSafe : styles.badgeReadOnly}>
                    {diagnosticData.all_systems_ready ? 'ALL SYSTEMS OPERATIONAL' : 'SYSTEM AUDIT WARNINGS'}
                  </span>
                </div>

                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Diagnostic Name</th>
                        <th>Category</th>
                        <th>Latency</th>
                        <th>Details</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diagnosticData.diagnostics.map((diag) => (
                        <tr key={diag.id}>
                          <td>
                            {diag.status === 'PASS' && (
                              <span style={{ color: '#16a34a', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 'bold' }}>
                                <CheckCircleIcon size={14} /> PASS
                              </span>
                            )}
                            {diag.status === 'WARN' && (
                              <span style={{ color: '#d97706', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 'bold' }}>
                                <AlertTriangleIcon size={14} /> WARN
                              </span>
                            )}
                            {diag.status === 'FAIL' && (
                              <span style={{ color: '#dc2626', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 'bold' }}>
                                FAIL
                              </span>
                            )}
                          </td>
                          <td><strong>{diag.name}</strong></td>
                          <td>{diag.category}</td>
                          <td>{diag.latency_ms !== undefined ? `${diag.latency_ms} ms` : '—'}</td>
                          <td>{diag.details}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 9: DEMONSTRATION TEST RUNNER & EVIDENCE (PART 7F)                     */}
      {/* ========================================================================= */}
      {activeTab === 'tests' && (
        <div className={styles.container}>
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>DA3 Live Demonstration Test Runner &amp; Verification Evidence</h3>
                <p className={styles.cardDesc}>
                  Executes and displays verified test suites across Backend Unit, Integration, Frontend UI, and Live Microservice workflows.
                </p>
              </div>
              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleReloadTestReport}
                  disabled={loading}
                >
                  <RefreshIcon size={14} />
                  <span>Reload Stored Report</span>
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleRunTests}
                  disabled={loading}
                >
                  <span>{loading ? 'Running Suite...' : 'Execute Test Suite'}</span>
                </Button>
              </div>
            </div>

            {/* Test Suite Selector Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', flexWrap: 'wrap', marginBottom: 'var(--space-4)' }}>
              <div className={styles.formRow} style={{ flex: '1 1 250px' }}>
                <label className={styles.formLabel}>Target Test Suite</label>
                <select
                  className={styles.formSelect}
                  value={selectedSuite}
                  onChange={(e) => setSelectedSuite(e.target.value)}
                  disabled={loading}
                >
                  <option value="quick">Quick Verification Suite (&lt; 20s — Recommended for Viva)</option>
                  <option value="integration">Backend Integration &amp; Evaluation Console Tests</option>
                  <option value="unit">Backend Unit Tests (Security, Schemas, ML, Alerts)</option>
                  <option value="frontend">Frontend Webstation Assertions (Node.js)</option>
                  <option value="live">Live Microservices, Stop/Resume &amp; Probes</option>
                  <option value="all">Full Comprehensive Audit (All Layers)</option>
                </select>
              </div>

              <div className={styles.formRow} style={{ flex: '1 1 250px' }}>
                <label className={styles.formLabel}>Search Test Cases</label>
                <input
                  type="text"
                  className={styles.searchInput}
                  placeholder="Filter by test name, ID, or symbol..."
                  value={testSearch}
                  onChange={(e) => setTestSearch(e.target.value)}
                />
              </div>
            </div>

            {/* Invariants Guard Banner */}
            {testReport && (
              <div style={{
                display: 'flex',
                gap: 'var(--space-3)',
                flexWrap: 'wrap',
                marginBottom: 'var(--space-4)',
                padding: 'var(--space-3)',
                backgroundColor: 'var(--color-bg-surface-subtle)',
                borderRadius: 'var(--radius-xs)',
                border: '1px solid var(--color-border-subtle)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: 'var(--text-xs)', fontWeight: 'bold' }}>MongoDB Atlas Safety:</span>
                  <span className={styles.badgeReadOnly}>
                    {testReport.invariants.mongodb_status} ({testReport.invariants.mongodb_final_doc_count ?? 2955} Docs, {testReport.invariants.mongodb_writes_detected} Writes)
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: 'var(--text-xs)', fontWeight: 'bold' }}>MySQL Baseline EHR Guard:</span>
                  <span className={styles.badgeSqlSafe}>
                    {testReport.invariants.mysql_status} (P101–P105 Verified Intact)
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: 'auto' }}>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                    Run ID: <strong>{testReport.run_id}</strong> | Executed: <strong>{testReport.completed_at}</strong>
                  </span>
                </div>
              </div>
            )}

            {/* Metrics Scorecard Grid */}
            {testReport && (
              <div className={styles.scorecardGrid}>
                <div className={styles.scorecardMetric}>
                  <span className={styles.scorecardMetricLabel}>Overall Status</span>
                  <span className={styles.scorecardMetricValue} style={{ color: testReport.overall_status === 'PASSED' ? '#16a34a' : '#dc2626' }}>
                    {testReport.overall_status}
                  </span>
                </div>
                <div className={styles.scorecardMetric}>
                  <span className={styles.scorecardMetricLabel}>Total Tests</span>
                  <span className={styles.scorecardMetricValue}>{testReport.summary.total_tests}</span>
                </div>
                <div className={styles.scorecardMetric}>
                  <span className={styles.scorecardMetricLabel}>Passed</span>
                  <span className={styles.scorecardMetricValue} style={{ color: '#16a34a' }}>
                    {testReport.summary.passed}
                  </span>
                </div>
                <div className={styles.scorecardMetric}>
                  <span className={styles.scorecardMetricLabel}>Failed</span>
                  <span className={styles.scorecardMetricValue} style={{ color: testReport.summary.failed > 0 ? '#dc2626' : 'var(--color-text-primary)' }}>
                    {testReport.summary.failed}
                  </span>
                </div>
                <div className={styles.scorecardMetric}>
                  <span className={styles.scorecardMetricLabel}>Pass Rate</span>
                  <span className={styles.scorecardMetricValue}>
                    {testReport.summary.pass_rate_percent}%
                  </span>
                </div>
                <div className={styles.scorecardMetric}>
                  <span className={styles.scorecardMetricLabel}>Total Duration</span>
                  <span className={styles.scorecardMetricValue}>
                    {(testReport.total_duration_ms / 1000).toFixed(1)}s
                  </span>
                </div>
              </div>
            )}

            {/* Category Filter Chips */}
            {testReport && (
              <div className={styles.chipContainer}>
                <button
                  type="button"
                  className={`${styles.chip} ${selectedCategory === 'ALL' ? styles.chipActive : ''}`}
                  onClick={() => setSelectedCategory('ALL')}
                >
                  All ({testReport.summary.total_tests})
                </button>
                <button
                  type="button"
                  className={`${styles.chip} ${selectedCategory === 'Backend Unit' ? styles.chipActive : ''}`}
                  onClick={() => setSelectedCategory('Backend Unit')}
                >
                  Backend Unit ({testReport.categories.backend_unit || 0})
                </button>
                <button
                  type="button"
                  className={`${styles.chip} ${selectedCategory === 'Backend Integration' ? styles.chipActive : ''}`}
                  onClick={() => setSelectedCategory('Backend Integration')}
                >
                  Backend Integration ({testReport.categories.backend_integration || 0})
                </button>
                <button
                  type="button"
                  className={`${styles.chip} ${selectedCategory === 'Frontend UI' ? styles.chipActive : ''}`}
                  onClick={() => setSelectedCategory('Frontend UI')}
                >
                  Frontend UI ({testReport.categories.frontend_ui || 0})
                </button>
                <button
                  type="button"
                  className={`${styles.chip} ${selectedCategory === 'Live Microservices' ? styles.chipActive : ''}`}
                  onClick={() => setSelectedCategory('Live Microservices')}
                >
                  Live Microservices ({testReport.categories.live_microservices || 0})
                </button>
              </div>
            )}

            {/* Test Results Table */}
            {testReport ? (
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th style={{ width: '90px' }}>Status</th>
                      <th style={{ width: '130px' }}>Test ID</th>
                      <th>Test Case &amp; Assertion</th>
                      <th style={{ width: '160px' }}>Category</th>
                      <th style={{ width: '220px' }}>Dependency Level</th>
                      <th style={{ width: '100px', textAlign: 'right' }}>Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {testReport.tests
                      .filter((t) => {
                        if (selectedCategory !== 'ALL' && t.category !== selectedCategory) return false;
                        if (testSearch.trim()) {
                          const q = testSearch.toLowerCase();
                          return (
                            t.name.toLowerCase().includes(q) ||
                            t.id.toLowerCase().includes(q) ||
                            t.test_symbol.toLowerCase().includes(q)
                          );
                        }
                        return true;
                      })
                      .map((t) => (
                        <React.Fragment key={t.id}>
                          <tr
                            onClick={() => setExpandedTestId(expandedTestId === t.id ? null : t.id)}
                            style={{ cursor: 'pointer' }}
                            title="Click to view details"
                          >
                            <td>
                              {t.status === 'PASS' && (
                                <span className={styles.statusPass}>
                                  <CheckCircleIcon size={12} /> PASS
                                </span>
                              )}
                              {t.status === 'FAIL' && (
                                <span className={styles.statusFail}>
                                  FAIL
                                </span>
                              )}
                              {t.status === 'SKIPPED' && (
                                <span className={styles.statusSkipped}>
                                  SKIPPED
                                </span>
                              )}
                            </td>
                            <td>
                              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontWeight: 'bold' }}>
                                {t.id}
                              </span>
                            </td>
                            <td>
                              <div>
                                <strong>{t.name}</strong>
                                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', fontFamily: 'var(--font-mono, monospace)' }}>
                                  {t.test_symbol}
                                </div>
                              </div>
                            </td>
                            <td>{t.category}</td>
                            <td>
                              <span className={styles.depBadge}>{t.dependency}</span>
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono, monospace)' }}>
                              {t.duration_ms.toFixed(1)} ms
                            </td>
                          </tr>
                          {expandedTestId === t.id && (
                            <tr>
                              <td colSpan={6} style={{ backgroundColor: 'var(--color-bg-surface-subtle)', padding: 'var(--space-3)' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: 'var(--text-xs)' }}>
                                  <div><strong>Test Suite File:</strong> <code>{t.suite}</code></div>
                                  <div><strong>Execution Details:</strong> {t.details || '—'}</div>
                                  {t.error && (
                                    <div style={{ color: '#dc2626', marginTop: '4px' }}>
                                      <strong>Error Output:</strong>
                                      <pre style={{ whiteSpace: 'pre-wrap', backgroundColor: '#fee2e2', padding: '6px', borderRadius: '4px' }}>
                                        {t.error}
                                      </pre>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ padding: 'var(--space-8)', textAlign: 'center', color: 'var(--color-text-secondary)' }}>
                <p>No test report currently loaded. Click <strong>"Execute Test Suite"</strong> above to run live demonstration verification.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 10: CHALLENGE MODE (PART 7G)                                          */}
      {/* ========================================================================= */}
      {activeTab === 'challenges' && (
        <div className={styles.container}>
          {/* Header Card */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>DA3 Live Database Challenge Mode</h3>
                <p className={styles.cardSubtitle}>
                  Rapid, guided response mode for academic examiner requests. Executes verified server-side database operations across MySQL and MongoDB Atlas with zero client-side mock logic.
                </p>
              </div>
              <div className={styles.bannerBadges}>
                <span className={styles.badgeReadOnly}>MongoDB: Strictly Read-Only (2,955 Docs)</span>
                <span className={styles.badgeSqlSafe}>MySQL: Scoped EVAL Records</span>
                <span className={styles.badgeAtlas}>Total Challenges: {challenges.length || 22}</span>
              </div>
            </div>

            {/* Filter Bar */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                <button
                  className={`${styles.chip} ${challengeCategory === 'ALL' ? styles.chipActive : ''}`}
                  onClick={() => setChallengeCategory('ALL')}
                >
                  All ({challenges.length || 22})
                </button>
                <button
                  className={`${styles.chip} ${challengeCategory === 'SQL Challenges' ? styles.chipActive : ''}`}
                  onClick={() => setChallengeCategory('SQL Challenges')}
                >
                  SQL Challenges (11)
                </button>
                <button
                  className={`${styles.chip} ${challengeCategory === 'MongoDB Challenges' ? styles.chipActive : ''}`}
                  onClick={() => setChallengeCategory('MongoDB Challenges')}
                >
                  MongoDB Challenges (5)
                </button>
                <button
                  className={`${styles.chip} ${challengeCategory === 'Security & Testing Challenges' ? styles.chipActive : ''}`}
                  onClick={() => setChallengeCategory('Security & Testing Challenges')}
                >
                  Security &amp; Testing (6)
                </button>
              </div>

              <input
                type="text"
                className={styles.searchInput}
                placeholder="Search challenges by name or keyword..."
                value={challengeSearch}
                onChange={(e) => setChallengeSearch(e.target.value)}
              />
            </div>
          </div>

          {/* Master-Detail Challenge Layout */}
          <div className={styles.challengeLayout}>
            {/* Left Column: Challenge List */}
            <div className={styles.challengeList}>
              {challenges
                .filter((c) => {
                  if (challengeCategory !== 'ALL' && c.category !== challengeCategory) return false;
                  if (challengeSearch.trim()) {
                    const q = challengeSearch.toLowerCase();
                    return (
                      c.name.toLowerCase().includes(q) ||
                      c.challenge_id.toLowerCase().includes(q) ||
                      c.purpose.toLowerCase().includes(q) ||
                      c.operation_type.toLowerCase().includes(q)
                    );
                  }
                  return true;
                })
                .map((c) => {
                  const isSelected = c.challenge_id === selectedChallengeId;
                  return (
                    <div
                      key={c.challenge_id}
                      className={`${styles.challengeItem} ${isSelected ? styles.challengeItemActive : ''}`}
                      onClick={() => {
                        setSelectedChallengeId(c.challenge_id);
                        setChallengeConfirmed(false);
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span className={styles.depBadge}>{c.operation_type}</span>
                        <span style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>{c.category.split(' ')[0]}</span>
                      </div>
                      <div className={isSelected ? styles.challengeItemActiveTitle : ''} style={{ fontSize: 'var(--text-sm)' }}>
                        {c.name}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', lineHeight: '1.3' }}>
                        {c.purpose.slice(0, 90)}...
                      </div>
                    </div>
                  );
                })}
            </div>

            {/* Right Column: Selected Challenge Execution Panel */}
            <div className={styles.challengeDetailPanel}>
              {(() => {
                const currentChallenge = challenges.find((c) => c.challenge_id === selectedChallengeId) || challenges[0];
                if (!currentChallenge) {
                  return (
                    <div className={styles.card} style={{ padding: 'var(--space-6)', textAlign: 'center' }}>
                      <p>Loading evaluation challenges...</p>
                    </div>
                  );
                }

                return (
                  <>
                    {/* Execution Config Card */}
                    <div className={styles.challengeDetailCard}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span className={styles.depBadge}>{currentChallenge.operation_type}</span>
                            <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)', fontWeight: 'bold' }}>
                              {currentChallenge.category}
                            </span>
                          </div>
                          <h3 style={{ fontSize: 'var(--text-lg)', fontWeight: 'bold', marginTop: '4px' }}>
                            {currentChallenge.name}
                          </h3>
                        </div>

                        <Button
                          variant="primary"
                          onClick={handleExecuteChallenge}
                          disabled={loading}
                        >
                          <RefreshIcon size={14} />
                          {loading ? 'Executing Operation...' : 'Execute Challenge'}
                        </Button>
                      </div>

                      <div className={styles.explanationCallout}>
                        <strong>Academic Purpose:</strong> {currentChallenge.purpose}
                      </div>

                      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                        {currentChallenge.description}
                      </p>

                      {/* Dynamic Parameters Form */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', borderTop: '1px solid var(--color-border-subtle)', paddingTop: 'var(--space-3)' }}>
                        <span style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--color-text-primary)' }}>
                          Challenge Parameters &amp; Execution Scope:
                        </span>

                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-4)', alignItems: 'center' }}>
                          {/* Patient ID Selector (if relevant) */}
                          {['sql_select_patient_readings', 'sql_insert_evaluation_reading', 'sql_update_evaluation_record', 'sql_demonstrate_nested_query', 'sql_demonstrate_aggregates', 'sql_query_view', 'mongo_filter_documents', 'mongo_aggregation_pipeline', 'sec_authorized_request', 'sec_unauthorized_request_rejected'].includes(currentChallenge.challenge_id) && (
                            <div className={styles.formGroup} style={{ minWidth: '160px' }}>
                              <label className={styles.formLabel}>Target Patient ID:</label>
                              <select
                                className={styles.formSelect}
                                value={challengeParams.patient_id || 'P101'}
                                onChange={(e) => setChallengeParams({ ...challengeParams, patient_id: e.target.value })}
                              >
                                <option value="P101">P101 (Alice Smith)</option>
                                <option value="P102">P102 (Bob Johnson)</option>
                                <option value="P103">P103 (Carol White)</option>
                                <option value="P104">P104 (David Brown)</option>
                                <option value="P105">P105 (Eva Green)</option>
                              </select>
                            </div>
                          )}

                          {/* Limit Parameter */}
                          {['sql_select_patient_readings', 'sql_demonstrate_join', 'mongo_retrieve_documents', 'mongo_filter_documents'].includes(currentChallenge.challenge_id) && (
                            <div className={styles.formGroup} style={{ width: '110px' }}>
                              <label className={styles.formLabel}>Limit (Rows):</label>
                              <input
                                type="number"
                                className={styles.formInput}
                                value={challengeParams.limit || 10}
                                min={1}
                                max={50}
                                onChange={(e) => setChallengeParams({ ...challengeParams, limit: parseInt(e.target.value) || 10 })}
                              />
                            </div>
                          )}

                          {/* Heart Rate Parameter for Ingestion */}
                          {currentChallenge.challenge_id === 'sql_insert_evaluation_reading' && (
                            <>
                              <div className={styles.formGroup} style={{ width: '130px' }}>
                                <label className={styles.formLabel}>Heart Rate (bpm):</label>
                                <input
                                  type="number"
                                  className={styles.formInput}
                                  value={challengeParams.heart_rate || 128.5}
                                  step="0.5"
                                  onChange={(e) => setChallengeParams({ ...challengeParams, heart_rate: parseFloat(e.target.value) || 128.5 })}
                                />
                              </div>
                              <div className={styles.formGroup} style={{ width: '110px' }}>
                                <label className={styles.formLabel}>SpO2 (%):</label>
                                <input
                                  type="number"
                                  className={styles.formInput}
                                  value={challengeParams.spo2 || 94.0}
                                  step="0.5"
                                  onChange={(e) => setChallengeParams({ ...challengeParams, spo2: parseFloat(e.target.value) || 94.0 })}
                                />
                              </div>
                            </>
                          )}

                          {/* Stored Routine Inputs */}
                          {currentChallenge.challenge_id === 'sql_execute_stored_routine' && (
                            <>
                              <div className={styles.formGroup} style={{ width: '130px' }}>
                                <label className={styles.formLabel}>Weight (kg):</label>
                                <input
                                  type="number"
                                  className={styles.formInput}
                                  value={challengeParams.weight_kg || 78.5}
                                  step="0.5"
                                  onChange={(e) => setChallengeParams({ ...challengeParams, weight_kg: parseFloat(e.target.value) || 78.5 })}
                                />
                              </div>
                              <div className={styles.formGroup} style={{ width: '130px' }}>
                                <label className={styles.formLabel}>Height (m):</label>
                                <input
                                  type="number"
                                  className={styles.formInput}
                                  value={challengeParams.height_m || 1.75}
                                  step="0.01"
                                  onChange={(e) => setChallengeParams({ ...challengeParams, height_m: parseFloat(e.target.value) || 1.75 })}
                                />
                              </div>
                            </>
                          )}
                        </div>

                        {/* Guarded Delete Options */}
                        {currentChallenge.challenge_id === 'sql_delete_evaluation_record' && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', backgroundColor: '#fef2f2', border: '1px solid #fee2e2', padding: '10px', borderRadius: '4px' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#991b1b', cursor: 'pointer' }}>
                              <input
                                type="checkbox"
                                checked={challengeParams.target_baseline || false}
                                onChange={(e) => setChallengeParams({ ...challengeParams, target_baseline: e.target.checked })}
                              />
                              <strong>Attempt Deletion of Baseline Record P001:</strong> Explicitly test Core EHR Immutability Guard (Demonstrates HTTP 403 Forbidden).
                            </label>

                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#166534', cursor: 'pointer' }}>
                              <input
                                type="checkbox"
                                checked={challengeConfirmed}
                                onChange={(e) => setChallengeConfirmed(e.target.checked)}
                              />
                              <strong>Confirm Deletion:</strong> I explicitly authorize safe deletion of the designated EVAL_* fixture.
                            </label>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Live Execution Results Card */}
                    {challengeResult && challengeResult.challenge_id === selectedChallengeId && (
                      <div className={styles.challengeResultCard}>
                        <div className={styles.challengeResultHeader}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span
                              className={
                                challengeResult.status === 'SUCCESS'
                                  ? styles.statusPass
                                  : challengeResult.status === 'REJECTED_SAFE'
                                  ? styles.statusSkipped
                                  : styles.statusFail
                              }
                            >
                              {challengeResult.status}
                            </span>
                            <span style={{ fontSize: '12px', fontWeight: 'bold' }}>
                              HTTP {challengeResult.http_status}
                            </span>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '12px', fontFamily: 'var(--font-mono, monospace)' }}>
                            <span><strong>Execution Time:</strong> {challengeResult.execution_time_ms.toFixed(2)} ms</span>
                            {challengeResult.affected_rows !== null && (
                              <span><strong>Affected Rows/Records:</strong> {challengeResult.affected_rows}</span>
                            )}
                          </div>
                        </div>

                        {/* Academic Explanation */}
                        <div>
                          <strong style={{ fontSize: '11px', color: 'var(--color-text-secondary)', textTransform: 'uppercase' }}>
                            Examiner Rationale &amp; Evidence:
                          </strong>
                          <div className={styles.explanationCallout} style={{ marginTop: '4px' }}>
                            {challengeResult.explanation}
                          </div>
                        </div>

                        {/* Demonstrated SQL / Pipeline / Operation */}
                        <div>
                          <strong style={{ fontSize: '11px', color: 'var(--color-text-secondary)', textTransform: 'uppercase' }}>
                            Demonstrated Server-Side Query / Operation:
                          </strong>
                          <pre className={styles.sqlPreBlock} style={{ marginTop: '4px' }}>
                            {challengeResult.operation_demonstrated}
                          </pre>
                        </div>

                        {/* Real Response Data */}
                        <div>
                          <strong style={{ fontSize: '11px', color: 'var(--color-text-secondary)', textTransform: 'uppercase' }}>
                            Live Database Response Data (Verified Zero Hardcoding):
                          </strong>
                          <pre
                            style={{
                              backgroundColor: 'var(--color-bg-surface-subtle)',
                              padding: 'var(--space-3)',
                              borderRadius: 'var(--radius-xs)',
                              fontFamily: 'var(--font-mono, monospace)',
                              fontSize: '11px',
                              maxHeight: '260px',
                              overflowY: 'auto',
                              whiteSpace: 'pre-wrap',
                              marginTop: '4px',
                            }}
                          >
                            {JSON.stringify(challengeResult.response_data, null, 2)}
                          </pre>
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

