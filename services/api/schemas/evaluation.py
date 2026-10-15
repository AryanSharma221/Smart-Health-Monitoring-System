"""
Pydantic Schemas for the DA3 Evaluation Console.

Provides structured request and response contracts for:
- Isolated evaluation CRUD operations (EVAL_* records).
- Parameterized SQL demonstrations and execution plans.
- Database objects (views, stored functions, stored procedures, triggers).
- MongoDB analytics aggregation pipelines.
- Performance benchmarks and RBAC security testing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class EvaluationRecordCreate(BaseModel):
    """Payload to create an isolated evaluation record."""
    patient_id: str = Field("P101", description="Approved test patient ID (P101-P105)")
    record_type: str = Field("clinical_note", description="Category: clinical_note, triage_assessment, observation")
    title: str = Field(..., min_length=1, max_length=255, description="Brief summary title")
    content_text: str = Field(..., min_length=1, description="Clinical evaluation text body")
    status: str = Field("ACTIVE", description="Initial lifecycle status")


class EvaluationRecordUpdate(BaseModel):
    """Payload to update an existing evaluation record."""
    title: Optional[str] = Field(None, max_length=255)
    content_text: Optional[str] = None
    status: Optional[str] = None
    record_type: Optional[str] = None


class EvaluationRecordResponse(BaseModel):
    """Evaluation record representation with provenance metadata."""
    model_config = ConfigDict(from_attributes=True)

    record_id: str
    patient_id: str
    record_type: str
    title: str
    content_text: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class DemoReadingCreate(BaseModel):
    """Payload to inject a controlled vitals reading into the ingestion pipeline."""
    patient_id: str = Field("P101", description="Target test patient ID")
    heart_rate: Optional[float] = Field(78.0, ge=20.0, le=300.0, description="Heart rate in bpm")
    spo2: Optional[float] = Field(98.0, ge=50.0, le=100.0, description="SpO2 percentage")
    temperature_f: Optional[float] = Field(98.6, ge=70.0, le=120.0, description="Temperature in Fahrenheit")
    source: Optional[str] = Field("demo-simulator", description="Provenance marker")


class DemoReadingResponse(BaseModel):
    """Outcome of controlled reading injection."""
    event_id: str
    patient_id: str
    outcome: str
    measured_at: datetime
    vitals_created: int
    alert_created: bool
    alert_detail: Optional[str] = None
    outbox_staged: bool


class SqlDemonstrationRequest(BaseModel):
    """Request to execute a predefined named SQL query."""
    query_name: str = Field(
        ...,
        description=(
            "Named query: 'basic_filter', 'inner_join', 'multi_join', "
            "'nested_subquery', 'aggregate_moments', 'group_by_having', 'left_outer_join'"
        ),
    )
    patient_id: Optional[str] = Field("P101", description="Target patient ID parameter")
    limit: Optional[int] = Field(50, ge=1, le=200, description="Result limit")


class SqlDemonstrationResponse(BaseModel):
    """Results and execution metadata of a named SQL query."""
    query_name: str
    title: str
    description: str
    sql_text: str
    execution_time_ms: float
    row_count: int
    columns: List[str]
    rows: List[Dict[str, Any]]


class SqlExplainRequest(BaseModel):
    """Request to generate execution plan for comparison."""
    query_type: str = Field("indexed", description="'indexed' or 'unindexed'")
    patient_id: Optional[str] = Field("P101")


class SqlExplainResponse(BaseModel):
    """Query execution plan output with index optimization analysis."""
    query_type: str
    sql_text: str
    execution_time_ms: float
    plan_rows: List[Dict[str, Any]]
    index_used: Optional[str]
    scan_type: str
    analysis: str


class StoredFunctionBmiRequest(BaseModel):
    """Input parameters for BMI calculation routine."""
    weight_kg: float = Field(..., ge=10.0, le=400.0, description="Patient weight in kg")
    height_cm: Optional[float] = Field(None, ge=40.0, le=250.0, description="Patient height in cm")
    height_m: Optional[float] = Field(None, ge=0.4, le=2.5, description="Patient height in meters")


class StoredFunctionBmiResponse(BaseModel):
    """Calculated BMI and WHO classification category."""
    weight_kg: float
    height_cm: float
    bmi: float
    category: str
    formula_used: str
    result: Optional[Any] = None
    interpretation: Optional[str] = None


class StoredFunctionFeverRequest(BaseModel):
    """Input parameter for fever classification routine."""
    temperature_f: Optional[float] = Field(None, ge=75.0, le=115.0)
    temperature_c: Optional[float] = Field(None, ge=25.0, le=46.0)
    temp_c: Optional[float] = Field(None, ge=25.0, le=46.0)


class StoredFunctionFeverResponse(BaseModel):
    """Fever stage and clinical guidance."""
    temperature_f: float
    temperature_c: float
    fever_category: str
    clinical_action: str
    result: Optional[Any] = None
    interpretation: Optional[str] = None


class StoredProcedureDischargeRequest(BaseModel):
    """Request to execute safe discharge procedure."""
    patient_id: str = Field("P101")
    simulate_rollback: Optional[bool] = Field(
        False,
        description="If True, tests transactional rollback when unresolved critical alerts exist.",
    )


class StoredProcedureDischargeResponse(BaseModel):
    """Outcome of transactional patient discharge procedure."""
    patient_id: str
    status: str
    active_alerts_count: int
    message: str
    transaction_status: str
    transaction_outcome: Optional[str] = None


class StoredProcedureAcknowledgeRequest(BaseModel):
    """Request to execute alert acknowledgement procedure."""
    alert_id: str
    notes: Optional[str] = "Acknowledged via DA3 Evaluation Console"
    clinician_id: Optional[str] = None
    note: Optional[str] = None


class StoredProcedureAcknowledgeResponse(BaseModel):
    """Result of stored procedure execution."""
    alert_id: str
    new_status: str
    acknowledged_at: datetime
    message: str
    status: Optional[str] = "ACKNOWLEDGED"
    transaction_outcome: Optional[str] = "COMMIT_SUCCESSFUL"


class TriggerTestUpdateRequest(BaseModel):
    """Request to invoke database trigger via status update."""
    alert_id: Optional[str] = None
    new_status: Optional[str] = "ACKNOWLEDGED"


class TriggerHistoryResponse(BaseModel):
    """Audit entry generated automatically by database trigger."""
    history_id: Optional[int] = None
    alert_id: str
    old_status: Optional[str]
    new_status: str
    changed_at: datetime
    changed_by: Optional[str]
    trigger_name: str = "trg_alert_status_history_after_update"


class MongoCollectionInfo(BaseModel):
    """Metadata describing a MongoDB collection."""
    name: str
    document_count: int
    indexes_count: int
    indexes: List[Dict[str, Any]]


class MongoStatusResponse(BaseModel):
    """MongoDB mirror connection, cloud deployment, and Outbox queue status."""
    status: str
    is_connected: bool
    is_cloud: bool
    cloud_host_redacted: str
    ping_latency_ms: Optional[float] = None
    database: str
    collections: List[MongoCollectionInfo]
    outbox_queue: Dict[str, Any]
    is_read_only_enforced: bool = True
    is_mirror_enabled: bool = False


class MongoDocumentsResponse(BaseModel):
    """Paginated collection of MongoDB documents."""
    collection_name: str
    total_matching: int
    page: int
    page_size: int
    total_pages: int
    documents: List[Dict[str, Any]]


class MongoIndexInfoResponse(BaseModel):
    """Indexes registered on a MongoDB collection."""
    collection_name: str
    indexes: List[Dict[str, Any]]


class MongoExplainRequest(BaseModel):
    """Request to generate execution plan for MongoDB query."""
    collection_name: str = Field("telemetry_events")
    query_type: str = Field("indexed", description="'indexed' (IXSCAN) or 'unindexed' (COLLSCAN)")
    patient_id: Optional[str] = Field("P101")


class MongoExplainResponse(BaseModel):
    """MongoDB query planner explain output."""
    collection_name: str
    query_type: str
    query_filter: Dict[str, Any]
    winning_stage: str
    index_used: Optional[str] = None
    execution_time_ms: float
    total_docs_examined: int
    total_keys_examined: int
    docs_returned: int
    analysis: str
    raw_plan: Dict[str, Any]


class MongoAggregateRequest(BaseModel):
    """Request to execute a MongoDB aggregation pipeline."""
    pipeline_name: str = Field(
        ...,
        description="Pipeline key: 'dataset_overview', 'patient_vitals_summary', 'time_bucketed', 'source_breakdown'",
    )
    patient_id: Optional[str] = Field("P101")


class MongoAggregateResponse(BaseModel):
    """Results of MongoDB aggregation pipeline."""
    pipeline_name: str
    description: str
    pipeline_json: str
    execution_time_ms: float
    result_count: int
    results: List[Dict[str, Any]]


class BenchmarkSummaryResponse(BaseModel):
    """Empirical benchmark summary and academic scorecard."""
    run_id: str
    timestamp: str
    environment: str
    workloads: List[Dict[str, Any]]
    speedup_highlights: List[str]
    test_scorecard: Dict[str, Any]


class RbacTestResponse(BaseModel):
    """Results of role-based security boundary check."""
    caller_role: str
    caller_id: str
    permissions: Dict[str, bool]
    access_matrix: List[Dict[str, Any]]


class DiagnosticsResponse(BaseModel):
    """Non-destructive preflight system verification."""
    total_checks: int
    passed_checks: int
    failed_checks: int
    checks: List[Dict[str, Any]]


class SecurityDemonstrationRequest(BaseModel):
    """Request to demonstrate a specific security or error-handling scenario."""
    scenario: str = Field(
        ...,
        description=(
            "Security scenario: 'authorized_read', 'denied_unassigned_patient', "
            "'denied_baseline_delete', 'invalid_reading_range', 'duplicate_event_rejection', "
            "'missing_record_lookup', 'unauthenticated_request'"
        ),
    )
    patient_id: Optional[str] = Field("P101", description="Target patient ID parameter")
    record_id: Optional[str] = Field("P001", description="Record or patient ID parameter")


class SecurityDemonstrationResponse(BaseModel):
    """Sanitized evidence from executing a security or error-handling scenario."""
    scenario: str
    title: str
    expected_status: int
    actual_status: int
    outcome: str  # PERMITTED, DENIED, VALIDATION_FAILED, NOT_FOUND, CONFLICT_HANDLED
    security_layer: str
    security_explanation: str
    sanitized_response: Dict[str, Any]
    timestamp: str


class TestRunnerRunRequest(BaseModel):
    """Request to trigger a safe, pre-scoped demonstration test suite."""
    suite_type: str = Field(
        "quick",
        description="Suite to execute: 'quick', 'unit', 'integration', 'frontend', 'live', or 'all'",
    )


class TestItemResponse(BaseModel):
    """Individual test execution outcome record."""
    id: str
    name: str
    test_symbol: str
    suite: str
    category: str
    status: str  # PASS, FAIL, SKIPPED, NOT_EXECUTED
    duration_ms: float
    dependency: str
    details: Optional[str] = None
    error: Optional[str] = None


class TestRunnerSummary(BaseModel):
    """Aggregated test execution statistics."""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    pass_rate_percent: float


class TestRunnerInvariants(BaseModel):
    """Safety invariants verified during test run."""
    mongodb_read_only_enforced: bool
    mongodb_initial_doc_count: Optional[int] = None
    mongodb_final_doc_count: Optional[int] = None
    mongodb_writes_detected: int
    mongodb_status: str
    mysql_baseline_ehr_intact: bool
    mysql_status: str


class TestRunnerReportResponse(BaseModel):
    """Complete test evidence report for viva demonstration."""
    report_schema_version: str
    run_id: str
    suite_type: str
    overall_status: str
    started_at: str
    completed_at: str
    total_duration_ms: float
    summary: TestRunnerSummary
    invariants: TestRunnerInvariants
    categories: Dict[str, int]
    tests: List[TestItemResponse]


# ============================================================================
# CHALLENGE MODE SCHEMAS (PART 7G)
# ============================================================================

class ChallengeMetadata(BaseModel):
    """Metadata definition for a guided evaluation challenge."""
    challenge_id: str = Field(..., description="Unique slug for challenge")
    category: str = Field(..., description="'SQL Challenges', 'MongoDB Challenges', 'Security & Testing Challenges'")
    name: str = Field(..., description="Short name of the challenge")
    purpose: str = Field(..., description="Academic purpose and learning objective")
    operation_type: str = Field(..., description="Type of operation performed")
    requires_confirmation: bool = Field(False, description="Whether destructive confirmation is required")
    allowed_parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Customizable parameters")
    description: str = Field(..., description="Detailed explanation of the challenge")


class ChallengeExecuteRequest(BaseModel):
    """Payload to safely execute a guided evaluation challenge."""
    challenge_id: str = Field(..., description="Target challenge identifier")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional parameter overrides")
    confirmed: Optional[bool] = Field(False, description="Explicit confirmation for destructive operations")


class ChallengeExecuteResponse(BaseModel):
    """Empirical result of a guided evaluation challenge."""
    challenge_id: str
    name: str
    category: str
    purpose: str
    operation_demonstrated: str
    status: str  # 'SUCCESS', 'REJECTED_SAFE', 'VALIDATION_ERROR', 'FAILED'
    http_status: int
    execution_time_ms: float
    affected_rows: Optional[int] = None
    response_data: Any
    explanation: str
    timestamp_utc: str


# ============================================================================
# SQL WORKBENCH SCHEMAS (DEMO MODE ONLY)
# ============================================================================

class MLAssessmentSummary(BaseModel):
    """Summary of ML anomaly detection inference triggered by vital insert."""
    assessed: bool = Field(True, description="Whether ML assessment was executed")
    event_id: Optional[str] = Field(None, description="Ingestion event UUID")
    patient_id: Optional[str] = Field(None, description="Assessed patient ID")
    anomaly_score: Optional[float] = Field(None, description="Isolation Forest anomaly score [0.0 - 1.0]")
    result: Optional[str] = Field(None, description="'normal', 'anomaly', or 'inconclusive'")
    alert_created: bool = Field(False, description="Whether an alert was triggered")
    alert_severity: Optional[str] = Field(None, description="Alert severity level: LOW, MEDIUM, HIGH, CRITICAL")
    message: Optional[str] = Field(None, description="Clinical anomaly explanation")


class SQLWorkbenchExecuteRequest(BaseModel):
    """Payload to execute an arbitrary SQL statement in Demo Mode."""
    sql: str = Field(..., min_length=1, max_length=5000, description="Single SQL statement to execute")
    patient_id: Optional[str] = Field(None, description="Optional target patient ID context")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional query parameter bindings")
    is_demo_mode: bool = Field(True, description="Must be true to permit execution in Demo Mode")


class SQLWorkbenchExecuteResponse(BaseModel):
    """Structured result returned by the Demo SQL Workbench."""
    status: str = Field("success", description="'success' or 'error'")
    statement_type: str = Field(..., description="Detected SQL command: SELECT, INSERT, UPDATE, DELETE, CREATE")
    execution_time_ms: float = Field(..., description="Query elapsed execution duration in milliseconds")
    columns: Optional[List[str]] = Field(default=None, description="Ordered column names for tabular results")
    rows: Optional[List[List[Any]]] = Field(default=None, description="Row values as 2D array")
    row_count: int = Field(0, description="Total rows returned in the result set")
    rows_affected: Optional[int] = Field(default=None, description="Number of rows modified, inserted, or deleted")
    last_inserted_id: Optional[Union[int, str]] = Field(default=None, description="Autoincrement ID of newly inserted record")
    message: Optional[str] = Field(default=None, description="Informational or operation status message")
    ml_assessment: Optional[MLAssessmentSummary] = Field(default=None, description="ML assessment result if reading was inserted")


