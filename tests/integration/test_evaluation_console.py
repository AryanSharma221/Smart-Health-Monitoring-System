"""
Integration Test Suite for DA3 Academic Evaluation Console Endpoints.

Validates:
1. Isolated CRUD operations on EVAL_* records with full audit logging.
2. Safety guard preventing hard deletion of non-EVAL_* records.
3. Named SQL query execution and latency benchmarking.
4. EXPLAIN execution plan analysis comparing indexed vs unindexed queries.
5. Database objects: views, stored functions (BMI, fever), stored procedures (acknowledge, discharge), and triggers.
6. MongoDB aggregation pipeline simulation and fallback.
7. Performance benchmark scorecard retrieval.
8. RBAC security evaluation and 10-point preflight diagnostics.
"""

from __future__ import annotations

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    Alert,
    AlertRule,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    EvaluationRecord,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password


@pytest.fixture(scope="function")
def eval_settings() -> Settings:
    return Settings(
        app_env="testing",
        jwt_secret="testing_eval_console_secret_key_at_least_32_chars!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        mongodb_sync_enabled=False,
    )


@pytest.fixture(scope="function")
def eval_db_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    # Create views and trigger in SQLite memory engine
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE VIEW IF NOT EXISTS v_latest_patient_vitals AS
            WITH ranked_vitals AS (
                SELECT reading_id, event_id, patient_id, metric_code, value, unit, raw_value, raw_unit, quality_status, measured_at,
                       ROW_NUMBER() OVER (PARTITION BY patient_id, metric_code ORDER BY measured_at DESC) AS rn
                FROM vitals_readings
            )
            SELECT reading_id, event_id, patient_id, metric_code, value, unit, raw_value, raw_unit, quality_status, measured_at
            FROM ranked_vitals
            WHERE rn = 1;
        """))
        conn.execute(text("""
            CREATE VIEW IF NOT EXISTS v_patient_active_alerts AS
            SELECT a.alert_id, a.patient_id, p.first_name, p.last_name,
                   a.severity, a.status, a.category, a.reason, a.created_at
            FROM alerts a
            INNER JOIN patient_profiles p ON a.patient_id = p.patient_id
            WHERE a.status IN ('NEW', 'ACTIVE');
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_alert_status_history_after_update
            AFTER UPDATE OF status ON alerts
            FOR EACH ROW
            WHEN OLD.status <> NEW.status
            BEGIN
                INSERT INTO alert_status_history (alert_id, old_status, new_status, actor_id, note, changed_at)
                VALUES (OLD.alert_id, OLD.status, NEW.status, COALESCE(NEW.acknowledged_by, NEW.resolved_by), 'Trigger recorded transition', CURRENT_TIMESTAMP);
            END;
        """))

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()

    # Seed baseline doctor and demo patients
    doc_user = User(
        user_id="USR_DOC_EVAL",
        email="doctor.eval@hospital.org",
        password_hash=hash_password("DoctorPass123!"),
        role="doctor",
        is_active=True,
    )
    session.add(doc_user)

    pat_user = User(
        user_id="USR_PAT_P101",
        email="patient.p101@hospital.org",
        password_hash=hash_password("PatientPass123!"),
        role="patient",
        is_active=True,
    )
    session.add(pat_user)
    session.flush()

    doc_profile = DoctorProfile(
        doctor_id="DOC_EVAL",
        user_id="USR_DOC_EVAL",
        first_name="Jane",
        last_name="Doe",
        specialization="Critical Care",
        license_number="LIC-EVAL-12345",
    )
    session.add(doc_profile)

    patient_p101 = PatientProfile(
        patient_id="P101",
        user_id="USR_PAT_P101",
        first_name="Kaggle",
        last_name="Patient P101",
        date_of_birth=datetime(1980, 5, 12, tzinfo=timezone.utc).date(),
        gender="male",
    )
    session.add(patient_p101)

    assignment = DoctorPatientAssignment(
        doctor_id="DOC_EVAL",
        patient_id="P101",
        is_active=True,
    )
    session.add(assignment)

    # Seed IngestionEvents and vitals
    now = datetime.now(timezone.utc)
    for i in range(10):
        evt_id = f"EVT_EVAL_{i}"
        evt = IngestionEvent(
            event_id=evt_id,
            source="kaggle",
            source_event_id=f"SRC_KAGGLE_{i}",
            patient_id="P101",
            measured_at=now,
            is_simulated=False,
            mirror_status="mirrored",
        )
        session.add(evt)
        session.add(VitalsReading(
            event_id=evt_id,
            patient_id="P101",
            metric_code="heart_rate",
            value=Decimal(str(75.0 + i)),
            unit="bpm",
            raw_value=Decimal(str(75.0 + i)),
            raw_unit="bpm",
            quality_status="valid",
            measured_at=now,
        ))

    # Seed active alert
    session.add(Alert(
        alert_id="ALT_EVAL_01",
        patient_id="P101",
        event_id="EVT_EVAL_0",
        severity="HIGH",
        status="NEW",
        category="vital_threshold",
        reason="Tachycardia alert for P101",
        created_at=now,
    ))

    session.commit()
    yield session
    session.close()


@pytest.fixture(scope="function")
def eval_client(eval_settings: Settings, eval_db_session: Session) -> TestClient:
    app = create_app(settings=eval_settings)
    app.dependency_overrides[get_db] = lambda: eval_db_session
    with TestClient(app) as client:
        yield client


# ============================================================================
# TESTS
# ============================================================================

def test_crud_lifecycle_create_read_update_delete(eval_client: TestClient):
    """Verify full CRUD lifecycle on isolated EVAL_* records with non-repudiation audit."""
    # 1. CREATE
    create_payload = {
        "patient_id": "P101",
        "record_type": "clinical_note",
        "title": "Post-Op Triage Evaluation",
        "content_text": "Patient vitals stable following telemetry observation.",
        "status": "ACTIVE",
    }
    res = eval_client.post("/api/v1/evaluation/crud/records", json=create_payload)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    record_id = data["record_id"]
    assert record_id.startswith("EVAL_NOTE_")
    assert data["title"] == "Post-Op Triage Evaluation"

    # 2. READ ALL
    res_list = eval_client.get("/api/v1/evaluation/crud/records?patient_id=P101")
    assert res_list.status_code == status.HTTP_200_OK
    items = res_list.json()
    assert len(items) >= 1
    assert any(r["record_id"] == record_id for r in items)

    # 3. READ ONE
    res_get = eval_client.get(f"/api/v1/evaluation/crud/records/{record_id}")
    assert res_get.status_code == status.HTTP_200_OK
    assert res_get.json()["record_id"] == record_id

    # 4. UPDATE
    update_payload = {"title": "Updated Triage Assessment", "status": "FINALIZED"}
    res_put = eval_client.put(f"/api/v1/evaluation/crud/records/{record_id}", json=update_payload)
    assert res_put.status_code == status.HTTP_200_OK
    assert res_put.json()["title"] == "Updated Triage Assessment"
    assert res_put.json()["status"] == "FINALIZED"

    # 5. DELETE
    res_del = eval_client.delete(f"/api/v1/evaluation/crud/records/{record_id}")
    assert res_del.status_code == status.HTTP_200_OK
    assert res_del.json()["deleted"] is True

    # 6. VERIFY DELETED
    res_verify = eval_client.get(f"/api/v1/evaluation/crud/records/{record_id}")
    assert res_verify.status_code == status.HTTP_404_NOT_FOUND


def test_crud_safety_guard_prevents_unauthorized_deletion(eval_client: TestClient):
    """Verify that deleting records not prefixed with EVAL_ is blocked with 403 Forbidden."""
    res = eval_client.delete("/api/v1/evaluation/crud/records/P101")
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "Security & Clinical Safety Violation" in res.json()["detail"]


def test_insert_demo_reading_with_tachycardia_alert(eval_client: TestClient):
    """Verify controlled reading ingestion generates vital reading and triggers alert."""
    payload = {
        "patient_id": "P101",
        "heart_rate": 135.5,  # Breaches 120 bpm limit
        "spo2": 97.0,
        "temperature_f": 98.6,
        "source": "demo-simulator",
    }
    res = eval_client.post("/api/v1/evaluation/crud/readings", json=payload)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["outcome"] == "accepted"
    assert data["alert_created"] is True
    assert "Tachycardia Alert" in data["alert_detail"]


def test_sql_demonstrations_execute_successfully(eval_client: TestClient):
    """Verify named SQL queries execute with positive row counts and measured latency."""
    for q_name in ["basic_filter", "inner_join", "multi_join", "nested_subquery", "aggregate_moments"]:
        payload = {"query_name": q_name, "patient_id": "P101", "limit": 10}
        res = eval_client.post("/api/v1/evaluation/sql/demonstrate", json=payload)
        assert res.status_code == status.HTTP_200_OK, f"Failed for {q_name}: {res.text}"
        data = res.json()
        assert data["query_name"] == q_name
        assert data["execution_time_ms"] >= 0.0
        assert data["row_count"] > 0
        assert len(data["columns"]) > 0


def test_sql_explain_plan_comparison(eval_client: TestClient):
    """Verify EXPLAIN QUERY PLAN returns execution plan and index analysis."""
    # Test indexed covering scan
    res_idx = eval_client.post("/api/v1/evaluation/sql/explain", json={"query_type": "indexed", "patient_id": "P101"})
    assert res_idx.status_code == status.HTTP_200_OK
    assert "INDEX COVERING SCAN" in res_idx.json()["analysis"]

    # Test unindexed full table scan
    res_unidx = eval_client.post("/api/v1/evaluation/sql/explain", json={"query_type": "unindexed"})
    assert res_unidx.status_code == status.HTTP_200_OK
    assert "FULL TABLE SCAN" in res_unidx.json()["analysis"]


def test_database_views_query(eval_client: TestClient):
    """Verify querying v_latest_patient_vitals and v_patient_active_alerts views."""
    res1 = eval_client.get("/api/v1/evaluation/db-objects/views/v_latest_patient_vitals")
    assert res1.status_code == status.HTTP_200_OK
    assert res1.json()["view_name"] == "v_latest_patient_vitals"
    assert res1.json()["row_count"] >= 1

    res2 = eval_client.get("/api/v1/evaluation/db-objects/views/v_patient_active_alerts")
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["view_name"] == "v_patient_active_alerts"
    assert res2.json()["row_count"] >= 1


def test_stored_functions_bmi_and_fever(eval_client: TestClient):
    """Verify calculation results of stored mathematical and triage functions."""
    bmi_res = eval_client.post("/api/v1/evaluation/db-objects/functions/calculate-bmi", json={"weight_kg": 72.0, "height_cm": 178.0})
    assert bmi_res.status_code == status.HTTP_200_OK
    data = bmi_res.json()
    assert data["bmi"] == 22.72
    assert data["category"] == "NORMAL_WEIGHT"

    fever_res = eval_client.post("/api/v1/evaluation/db-objects/functions/fever-category", json={"temperature_f": 102.5})
    assert fever_res.status_code == status.HTTP_200_OK
    fdata = fever_res.json()
    assert fdata["fever_category"] == "MODERATE_FEVER"
    assert "Antipyretic therapy" in fdata["clinical_action"]


def test_stored_procedure_acknowledge_and_trigger(eval_client: TestClient):
    """Verify sp_acknowledge_alert executes atomically and fires database trigger."""
    ack_res = eval_client.post(
        "/api/v1/evaluation/db-objects/procedures/acknowledge-alert",
        json={"alert_id": "ALT_EVAL_01", "notes": "Panel demonstration test note"},
    )
    assert ack_res.status_code == status.HTTP_200_OK
    assert ack_res.json()["new_status"] == "ACKNOWLEDGED"

    # Query trigger history table
    trg_res = eval_client.get("/api/v1/evaluation/db-objects/triggers/history/ALT_EVAL_01")
    assert trg_res.status_code == status.HTTP_200_OK
    hist = trg_res.json()
    assert len(hist) >= 1
    assert hist[0]["new_status"] == "ACKNOWLEDGED"


def test_stored_procedure_safe_discharge_rollback(eval_client: TestClient):
    """Verify discharge procedure refuses and rolls back when unresolved alerts exist."""
    res = eval_client.post(
        "/api/v1/evaluation/db-objects/procedures/safe-discharge",
        json={"patient_id": "P101", "simulate_rollback": False},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    # P101 has open alert ALT_EVAL_01
    assert data["status"] == "ROLLED_BACK"


def test_mongodb_status_and_aggregations(eval_client: TestClient):
    """Verify MongoDB mirror status endpoint and analytical pipelines."""
    status_res = eval_client.get("/api/v1/evaluation/mongodb/status")
    assert status_res.status_code == status.HTTP_200_OK
    assert "outbox_queue" in status_res.json()

    for p_name in ["dataset_overview", "statistical_moments", "alert_triage", "outlier_detection"]:
        agg_res = eval_client.post("/api/v1/evaluation/mongodb/aggregate", json={"pipeline_name": p_name})
        assert agg_res.status_code == status.HTTP_200_OK
        data = agg_res.json()
        assert data["pipeline_name"] == p_name
        assert data["execution_time_ms"] >= 0.0
        assert data["result_count"] >= 1


def test_benchmarks_and_diagnostics(eval_client: TestClient):
    """Verify benchmark summary scorecard and preflight system diagnostics."""
    bench_res = eval_client.get("/api/v1/evaluation/benchmarks/summary")
    assert bench_res.status_code == status.HTTP_200_OK
    bdata = bench_res.json()
    assert len(bdata["workloads"]) == 7
    assert bdata["test_scorecard"]["backend_pass_rate"] == "100.0%"

    diag_res = eval_client.post("/api/v1/evaluation/diagnostics/preflight")
    assert diag_res.status_code == status.HTTP_200_OK
    ddata = diag_res.json()
    assert ddata["total_checks"] == 10
    assert ddata["passed_checks"] >= 9


def test_security_access_control_demonstrations(eval_client: TestClient):
    """Verify security controls, RBAC denials, input boundary validation, and sanitized errors."""
    # 1. RBAC Test
    rbac_res = eval_client.get("/api/v1/evaluation/security/rbac-test")
    assert rbac_res.status_code == status.HTTP_200_OK
    rdata = rbac_res.json()
    assert "permissions" in rdata
    assert "access_matrix" in rdata

    # 2. Authorized Read
    auth_res = eval_client.post("/api/v1/evaluation/security/demonstrate", json={"scenario": "authorized_read", "patient_id": "P101"})
    assert auth_res.status_code == status.HTTP_200_OK
    assert auth_res.json()["outcome"] == "PERMITTED"
    assert auth_res.json()["actual_status"] == 200

    # 3. Denied Unassigned Patient
    denied_res = eval_client.post("/api/v1/evaluation/security/demonstrate", json={"scenario": "denied_unassigned_patient"})
    assert denied_res.status_code == status.HTTP_200_OK
    assert denied_res.json()["outcome"] == "DENIED"
    assert denied_res.json()["actual_status"] == 403

    # 4. Denied Baseline Delete
    baseline_res = eval_client.post("/api/v1/evaluation/security/demonstrate", json={"scenario": "denied_baseline_delete", "record_id": "P001"})
    assert baseline_res.status_code == status.HTTP_200_OK
    assert baseline_res.json()["outcome"] == "DENIED"
    assert baseline_res.json()["actual_status"] == 403

    # 5. Invalid Reading Range (Boundary Validation)
    range_res = eval_client.post("/api/v1/evaluation/security/demonstrate", json={"scenario": "invalid_reading_range"})
    assert range_res.status_code == status.HTTP_200_OK
    assert range_res.json()["outcome"] == "VALIDATION_FAILED"
    assert range_res.json()["actual_status"] == 422

    # 6. Duplicate Event Rejection
    dup_res = eval_client.post("/api/v1/evaluation/security/demonstrate", json={"scenario": "duplicate_event_rejection"})
    assert dup_res.status_code == status.HTTP_200_OK
    assert dup_res.json()["outcome"] == "CONFLICT_HANDLED"
    assert dup_res.json()["actual_status"] == 409

    # 7. Missing Record Lookup
    missing_res = eval_client.post("/api/v1/evaluation/security/demonstrate", json={"scenario": "missing_record_lookup"})
    assert missing_res.status_code == status.HTTP_200_OK
    assert missing_res.json()["outcome"] == "NOT_FOUND"
    assert missing_res.json()["actual_status"] == 404

    # 8. Unauthenticated Request
    unauth_res = eval_client.post("/api/v1/evaluation/security/demonstrate", json={"scenario": "unauthenticated_request"})
    assert unauth_res.status_code == status.HTTP_200_OK
    assert unauth_res.json()["outcome"] == "DENIED"
    assert unauth_res.json()["actual_status"] == 401


def test_demonstration_test_runner_endpoints(eval_client: TestClient):
    """Verify DA3 demonstration test runner endpoints and safety invariants."""
    # 1. Fetch latest stored report
    latest_res = eval_client.get("/api/v1/evaluation/test-runner/latest")
    assert latest_res.status_code == status.HTTP_200_OK
    data = latest_res.json()
    assert "run_id" in data
    assert "summary" in data
    assert "invariants" in data
    assert "tests" in data
    assert data["invariants"]["mongodb_read_only_enforced"] is True
    assert data["invariants"]["mongodb_writes_detected"] == 0

    # 2. Reject invalid test suite name
    bad_res = eval_client.post("/api/v1/evaluation/test-runner/run", json={"suite_type": "drop_database"})
    assert bad_res.status_code == status.HTTP_400_BAD_REQUEST

    # 3. Trigger safe test suite execution (use 'frontend' for self-contained, live-server-independent verification)
    run_res = eval_client.post("/api/v1/evaluation/test-runner/run", json={"suite_type": "frontend"})
    assert run_res.status_code == status.HTTP_200_OK
    run_data = run_res.json()
    assert run_data["overall_status"] == "PASSED"
    assert run_data["summary"]["total_tests"] >= 28
    assert run_data["summary"]["passed"] >= 28
    assert run_data["invariants"]["mongodb_writes_detected"] == 0
    assert run_data["invariants"]["mysql_baseline_ehr_intact"] is True


def test_challenge_mode_catalog_and_execution(eval_client: TestClient):
    """
    Part 7G Integration Test: Verify Challenge Mode catalogue and safe execution.
    Tests:
    1. Catalogue retrieval returns all 22 registered challenges across the 3 categories.
    2. SQL SELECT challenge executes with valid query plan and positive duration.
    3. Delete challenge enforces both confirmation and Core EHR immutability guard (P001).
    4. Validation error challenge rejects out-of-range sensor readings (HTTP 422).
    """
    # 1. Catalogue Listing
    cat_res = eval_client.get("/api/v1/evaluation/challenges")
    assert cat_res.status_code == status.HTTP_200_OK
    catalog = cat_res.json()
    assert len(catalog) == 22
    categories = {c["category"] for c in catalog}
    assert "SQL Challenges" in categories
    assert "MongoDB Challenges" in categories
    assert "Security & Testing Challenges" in categories

    # 2. Execute SQL SELECT Challenge
    sel_res = eval_client.post(
        "/api/v1/evaluation/challenges/execute",
        json={"challenge_id": "sql_select_patient_readings", "parameters": {"patient_id": "P101", "limit": 5}},
    )
    assert sel_res.status_code == status.HTTP_200_OK
    sel_data = sel_res.json()
    assert sel_data["status"] == "SUCCESS"
    assert sel_data["http_status"] == 200
    assert sel_data["execution_time_ms"] >= 0.0
    assert "readings" in sel_data["response_data"]

    # 3. Guarded Delete Challenge: Baseline Protection
    base_res = eval_client.post(
        "/api/v1/evaluation/challenges/execute",
        json={"challenge_id": "sql_delete_evaluation_record", "parameters": {"target_baseline": True}, "confirmed": True},
    )
    assert base_res.status_code == status.HTTP_200_OK
    base_data = base_res.json()
    assert base_data["status"] == "REJECTED_SAFE"
    assert base_data["http_status"] == 403
    assert base_data["affected_rows"] == 0

    # 4. Guarded Delete Challenge: Confirmation Enforcement
    unconf_res = eval_client.post(
        "/api/v1/evaluation/challenges/execute",
        json={"challenge_id": "sql_delete_evaluation_record", "confirmed": False},
    )
    assert unconf_res.status_code == status.HTTP_200_OK
    unconf_data = unconf_res.json()
    assert unconf_data["status"] == "REJECTED_SAFE"
    assert unconf_data["http_status"] == 400

    # 5. Guarded Delete Challenge: Confirmed Safe Delete of Fixture
    conf_res = eval_client.post(
        "/api/v1/evaluation/challenges/execute",
        json={"challenge_id": "sql_delete_evaluation_record", "confirmed": True},
    )
    assert conf_res.status_code == status.HTTP_200_OK
    conf_data = conf_res.json()
    assert conf_data["status"] == "SUCCESS"
    assert conf_data["affected_rows"] == 1

    # 6. Security Input Validation Challenge
    val_res = eval_client.post(
        "/api/v1/evaluation/challenges/execute",
        json={"challenge_id": "sec_invalid_reading_validation", "parameters": {"heart_rate": -99.0}},
    )
    assert val_res.status_code == status.HTTP_200_OK
    val_data = val_res.json()
    assert val_data["status"] == "VALIDATION_ERROR"
    assert val_data["http_status"] == 422


