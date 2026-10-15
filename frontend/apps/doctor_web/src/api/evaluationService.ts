/**
 * SMART HEALTH MONITORING SYSTEM — DA3 EVALUATION CONSOLE API SERVICE
 * 
 * Strict architectural boundaries:
 * 1. Consumes exclusively central FastAPI gateway endpoints (/api/v1/evaluation/...).
 * 2. MongoDB endpoints are strictly READ-ONLY (no write operations).
 * 3. SQL operations are named and parameterized; no raw SQL execution.
 * 4. CRUD operations are restricted to EVAL_* test fixtures to protect baseline EHR data.
 */

import { apiRequest } from './client';

export interface EvaluationRecord {
  record_id: string;
  patient_id: string;
  record_type: string;
  title: string;
  content: string;
  created_by: string;
  created_at: string;
  is_evaluation: boolean;
}

export interface CreateRecordPayload {
  patient_id: string;
  title: string;
  content: string;
  record_type?: string;
  created_by?: string;
}

export interface UpdateRecordPayload {
  title?: string;
  content?: string;
  record_type?: string;
}

export interface DeleteRecordResponse {
  status: string;
  record_id: string;
  message: string;
  timestamp: string;
}

export interface DemoReadingPayload {
  patient_id: string;
  heart_rate: number;
  spo2: number;
  temperature_c: number;
  device_id?: string;
}

export interface DemoReadingResponse {
  status: string;
  event_id: string;
  patient_id: string;
  timestamp: string;
  readings_created: number;
  alert_generated: boolean;
  alert_details?: {
    alert_id?: string;
    severity?: string;
    category?: string;
    reason?: string;
  };
}

export interface SqlDemoPayload {
  query_name: string;
  patient_id?: string;
  limit?: number;
}

export interface SqlDemoResponse {
  query_name: string;
  description: string;
  sql_syntax: string;
  execution_time_ms: number;
  row_count: number;
  columns: string[];
  rows: Record<string, any>[];
}

export interface SqlExplainResponse {
  query_type: string;
  description: string;
  target_table: string;
  index_used: string | null;
  scan_type: string;
  execution_time_ms: number;
  rows_examined: number;
  rows_returned: number;
  filter_condition: string;
  analysis: string;
  raw_plan: Record<string, any>[];
}

export interface ViewQueryResponse {
  view_name: string;
  description: string;
  view_definition: string;
  row_count: number;
  columns: string[];
  data: Record<string, any>[];
}

export interface StoredFunctionResponse {
  function_name: string;
  input_params: Record<string, any>;
  result: any;
  interpretation: string;
  sql_definition: string;
}

export interface StoredProcedureResponse {
  procedure_name: string;
  input_params: Record<string, any>;
  status: string;
  message: string;
  transaction_outcome: string;
  sql_definition: string;
  affected_records?: Record<string, any>[];
}

export interface TriggerHistoryItem {
  history_id: number;
  alert_id: string;
  old_status: string | null;
  new_status: string;
  actor_id: string;
  note: string | null;
  changed_at: string;
}

export interface TriggerHistoryResponse {
  alert_id: string;
  trigger_name: string;
  trigger_event: string;
  trigger_definition: string;
  history_count: number;
  history_records: TriggerHistoryItem[];
}

export interface MongoStatusResponse {
  is_connected: boolean;
  is_read_only_enforced: boolean;
  sanitized_endpoint: string;
  latency_ms: number;
  database_name: string;
  collections_count: number;
  collections: Record<string, { document_count: number; indexes_count: number }>;
  outbox_queue: {
    pending_sync_count: number;
    sync_enabled: boolean;
    sync_policy: string;
  };
}

export interface MongoCollectionInfo {
  name: string;
  document_count: number;
  indexes_count: number;
  indexes: Array<{
    name: string;
    keys: Array<[string, number]>;
    unique?: boolean;
    sparse?: boolean;
  }>;
}

