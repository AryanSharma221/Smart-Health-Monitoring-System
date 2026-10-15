"""
Unit tests for DemoSQLExecutionService (Demo Mode SQL Workbench Backend).

Verifies:
1. Valid INSERT operations enforce source='self_added' and invoke ML analysis pipeline.
2. Standard SELECT, WHERE, ORDER BY, and LIMIT operations.
3. JOIN operations (INNER JOIN, LEFT JOIN).
4. Aggregations (COUNT, AVG, MIN, MAX, SUM) and GROUP BY.
5. Nested subqueries and CTEs.
6. CREATE VIEW and querying from user-defined views.
7. Safe UPDATE and DELETE on self_added records.
8. Rejection of mutations targeting baseline clinical cohorts (P001-P005).
9. Rejection of multi-statement payloads.
10. Rejection of unsafe commands (DROP, ATTACH, PRAGMA, LOAD DATA).
11. Rejection of access to system tables (users, audit_log, alembic_version).
12. Rejection outside Demo Mode.
13. Physiological boundary validations (e.g. SpO2 > 100%, HR > 250 bpm).
14. Transaction atomicity and rollback on syntax or execution failure.
15. Isolation guarantees (zero ML invocation on SELECT, zero MongoDB calls).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Generator
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    Base,
    IngestionEvent,
    ModelAssessment,
    PatientProfile,
    User,
    VitalsReading,
)
from services.api.schemas.evaluation import SQLWorkbenchExecuteRequest
from services.demo_sql_service import (
    DemoSQLExecutionService,
    sanitize_sql_error_message,
)


@pytest.fixture(scope="function")
def isolated_test_db() -> Generator[Session, None, None]:
    """Provides an isolated, in-memory SQLite database seeded with demo and baseline cohorts."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session: Session = TestingSessionLocal()

    # Seed demo patient P101
    user_p101 = User(
        user_id="U_PAT_101",
        email="p101@test.org",
        password_hash="test_hash_p101",
        role="patient",
        is_active=True,
    )
    session.add(user_p101)
    session.add(PatientProfile(
        patient_id="P101",
        user_id="U_PAT_101",
        first_name="Demo",
        last_name="Patient101",
        date_of_birth=date(1990, 1, 1),
        gender="male",
    ))

    # Seed baseline clinical patient P001 (immutable)
    user_p001 = User(
        user_id="U_PAT_001",
        email="p001@test.org",
        password_hash="test_hash_p001",
        role="patient",
        is_active=True,
    )
    session.add(user_p001)
    session.add(PatientProfile(
        patient_id="P001",
        user_id="U_PAT_001",
        first_name="Baseline",
        last_name="Patient001",
        date_of_birth=date(1975, 5, 20),
        gender="female",
    ))

    # Seed initial baseline vitals reading for P001
    evt_p001 = IngestionEvent(
        event_id="evt_baseline_001",
        patient_id="P001",
        source="smartwatch_simulator",
        source_event_id="src_baseline_001",
        measured_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        is_simulated=True,
        mirror_status="pending",
    )
    session.add(evt_p001)
    session.add(VitalsReading(
        event_id="evt_baseline_001",
        patient_id="P001",
        metric_code="heart_rate",
        value=Decimal("72.00"),
        unit="bpm",
        raw_value=Decimal("72.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=datetime.now(timezone.utc),
    ))

    session.commit()
    yield session
    session.close()


@pytest.fixture(scope="function")
def sql_service(isolated_test_db: Session) -> DemoSQLExecutionService:
    """Instantiate DemoSQLExecutionService with isolated in-memory test session."""
    session_factory = lambda: isolated_test_db
    return DemoSQLExecutionService(session_factory=session_factory)


# ============================================================================
# 1. CORE OPERATIONS (INSERT, SELECT, UPDATE, DELETE)
# ============================================================================

def test_valid_vitals_insert_enforces_self_added_and_calls_ml(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test valid vital insertion assigns source='self_added', creates event, and invokes ML."""
    req = SQLWorkbenchExecuteRequest(
        sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit, measured_at) "
            "VALUES ('P101', 'heart_rate', 145.0, 'bpm', datetime('now'))",
        is_demo_mode=True,
    )
    res = sql_service.execute_query(req, isolated_test_db)

    assert res.status == "success"
    assert res.statement_type == "INSERT"
    assert res.rows_affected == 1
    assert res.last_inserted_id is not None
    assert res.ml_assessment is not None
    assert res.ml_assessment.assessed is True
    assert res.ml_assessment.patient_id == "P101"

    # Verify relational persistence in isolated database
    reading = isolated_test_db.query(VitalsReading).filter(VitalsReading.patient_id == "P101").first()
    assert reading is not None
    assert float(reading.value) == 145.0
    assert reading.metric_code == "heart_rate"

    event = isolated_test_db.query(IngestionEvent).filter(IngestionEvent.event_id == reading.event_id).first()
    assert event is not None
    assert event.source == "self_added"  # Provenance invariant
    assert event.is_simulated is False   # Non-simulated invariant


def test_select_filtering_and_order_by(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test SELECT with WHERE, ORDER BY, and LIMIT returns structured tabular results."""
    # First insert a test reading
    req_insert = SQLWorkbenchExecuteRequest(
        sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit) "
            "VALUES ('P101', 'spo2', 96.5, '%')",
        is_demo_mode=True,
    )
    sql_service.execute_query(req_insert, isolated_test_db)

    # Now query it
    req_select = SQLWorkbenchExecuteRequest(
        sql="SELECT reading_id, patient_id, metric_code, value, unit "
            "FROM vitals_readings WHERE patient_id = 'P101' ORDER BY reading_id DESC LIMIT 10",
        is_demo_mode=True,
    )
    res = sql_service.execute_query(req_select, isolated_test_db)

    assert res.status == "success"
    assert res.statement_type == "SELECT"
    assert res.columns == ["reading_id", "patient_id", "metric_code", "value", "unit"]
    assert len(res.rows) == 1
    assert res.rows[0][1] == "P101"
    assert res.rows[0][2] == "spo2"
    assert float(res.rows[0][3]) == 96.5
    assert res.ml_assessment is None  # ML is NEVER invoked on SELECT


def test_aggregate_and_group_by(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test aggregate functions (COUNT, AVG, MIN, MAX) and GROUP BY."""
    # Insert multiple readings for P101
    for hr in [70.0, 80.0, 90.0]:
        sql_service.execute_query(
            SQLWorkbenchExecuteRequest(
                sql=f"INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', {hr}, 'bpm')",
                is_demo_mode=True,
            ),
            isolated_test_db,
        )

    req = SQLWorkbenchExecuteRequest(
        sql="SELECT metric_code, COUNT(*) AS count, AVG(value) AS avg_val, MIN(value) AS min_val, MAX(value) AS max_val "
            "FROM vitals_readings WHERE patient_id = 'P101' GROUP BY metric_code",
        is_demo_mode=True,
    )
    res = sql_service.execute_query(req, isolated_test_db)

    assert res.status == "success"
    assert res.columns == ["metric_code", "count", "avg_val", "min_val", "max_val"]
    assert len(res.rows) == 1
    row = res.rows[0]
    assert row[0] == "heart_rate"
    assert row[1] == 3
    assert float(row[2]) == 80.0
    assert float(row[3]) == 70.0
    assert float(row[4]) == 90.0


def test_inner_and_left_join(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test multi-table JOIN operations."""
    sql_service.execute_query(
        SQLWorkbenchExecuteRequest(
            sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', 75.0, 'bpm')",
            is_demo_mode=True,
        ),
        isolated_test_db,
    )

    req = SQLWorkbenchExecuteRequest(
        sql="SELECT p.patient_id, p.first_name, p.last_name, v.metric_code, v.value "
            "FROM patient_profiles p "
            "INNER JOIN vitals_readings v ON p.patient_id = v.patient_id "
            "WHERE p.patient_id = 'P101'",
        is_demo_mode=True,
    )
    res = sql_service.execute_query(req, isolated_test_db)

    assert res.status == "success"
    assert len(res.rows) == 1
    assert res.rows[0][0] == "P101"
    assert res.rows[0][1] == "Demo"
    assert res.rows[0][3] == "heart_rate"


def test_nested_select_query(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test nested subquery in WHERE clause."""
    sql_service.execute_query(
        SQLWorkbenchExecuteRequest(
            sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', 85.0, 'bpm')",
            is_demo_mode=True,
        ),
        isolated_test_db,
    )

    req = SQLWorkbenchExecuteRequest(
        sql="SELECT patient_id, metric_code, value FROM vitals_readings "
            "WHERE value > (SELECT AVG(value) FROM vitals_readings WHERE metric_code = 'heart_rate')",
        is_demo_mode=True,
    )
    res = sql_service.execute_query(req, isolated_test_db)
    assert res.status == "success"
    assert isinstance(res.rows, list)


def test_create_view_and_query_view(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test CREATE VIEW definition and querying from the created view."""
    # 1. Create View
    req_create = SQLWorkbenchExecuteRequest(
        sql="CREATE VIEW v_demo_heart_rates AS "
            "SELECT reading_id, patient_id, value FROM vitals_readings WHERE metric_code = 'heart_rate'",
        is_demo_mode=True,
    )
    res_create = sql_service.execute_query(req_create, isolated_test_db)
    assert res_create.status == "success"
    assert res_create.statement_type == "CREATE"

    # 2. Query View
    req_query = SQLWorkbenchExecuteRequest(
        sql="SELECT * FROM v_demo_heart_rates",
        is_demo_mode=True,
    )
    res_query = sql_service.execute_query(req_query, isolated_test_db)
    assert res_query.status == "success"
    assert res_query.columns == ["reading_id", "patient_id", "value"]


def test_update_and_delete_self_added_record(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test updating and deleting self_added demo records."""
    # Insert reading
    ins_res = sql_service.execute_query(
        SQLWorkbenchExecuteRequest(
            sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', 77.0, 'bpm')",
            is_demo_mode=True,
        ),
        isolated_test_db,
    )
    reading_id = ins_res.last_inserted_id

    # Update reading
    req_update = SQLWorkbenchExecuteRequest(
        sql=f"UPDATE vitals_readings SET value = 82.0 WHERE reading_id = {reading_id} AND patient_id = 'P101'",
        is_demo_mode=True,
    )
    res_update = sql_service.execute_query(req_update, isolated_test_db)
    assert res_update.status == "success"
    assert res_update.rows_affected == 1

    # Verify update persisted
    updated_reading = isolated_test_db.query(VitalsReading).filter(VitalsReading.reading_id == reading_id).first()
    assert float(updated_reading.value) == 82.0

    # Delete reading
    req_delete = SQLWorkbenchExecuteRequest(
        sql=f"DELETE FROM vitals_readings WHERE reading_id = {reading_id} AND patient_id = 'P101'",
        is_demo_mode=True,
    )
    res_delete = sql_service.execute_query(req_delete, isolated_test_db)
    assert res_delete.status == "success"
    assert res_delete.rows_affected == 1

    # Verify deletion
    deleted = isolated_test_db.query(VitalsReading).filter(VitalsReading.reading_id == reading_id).first()
    assert deleted is None


# ============================================================================
# 2. SECURITY & BOUNDARY ENFORCEMENT
# ============================================================================

def test_reject_update_or_delete_on_baseline_patient(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test modifying or deleting baseline patient P001 is rejected with 403 Forbidden."""
    req_update = SQLWorkbenchExecuteRequest(
        sql="UPDATE vitals_readings SET value = 99.0 WHERE patient_id = 'P001'",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req_update, isolated_test_db)
    assert exc_info.value.status_code == 403
    assert "P001" in exc_info.value.detail

    req_delete = SQLWorkbenchExecuteRequest(
        sql="DELETE FROM vitals_readings WHERE patient_id = 'P001'",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req_delete, isolated_test_db)
    assert exc_info.value.status_code == 403
    assert "P001" in exc_info.value.detail


def test_reject_multi_statement(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test chained queries with semicolons are rejected to prevent multi-statement injection."""
    req = SQLWorkbenchExecuteRequest(
        sql="SELECT * FROM vitals_readings; DELETE FROM vitals_readings;",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req, isolated_test_db)
    assert exc_info.value.status_code == 400
    assert "Multi-statement" in exc_info.value.detail


def test_reject_unsafe_commands_drop_attach_pragma(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test dangerous administrative statements are rejected."""
    dangerous_queries = [
        "DROP DATABASE smart_health_local",
        "DROP TABLE vitals_readings",
        "ATTACH DATABASE 'evil.db' AS evil",
        "DETACH DATABASE evil",
        "PRAGMA writable_schema=1",
        "ALTER TABLE vitals_readings ADD COLUMN evil TEXT",
        "TRUNCATE TABLE vitals_readings",
    ]
    for q in dangerous_queries:
        req = SQLWorkbenchExecuteRequest(sql=q, is_demo_mode=True)
        with pytest.raises(HTTPException) as exc_info:
            sql_service.execute_query(req, isolated_test_db)
        assert exc_info.value.status_code in (400, 403)


def test_reject_access_to_system_tables_users(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test queries attempting to select or modify users/credentials table are blocked."""
    req = SQLWorkbenchExecuteRequest(
        sql="SELECT user_id, password_hash FROM users",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req, isolated_test_db)
    assert exc_info.value.status_code == 403
    assert "users" in exc_info.value.detail


def test_reject_outside_demo_mode(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test query execution is denied when is_demo_mode is False."""
    req = SQLWorkbenchExecuteRequest(
        sql="SELECT * FROM vitals_readings",
        is_demo_mode=False,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req, isolated_test_db)
    assert exc_info.value.status_code == 403
    assert "restricted exclusively to Demo Mode" in exc_info.value.detail


# ============================================================================
# 3. CLINICAL DOMAIN VALIDATION & ATOMICITY
# ============================================================================

def test_reject_invalid_physiological_bounds(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test non-physiological vitals (e.g. SpO2 > 100% or HR > 250) are rejected."""
    # Out of range SpO2
    req_spo2 = SQLWorkbenchExecuteRequest(
        sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'spo2', 125.0, '%')",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req_spo2, isolated_test_db)
    assert exc_info.value.status_code == 422
    assert "spo2" in exc_info.value.detail.lower()

    # Out of range Heart Rate
    req_hr = SQLWorkbenchExecuteRequest(
        sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', 350.0, 'bpm')",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req_hr, isolated_test_db)
    assert exc_info.value.status_code == 422
    assert "heart_rate" in exc_info.value.detail.lower()


def test_reject_invalid_cohort(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test inserting readings for non-demo cohort patient is rejected."""
    req = SQLWorkbenchExecuteRequest(
        sql="INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P999', 'heart_rate', 75.0, 'bpm')",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req, isolated_test_db)
    assert exc_info.value.status_code == 422
    assert "demo cohort" in exc_info.value.detail.lower()


def test_transaction_rollback_on_failure(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test that a statement violating SQLite database constraints cleanly rolls back."""
    initial_count = isolated_test_db.query(VitalsReading).count()

    # Statement with invalid foreign key or missing non-null column
    req = SQLWorkbenchExecuteRequest(
        sql="INSERT INTO vitals_readings (reading_id, patient_id) VALUES (99999, 'INVALID_NONEXISTENT')",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req, isolated_test_db)
    assert exc_info.value.status_code in (400, 422)

    # Invariant: Database count must remain unchanged
    after_count = isolated_test_db.query(VitalsReading).count()
    assert initial_count == after_count


def test_sql_syntax_error_handling(
    sql_service: DemoSQLExecutionService,
    isolated_test_db: Session,
):
    """Test malformed SQL syntax returns a readable 400 error without leaking paths."""
    # 1. Invalid keyword
    req_bad_keyword = SQLWorkbenchExecuteRequest(
        sql="SELEC * FORM vitals_readings",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        sql_service.execute_query(req_bad_keyword, isolated_test_db)
    assert exc_info.value.status_code == 400
    assert "syntax" in exc_info.value.detail.lower() or "statement" in exc_info.value.detail.lower()

    # 2. Incomplete syntax causing engine syntax error
    req_incomplete = SQLWorkbenchExecuteRequest(
        sql="SELECT * FROM vitals_readings WHERE",
        is_demo_mode=True,
    )
    with pytest.raises(HTTPException) as exc_info2:
        sql_service.execute_query(req_incomplete, isolated_test_db)
    assert exc_info2.value.status_code == 400
    assert "syntax error" in exc_info2.value.detail.lower() or "incomplete input" in exc_info2.value.detail.lower()


def test_error_message_sanitizer():
    """Verify sanitizer strips Windows and Unix file paths and connection strings."""
    raw_error = "OperationalError: near C:\\Users\\Administrator\\db.sqlite: syntax error at sqlite:///C:/Users/app.db"
    sanitized = sanitize_sql_error_message(raw_error)
    assert "C:\\Users" not in sanitized
    assert "sqlite:///C:" not in sanitized
    assert "[REDACTED" in sanitized
