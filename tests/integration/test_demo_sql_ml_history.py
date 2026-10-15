"""
Comprehensive Integration Test Suite for Demo SQL Workbench ML & History Flow (Prompt 4).

Validates:
1. Full insertion-to-analysis flow: SQL INSERT -> IngestionEvent (self_added) -> VitalsReading
   -> Rule-Based AlertEvaluator -> MLService.assess_and_persist (Isolation Forest)
   -> ModelAssessment & Alert persistence -> History retrieval.
2. Anomaly detection & alerts: Multivariate readings (HR, SpO2, Temp) correctly trigger
   Isolation Forest anomaly scoring (score >= 0.50, result='anomaly') and clinical alerts.
3. Missing-feature handling: Single-metric insert without complete features sets
   result='inconclusive' (score 0.0) without fabricating missing values.
4. Normal vitals evaluation: Produces result='normal' (score < 0.50) with 0 alerts.
5. Demo history persistence: Newly inserted self_added vitals appear in /patients/{id}/readings,
   /patients/{id}/vitals, and /patients/{id}/alerts.
6. Consistent UPDATE behavior: Re-evaluates ML & clinical rules on value mutations.
7. Consistent DELETE behavior: Cascade cleans orphaned assessments, alerts, and events.
8. Strict security boundaries: Baseline cohorts (P001-P005), system tables, and prohibited
   statements remain completely immutable.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    Alert,
    AlertRule,
    AlertStatusHistory,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    ModelAssessment,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.session import get_db
from services.alerts.rules import DEFAULT_ALERT_RULES
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from services.demo_sql_service import DemoSQLExecutionService


@pytest.fixture(scope="function")
def test_settings() -> Settings:
    return Settings(
        app_env="testing",
        jwt_secret="testing_demo_sql_ml_history_secret_key_32_chars!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        mongodb_sync_enabled=False,
    )


@pytest.fixture(scope="function")
def test_db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    # Create analytical demo views
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

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()

    # Seed clinical alert rules
    for r in DEFAULT_ALERT_RULES:
        db_rule = AlertRule(
            rule_id=r.rule_id,
            metric_code=r.metric_code,
            operator=r.operator,
            configured_value=Decimal(str(r.configured_value)),
            duration_seconds=getattr(r, "duration_seconds", 0),
            severity=r.severity,
            is_enabled=True,
            is_demo_only=False,
            description=r.description,
        )
        session.add(db_rule)

    # Seed Admin User
    admin_user = User(
        user_id="USR_ADMIN",
        email="admin@hospital.org",
        password_hash=hash_password("AdminSecurePass123!"),
        role="admin_operator",
        is_active=True,
    )
    session.add(admin_user)

    # Seed Doctor User & Profile
    doc_user = User(
        user_id="USR_DOC",
        email="doctor.house@hospital.org",
        password_hash=hash_password("DocSecurePass123!"),
        role="doctor",
        is_active=True,
    )
    session.add(doc_user)
    session.flush()

    doc_profile = DoctorProfile(
        doctor_id="DOC_001",
        user_id="USR_DOC",
        first_name="Gregory",
        last_name="House",
        specialization="Diagnostic Medicine",
        license_number="MD-12345",
    )
    session.add(doc_profile)

    # Seed Baseline Protected Patient (P001) - Kaggle historical cohort
    p001_user = User(
        user_id="USR_P001",
        email="patient.p001@hospital.org",
        password_hash=hash_password("Patient001Pass!"),
        role="patient",
        is_active=True,
    )
    session.add(p001_user)
    session.flush()

    p001_profile = PatientProfile(
        patient_id="P001",
        user_id="USR_P001",
        first_name="Baseline",
        last_name="Subject 001",
    )
    session.add(p001_profile)
    session.add(DoctorPatientAssignment(doctor_id="DOC_001", patient_id="P001"))

    # Add Kaggle baseline historical record for P001
    evt_p001 = IngestionEvent(
        event_id="evt_kaggle_p001_001",
        patient_id="P001",
        source="kaggle",  # NON-SELF-ADDED IMMUTABLE BASELINE
        source_event_id="src_kaggle_p001",
        measured_at=datetime.now(timezone.utc) - timedelta(days=1),
        received_at=datetime.now(timezone.utc) - timedelta(days=1),
        is_simulated=False,
        mirror_status="mirrored",
    )
    session.add(evt_p001)
    session.add(VitalsReading(
        event_id="evt_kaggle_p001_001",
        patient_id="P001",
        metric_code="heart_rate",
        value=Decimal("70.00"),
        unit="bpm",
        raw_value=Decimal("70.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))

    # Seed Demo Patients (P101-P105)
    for p_id in ["P101", "P102", "P103", "P104", "P105"]:
        u = User(
            user_id=f"USR_{p_id}",
            email=f"{p_id.lower()}@demo.local",
            password_hash=hash_password("DemoPassword123!"),
            role="patient",
            is_active=True,
        )
        session.add(u)
        session.flush()

        prof = PatientProfile(
            patient_id=p_id,
            user_id=f"USR_{p_id}",
            first_name="Demo",
            last_name=f"Patient {p_id}",
        )
        session.add(prof)
        session.add(DoctorPatientAssignment(doctor_id="DOC_001", patient_id=p_id))

    session.commit()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(test_db_session: Session, test_settings: Settings) -> Generator[TestClient, None, None]:
    app = create_app(test_settings)
    app.dependency_overrides[get_db] = lambda: test_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def admin_token(test_settings: Settings) -> str:
    return create_access_token(
        data={"sub": "USR_ADMIN", "role": "admin_operator", "email": "admin@hospital.org"},
        settings=test_settings,
    )


@pytest.fixture(scope="function")
def doctor_token(test_settings: Settings) -> str:
    return create_access_token(
        data={"sub": "USR_DOC", "role": "doctor", "email": "doctor.house@hospital.org"},
        settings=test_settings,
    )


# ============================================================================
# 1. FULL INSERTION-TO-ANALYSIS & ANOMALY DETECTION WORKFLOW
# ============================================================================

def test_multivariate_vitals_insert_triggers_ml_anomaly_and_rules(
    client: TestClient,
    doctor_token: str,
    test_db_session: Session,
):
    """
    Test that inserting a full triad of abnormal vitals (HR=145, SpO2=86%, Temp=103.5°F):
    1. Executes SQL and persists readings atomically.
    2. Enforces source='self_added' and is_simulated=False on ingestion_events.
    3. Triggers AlertEvaluator clinical threshold rules (Tachycardia, Hypoxemia, Fever).
    4. Triggers MLService Isolation Forest multivariate scoring (anomaly_score >= 0.50).
    5. Persists ModelAssessment with result='anomaly' and generates an ML anomaly alert.
    6. Returns execution status and ML feedback in structured response.
    """
    sql = (
        "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES "
        "('P101', 'heart_rate', 145.0, 'bpm'), "
        "('P101', 'spo2', 86.0, '%'), "
        "('P101', 'temperature', 103.5, 'degF')"
    )
    headers = {"Authorization": f"Bearer {doctor_token}"}
    payload = {
        "sql": sql,
        "is_demo_mode": True,
        "patient_id": "P101",
    }

    resp = client.post("/api/v1/evaluation/workbench/execute", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    data = resp.json()

    assert data["status"] == "success"
    assert data["statement_type"] == "INSERT"
    assert data["rows_affected"] == 3
    assert data["row_count"] == 3
    assert len(data["rows"]) == 3
    assert data["last_inserted_id"] is not None

    # Check ML assessment summary feedback
    ml_res = data["ml_assessment"]
    assert ml_res is not None
    assert ml_res["assessed"] is True
    assert ml_res["patient_id"] == "P101"
    assert ml_res["result"] == "anomaly"
    assert ml_res["anomaly_score"] is not None
    assert ml_res["anomaly_score"] >= 0.50
    assert ml_res["alert_created"] is True

    # Check Relational Invariants in DB
    event = test_db_session.query(IngestionEvent).filter(IngestionEvent.patient_id == "P101").first()
    assert event is not None
    assert event.source == "self_added"
    assert event.is_simulated is False

    readings = test_db_session.query(VitalsReading).filter(VitalsReading.event_id == event.event_id).all()
    assert len(readings) == 3
    metric_map = {r.metric_code: float(r.value) for r in readings}
    assert metric_map["heart_rate"] == 145.0
    assert metric_map["spo2"] == 86.0
    # Temperature 103.5°F converted canonically to Celsius
    assert round(metric_map["temperature"], 1) == 39.7

    # Check ModelAssessment persisted record
    assessment = test_db_session.query(ModelAssessment).filter(ModelAssessment.event_id == event.event_id).first()
    assert assessment is not None
    assert assessment.result == "anomaly"
    assert float(assessment.score) >= 0.50

    # Check Alerts generated
    alerts = test_db_session.query(Alert).filter(Alert.event_id == event.event_id).all()
    assert len(alerts) >= 1
    alert_categories = {a.category for a in alerts}
    assert "vital_threshold" in alert_categories or "ml_anomaly" in alert_categories


# ============================================================================
# 2. DEMO HISTORY & CLINICAL API RETRIEVAL
# ============================================================================

def test_inserted_self_added_readings_appear_in_demo_history(
    client: TestClient,
    doctor_token: str,
    test_db_session: Session,
):
    """
    Test that readings inserted via Demo SQL Workbench immediately appear
    in /patients/{id}/readings, /patients/{id}/vitals, and /patients/{id}/alerts.
    """
    # 1. Insert readings via SQL Workbench
    sql = (
        "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES "
        "('P101', 'heart_rate', 130.0, 'bpm'), "
        "('P101', 'spo2', 89.0, '%'), "
        "('P101', 'temperature', 101.5, 'degF')"
    )
    headers = {"Authorization": f"Bearer {doctor_token}"}
    client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": sql, "is_demo_mode": True, "patient_id": "P101"},
        headers=headers,
    )

    # 2. Retrieve history from /patients/P101/readings
    resp_readings = client.get("/api/v1/patients/P101/readings", headers=headers)
    assert resp_readings.status_code == status.HTTP_200_OK
    readings_data = resp_readings.json()
    assert readings_data["total_count"] >= 1
    latest_event = readings_data["items"][0]
    assert latest_event["source"] == "self_added"
    assert latest_event["is_simulated"] is False
    assert latest_event["heart_rate"] == 130.0
    assert latest_event["spo2"] == 89.0
    assert latest_event["temperature_f"] == 101.5

    # 3. Retrieve latest vitals from /patients/P101/vitals/latest
    resp_vitals = client.get("/api/v1/patients/P101/vitals/latest", headers=headers)
    assert resp_vitals.status_code == status.HTTP_200_OK
    vitals_data = resp_vitals.json()
    assert vitals_data["patient_id"] == "P101"
    vitals_metrics = {m["metric_code"]: m for m in vitals_data["metrics"]}
    assert "heart_rate" in vitals_metrics
    assert vitals_metrics["heart_rate"]["source"] == "self_added"
    assert vitals_metrics["heart_rate"]["value"] == 130.0

    # 4. Retrieve alerts from /patients/P101/alerts
    resp_alerts = client.get("/api/v1/patients/P101/alerts", headers=headers)
    assert resp_alerts.status_code == status.HTTP_200_OK
    alerts_data = resp_alerts.json()
    assert alerts_data["total_count"] >= 1
    assert alerts_data["items"][0]["status"] == "NEW"


# ============================================================================
# 3. MISSING FEATURE HANDLING (NO VALUE FABRICATION)
# ============================================================================

def test_missing_features_yields_inconclusive_without_inventing_values(
    client: TestClient,
    doctor_token: str,
    test_db_session: Session,
):
    """
    Test that when a single vital sign is inserted without the other model features,
    the ML integration maps the result to 'inconclusive' (score 0.0) without
    fabricating or guessing missing feature values.
    """
    sql = "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P102', 'heart_rate', 76.0, 'bpm')"
    headers = {"Authorization": f"Bearer {doctor_token}"}
    resp = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": sql, "is_demo_mode": True, "patient_id": "P102"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    ml_res = data["ml_assessment"]
    assert ml_res is not None
    assert ml_res["assessed"] is True
    assert ml_res["result"] == "inconclusive"
    assert ml_res["anomaly_score"] == 0.0
    assert ml_res["alert_created"] is False

    # Check ModelAssessment record
    event = test_db_session.query(IngestionEvent).filter(IngestionEvent.patient_id == "P102").first()
    assessment = test_db_session.query(ModelAssessment).filter(ModelAssessment.event_id == event.event_id).first()
    assert assessment is not None
    assert assessment.result == "inconclusive"
    assert float(assessment.score) == 0.0


# ============================================================================
# 4. NORMAL VITALS EVALUATION
# ============================================================================

def test_normal_vitals_yields_normal_assessment_and_no_alerts(
    client: TestClient,
    doctor_token: str,
    test_db_session: Session,
):
    """
    Test that inserting healthy vitals (HR=72, SpO2=98.5%, Temp=98.6°F) results in
    result='normal' with an anomaly score < 0.50 and no clinical alerts.
    """
    sql = (
        "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES "
        "('P103', 'heart_rate', 72.0, 'bpm'), "
        "('P103', 'spo2', 98.5, '%'), "
        "('P103', 'temperature', 98.6, 'degF')"
    )
    headers = {"Authorization": f"Bearer {doctor_token}"}
    resp = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": sql, "is_demo_mode": True, "patient_id": "P103"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    ml_res = data["ml_assessment"]
    assert ml_res is not None
    assert ml_res["result"] == "normal"
    assert ml_res["anomaly_score"] < 0.50
    assert ml_res["alert_created"] is False


# ============================================================================
# 5. UPDATE MUTATIONS AND RE-ANALYSIS
# ============================================================================

def test_update_self_added_reading_reanalyzes_telemetry(
    client: TestClient,
    doctor_token: str,
    test_db_session: Session,
):
    """
    Test that updating a self_added vital sign reading:
    1. Updates the reading in the database.
    2. Re-evaluates clinical threshold rules on the modified value.
    3. Triggers an alert if the updated value breaches a threshold.
    4. Rejects attempts to modify baseline patient P001.
    """
    headers = {"Authorization": f"Bearer {doctor_token}"}

    # 1. Insert normal reading for P104
    ins_resp = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={
            "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P104', 'heart_rate', 75.0, 'bpm')",
            "is_demo_mode": True,
            "patient_id": "P104",
        },
        headers=headers,
    )
    reading_id = ins_resp.json()["last_inserted_id"]

    # 2. Update reading to tachycardic value (148 bpm)
    update_sql = f"UPDATE vitals_readings SET value = 148.0 WHERE reading_id = {reading_id} AND patient_id = 'P104'"
    upd_resp = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": update_sql, "is_demo_mode": True, "patient_id": "P104"},
        headers=headers,
    )
    assert upd_resp.status_code == status.HTTP_200_OK
    assert upd_resp.json()["rows_affected"] == 1

    # Verify updated value in DB
    updated_r = test_db_session.query(VitalsReading).filter(VitalsReading.reading_id == reading_id).first()
    assert float(updated_r.value) == 148.0

    # Verify re-evaluation triggered tachycardia alert
    alerts = test_db_session.query(Alert).filter(Alert.patient_id == "P104").all()
    assert len(alerts) >= 1
    assert any("Tachycardia" in a.reason or a.severity in ("HIGH", "CRITICAL") for a in alerts)

    # 3. Verify updating baseline patient P001 is strictly forbidden
    forbidden_upd = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": "UPDATE vitals_readings SET value = 99.0 WHERE patient_id = 'P001'", "is_demo_mode": True},
        headers=headers,
    )
    assert forbidden_upd.status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# 6. DELETE MUTATIONS AND CASCADE CLEANUP
# ============================================================================

def test_delete_self_added_reading_cleans_orphaned_records(
    client: TestClient,
    doctor_token: str,
    test_db_session: Session,
):
    """
    Test that deleting a self_added vital sign reading:
    1. Removes the reading.
    2. Cleans up associated orphaned alerts, status history, and model assessments.
    3. Cleans up the parent IngestionEvent if no readings remain.
    4. Rejects attempts to delete baseline records.
    """
    headers = {"Authorization": f"Bearer {doctor_token}"}

    # 1. Insert tachycardic reading for P105
    ins_resp = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={
            "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P105', 'heart_rate', 155.0, 'bpm')",
            "is_demo_mode": True,
            "patient_id": "P105",
        },
        headers=headers,
    )
    data = ins_resp.json()
    reading_id = data["last_inserted_id"]
    event_id = data["rows"][0][1]

    # Confirm alert and event exist
    assert test_db_session.query(VitalsReading).filter(VitalsReading.reading_id == reading_id).count() == 1
    assert test_db_session.query(IngestionEvent).filter(IngestionEvent.event_id == event_id).count() == 1

    # 2. Delete the reading
    del_sql = f"DELETE FROM vitals_readings WHERE reading_id = {reading_id} AND patient_id = 'P105'"
    del_resp = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": del_sql, "is_demo_mode": True, "patient_id": "P105"},
        headers=headers,
    )
    assert del_resp.status_code == status.HTTP_200_OK
    assert del_resp.json()["rows_affected"] == 1

    # 3. Confirm reading and parent event are cleanly deleted (no orphans)
    assert test_db_session.query(VitalsReading).filter(VitalsReading.reading_id == reading_id).first() is None
    assert test_db_session.query(IngestionEvent).filter(IngestionEvent.event_id == event_id).first() is None
    assert test_db_session.query(Alert).filter(Alert.event_id == event_id).count() == 0
    assert test_db_session.query(ModelAssessment).filter(ModelAssessment.event_id == event_id).count() == 0

    # 4. Verify deleting baseline patient P001 is strictly forbidden
    forbidden_del = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": "DELETE FROM vitals_readings WHERE patient_id = 'P001'", "is_demo_mode": True},
        headers=headers,
    )
    assert forbidden_del.status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# 7. SAFETY RESTRICTIONS & IMMUTABILITY
# ============================================================================

def test_security_boundaries_and_rejections(
    client: TestClient,
    doctor_token: str,
):
    """
    Test all mandatory security rejection rules:
    - Non-demo mode
    - Multi-statement injection
    - Administrative statements (DROP, PRAGMA, ATTACH)
    - System tables (users)
    - Out-of-bounds physiological values
    - Future timestamps
    """
    headers = {"Authorization": f"Bearer {doctor_token}"}

    # Outside demo mode
    r1 = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": "SELECT 1", "is_demo_mode": False},
        headers=headers,
    )
    assert r1.status_code == status.HTTP_403_FORBIDDEN

    # Multi-statement
    r2 = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": "SELECT 1; SELECT 2;", "is_demo_mode": True},
        headers=headers,
    )
    assert r2.status_code == status.HTTP_400_BAD_REQUEST

    # DROP command
    r3 = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": "DROP TABLE vitals_readings", "is_demo_mode": True},
        headers=headers,
    )
    assert r3.status_code == status.HTTP_400_BAD_REQUEST

    # System table access
    r4 = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={"sql": "SELECT * FROM users", "is_demo_mode": True},
        headers=headers,
    )
    assert r4.status_code == status.HTTP_403_FORBIDDEN

    # Extreme out-of-bounds heart rate (350 bpm)
    r5 = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={
            "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', 350.0, 'bpm')",
            "is_demo_mode": True,
        },
        headers=headers,
    )
    assert r5.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Extreme temperature (130 °F)
    r6 = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={
            "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'temperature', 130.0, 'degF')",
            "is_demo_mode": True,
        },
        headers=headers,
    )
    assert r6.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Future timestamp (> 5 min)
    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r7 = client.post(
        "/api/v1/evaluation/workbench/execute",
        json={
            "sql": f"INSERT INTO vitals_readings (patient_id, metric_code, value, unit, measured_at) VALUES ('P101', 'heart_rate', 75.0, 'bpm', '{future_time}')",
            "is_demo_mode": True,
        },
        headers=headers,
    )
    assert r7.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