export interface MongoDocumentListResponse {
  collection_name: string;
  total_count: number;
  limit: number;
  skip: number;
  has_more: boolean;
  documents: Record<string, any>[];
}

export interface MongoIndexInfoResponse {
  collection_name: string;
  indexes: Array<{
    name: string;
    keys: Array<[string, number]>;
    unique?: boolean;
    sparse?: boolean;
  }>;
}

export interface MongoExplainResponse {
  collection_name: string;
  query_type: string;
  query_filter: Record<string, any>;
  winning_stage: string;
  index_used: string | null;
  execution_time_ms: number;
  total_docs_examined: number;
  total_keys_examined: number;
  docs_returned: number;
  analysis: string;
  raw_plan: Record<string, any>;
}

export interface MongoAggregateResponse {
  pipeline_name: string;
  description: string;
  pipeline_json: string;
  execution_time_ms: number;
  result_count: number;
  results: Record<string, any>[];
}

export interface BenchmarkWorkload {
  workload_id: string;
  category: string;
  target_engine: string;
  description: string;
  latency_ms: number;
  throughput_qps: number;
  p95_latency_ms: number;
  status: string;
}

export interface BenchmarkSummaryResponse {
  benchmark_timestamp: string;
  test_environment: {
    os: string;
    runtime: string;
    relational_db: string;
    nosql_db: string;
    dataset_telemetry_records: number;
  };
  workloads: BenchmarkWorkload[];
  test_scorecard: {
    total_backend_tests: number;
    passed_backend_tests: number;
    backend_pass_rate: string;
    frontend_tests: number;
    frontend_pass_rate: string;
    consistency_verdict: string;
    recovery_verdict: string;
  };
}

export interface PreflightDiagnosticItem {
  id: string;
  name: string;
  category: string;
  status: 'PASS' | 'WARN' | 'FAIL';
  details: string;
  latency_ms?: number;
}

export interface PreflightDiagnosticResponse {
  timestamp: string;
  all_systems_ready: boolean;
  diagnostics: PreflightDiagnosticItem[];
}

export interface RbacTestResponse {
  caller_role: string;
  caller_id: string;
  permissions: Record<string, boolean>;
  access_matrix: Array<{
    role: string;
    view_assigned: boolean;
    view_all: boolean;
    ack_alerts: boolean;
    delete_eval: boolean;
  }>;
}

export interface SecurityDemonstrationResponse {
  scenario: string;
  title: string;
  expected_status: number;
  actual_status: number;
  outcome: 'PERMITTED' | 'DENIED' | 'VALIDATION_FAILED' | 'NOT_FOUND' | 'CONFLICT_HANDLED';
  security_layer: string;
  security_explanation: string;
  sanitized_response: Record<string, any>;
  timestamp: string;
}

export const evaluationService = {
  // --- CRUD OPERATIONS ---
  async getRecords(patientId?: string): Promise<EvaluationRecord[]> {
    const qs = patientId ? `?patient_id=${encodeURIComponent(patientId)}` : '';
    return apiRequest<EvaluationRecord[]>(`/evaluation/crud/records${qs}`);
  },

  async createRecord(payload: CreateRecordPayload): Promise<EvaluationRecord> {
    return apiRequest<EvaluationRecord>('/evaluation/crud/records', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async updateRecord(recordId: string, payload: UpdateRecordPayload): Promise<EvaluationRecord> {
    return apiRequest<EvaluationRecord>(`/evaluation/crud/records/${encodeURIComponent(recordId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  },

  async deleteRecord(recordId: string): Promise<DeleteRecordResponse> {
    return apiRequest<DeleteRecordResponse>(`/evaluation/crud/records/${encodeURIComponent(recordId)}`, {
      method: 'DELETE',
    });
  },

  async insertDemoReading(payload: DemoReadingPayload): Promise<DemoReadingResponse> {
    return apiRequest<DemoReadingResponse>('/evaluation/crud/readings', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // --- SQL DEMONSTRATIONS ---
  async demonstrateSql(payload: SqlDemoPayload): Promise<SqlDemoResponse> {
    return apiRequest<SqlDemoResponse>('/evaluation/sql/demonstrate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async explainSql(queryType: 'covering_index' | 'full_table_scan'): Promise<SqlExplainResponse> {
    return apiRequest<SqlExplainResponse>('/evaluation/sql/explain', {
      method: 'POST',
      body: JSON.stringify({ query_type: queryType }),
    });
  },

  // --- DATABASE OBJECTS ---
  async queryView(viewName: 'v_latest_patient_vitals' | 'v_patient_active_alerts'): Promise<ViewQueryResponse> {
    return apiRequest<ViewQueryResponse>(`/evaluation/db-objects/views/${viewName}`);
  },

  async runStoredFunction(functionName: 'calculate-bmi' | 'fever-category', params: Record<string, any>): Promise<StoredFunctionResponse> {
    return apiRequest<StoredFunctionResponse>(`/evaluation/db-objects/stored-functions/${functionName}`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  async runStoredProcedure(procedureName: 'acknowledge-alert' | 'safe-discharge', params: Record<string, any>): Promise<StoredProcedureResponse> {
    return apiRequest<StoredProcedureResponse>(`/evaluation/db-objects/stored-procedures/${procedureName}`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  async getTriggerHistory(alertId: string): Promise<TriggerHistoryResponse> {
    return apiRequest<TriggerHistoryResponse>(`/evaluation/db-objects/triggers/history/${encodeURIComponent(alertId)}`);
  },

  async testTriggerUpdate(alertId: string, newStatus: string): Promise<any> {
    return apiRequest('/evaluation/db-objects/triggers/test-update', {
      method: 'POST',
      body: JSON.stringify({ alert_id: alertId, new_status: newStatus }),
    });
  },

  // --- MONGODB READ-ONLY OPERATIONS ---
  async getMongoStatus(): Promise<MongoStatusResponse> {
    return apiRequest<MongoStatusResponse>('/evaluation/mongodb/status');
  },

  async getMongoCollections(): Promise<MongoCollectionInfo[]> {
    return apiRequest<MongoCollectionInfo[]>('/evaluation/mongodb/collections');
  },

  async getMongoDocuments(
    collectionName: string,
    params?: { limit?: number; skip?: number; patient_id?: string; source?: string; is_simulated?: boolean }
  ): Promise<MongoDocumentListResponse> {
    const searchParams = new URLSearchParams();
    if (params?.limit !== undefined) searchParams.set('limit', params.limit.toString());
    if (params?.skip !== undefined) searchParams.set('skip', params.skip.toString());
    if (params?.patient_id) searchParams.set('patient_id', params.patient_id);
    if (params?.source) searchParams.set('source', params.source);
    if (params?.is_simulated !== undefined) searchParams.set('is_simulated', params.is_simulated.toString());
    const qs = searchParams.toString() ? `?${searchParams.toString()}` : '';
    return apiRequest<MongoDocumentListResponse>(`/evaluation/mongodb/collections/${encodeURIComponent(collectionName)}/documents${qs}`);
  },

  async getMongoIndexes(collectionName: string): Promise<MongoIndexInfoResponse> {
    return apiRequest<MongoIndexInfoResponse>(`/evaluation/mongodb/collections/${encodeURIComponent(collectionName)}/indexes`);
  },

  async explainMongoQuery(payload: {
    collection_name: string;
    query_type: 'indexed' | 'unindexed';
    patient_id?: string;
  }): Promise<MongoExplainResponse> {
    return apiRequest<MongoExplainResponse>('/evaluation/mongodb/explain', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async aggregateMongo(payload: {
    pipeline_name: string;
    patient_id?: string;
  }): Promise<MongoAggregateResponse> {
    return apiRequest<MongoAggregateResponse>('/evaluation/mongodb/aggregate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // --- BENCHMARKS & DIAGNOSTICS ---
  async getBenchmarkSummary(): Promise<BenchmarkSummaryResponse> {
    return apiRequest<BenchmarkSummaryResponse>('/evaluation/benchmarks/summary');
  },

  async runPreflightDiagnostics(): Promise<PreflightDiagnosticResponse> {
    return apiRequest<PreflightDiagnosticResponse>('/evaluation/diagnostics/preflight', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },

  // --- SECURITY & ACCESS CONTROL ---
  async getRbacTest(): Promise<RbacTestResponse> {
    return apiRequest<RbacTestResponse>('/evaluation/security/rbac-test');
  },

  async demonstrateSecurity(scenario: string, patientId?: string, recordId?: string): Promise<SecurityDemonstrationResponse> {
    return apiRequest<SecurityDemonstrationResponse>('/evaluation/security/demonstrate', {
      method: 'POST',
      body: JSON.stringify({ scenario, patient_id: patientId, record_id: recordId }),
    });
  },

  // --- TEST RUNNER & VERIFICATION SCORECARD (PART 7F) ---
  async getLatestTestReport(): Promise<TestRunnerReportResponse> {
    return apiRequest<TestRunnerReportResponse>('/evaluation/test-runner/latest');
  },

  async runDemonstrationTests(suiteType: string = 'quick'): Promise<TestRunnerReportResponse> {
    return apiRequest<TestRunnerReportResponse>('/evaluation/test-runner/run', {
      method: 'POST',
      body: JSON.stringify({ suite_type: suiteType }),
    });
  },

  // --- CHALLENGE MODE (PART 7G) ---
  async getChallenges(): Promise<ChallengeMetadata[]> {
    return apiRequest<ChallengeMetadata[]>('/evaluation/challenges');
  },

  async executeChallenge(payload: {
    challenge_id: string;
    parameters?: Record<string, any>;
    confirmed?: boolean;
  }): Promise<ChallengeExecuteResponse> {
    return apiRequest<ChallengeExecuteResponse>('/evaluation/challenges/execute', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};

export interface TestItem {
  id: string;
  name: string;
  test_symbol: string;
  suite: string;
  category: string;
  status: 'PASS' | 'FAIL' | 'SKIPPED' | 'NOT_EXECUTED';
  duration_ms: number;
  dependency: string;
  details?: string | null;
  error?: string | null;
}

export interface TestRunnerSummary {
  total_tests: number;
  passed: number;
  failed: number;
  skipped: number;
  pass_rate_percent: number;
}

export interface TestRunnerInvariants {
  mongodb_read_only_enforced: boolean;
  mongodb_initial_doc_count?: number | null;
  mongodb_final_doc_count?: number | null;
  mongodb_writes_detected: number;
  mongodb_status: string;
  mysql_baseline_ehr_intact: boolean;
  mysql_status: string;
}

export interface TestRunnerReportResponse {
  report_schema_version: string;
  run_id: string;
  suite_type: string;
  overall_status: string;
  started_at: string;
  completed_at: string;
  total_duration_ms: number;
  summary: TestRunnerSummary;
  invariants: TestRunnerInvariants;
  categories: Record<string, number>;
  tests: TestItem[];
}

export interface ChallengeMetadata {
  challenge_id: string;
  category: 'SQL Challenges' | 'MongoDB Challenges' | 'Security & Testing Challenges';
  name: string;
  purpose: string;
  operation_type: string;
  requires_confirmation: boolean;
  allowed_parameters: Record<string, any>;
  description: string;
}

export interface ChallengeExecuteResponse {
  challenge_id: string;
  name: string;
  category: string;
  purpose: string;
  operation_demonstrated: string;
  status: 'SUCCESS' | 'REJECTED_SAFE' | 'VALIDATION_ERROR' | 'FAILED';
  http_status: number;
  execution_time_ms: number;
  affected_rows: number | null;
  response_data: any;
  explanation: string;
  timestamp_utc: string;
}


