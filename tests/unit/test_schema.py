"""
Unit Test Suite for MySQL Schema, Models, and Relational Constraints.

Executes in complete isolation against an in-memory SQLite engine with PRAGMA foreign_keys=ON.
Requires no external network, credentials, or running MySQL service.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from database.mysql.models import (
    Alert,
    AlertRule,
    AlertStatusHistory,
    AuditLog,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    ImportBatch,
    IngestionEvent,
    Message,
    ModelAssessment,
    NotificationDelivery,
    PatientBaseline,
    PatientProfile,
    User,
    VitalsReading,
)


@pytest.fixture(scope="function")
def in_memory_engine():
    """Create a fresh in-memory SQLite engine with foreign key enforcement enabled."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
    )

    # Enable SQLite foreign key constraint enforcement
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(in_memory_engine) -> Session:
    """Provide a transactional session for each unit test."""
    session_factory = sessionmaker(bind=in_memory_engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# =============================================================================
# 1. Schema Structure and Metadata Integrity
# =============================================================================

def test_all_expected_tables_present_in_metadata():
    """Verify that all 15 authoritative tables are registered in metadata."""
    expected_tables = {
        "import_batches",
        "users",
        "patient_profiles",
        "doctor_profiles",
        "doctor_patient_assignments",
        "ingestion_events",
        "vitals_readings",
        "alert_rules",
        "patient_baselines",
        "model_assessments",
        "alerts",
        "alert_status_history",
        "notification_deliveries",
        "messages",
        "audit_logs",
    }
    actual_tables = set(Base.metadata.tables.keys())
    missing = expected_tables - actual_tables
    assert not missing, f"Missing tables in metadata: {missing}"
    assert expected_tables == actual_tables


def test_table_columns_and_types(in_memory_engine):
    """Verify table column names, primary keys, and types using inspector."""
    inspector = inspect(in_memory_engine)
    
    # Check users table
    user_cols = {col["name"]: col for col in inspector.get_columns("users")}
    assert "user_id" in user_cols
    assert "email" in user_cols
    assert "password_hash" in user_cols
    assert "role" in user_cols
    assert "is_active" in user_cols
    user_pk = inspector.get_pk_constraint("users")
    assert user_pk["constrained_columns"] == ["user_id"]

    # Check vitals_readings table
    vitals_cols = {col["name"]: col for col in inspector.get_columns("vitals_readings")}
    assert "reading_id" in vitals_cols
    assert "event_id" in vitals_cols
    assert "patient_id" in vitals_cols
    assert "metric_code" in vitals_cols
    assert "value" in vitals_cols
    assert "unit" in vitals_cols
    assert "raw_value" in vitals_cols
    assert "raw_unit" in vitals_cols
    assert "quality_status" in vitals_cols
    assert "measured_at" in vitals_cols


# =============================================================================
# 2. Identity and Access Control Constraints
# =============================================================================

def test_user_email_uniqueness_enforced(db_session: Session):
    """Verify that inserting duplicate emails raises an IntegrityError."""
    u1 = User(
        user_id="usr_001",
        email="patient@example.com",
        password_hash="$2b$12$fakehashedpassword0000000000000000000000000000000",
        role="patient",
    )
    db_session.add(u1)
    db_session.commit()

    u2 = User(
        user_id="usr_002",
        email="patient@example.com",  # Duplicate email
        password_hash="$2b$12$anotherfakehash00000000000000000000000000000000",
        role="patient",
    )
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_patient_and_doctor_profiles_cascade_delete(db_session: Session):
    """Verify 1-to-1 profile creation and CASCADE deletion when parent user is removed."""
    # Create user and patient profile
    patient_user = User(
        user_id="usr_pat_101",
        email="p101@example.com",
        password_hash="hashed_pw_p101",
        role="patient",
    )
    patient = PatientProfile(
        patient_id="P101",
        user_id="usr_pat_101",
        first_name="John",
        last_name="Doe",
        date_of_birth=date(1985, 4, 12),
        gender="male",
        height_cm=Decimal("178.50"),
        weight_kg=Decimal("74.20"),
    )
    db_session.add_all([patient_user, patient])
    db_session.commit()

    # Query back
    queried_patient = db_session.get(PatientProfile, "P101")
    assert queried_patient is not None
    assert queried_patient.first_name == "John"
    assert queried_patient.user.email == "p101@example.com"

    # Delete parent user -> PatientProfile should be removed via CASCADE
    db_session.delete(patient_user)
    db_session.commit()
    assert db_session.get(PatientProfile, "P101") is None


def test_doctor_patient_assignment_composite_pk(db_session: Session):
    """Verify composite primary key and foreign keys on doctor_patient_assignments."""
    # Setup doctor
    doc_user = User(user_id="usr_doc_1", email="doc1@hospital.org", password_hash="hash", role="doctor")
    doc = DoctorProfile(doctor_id="D001", user_id="usr_doc_1", first_name="Sarah", last_name="Connor", license_number="MD-98765")

    # Setup patient
    pat_user = User(user_id="usr_pat_101", email="p101@hospital.org", password_hash="hash", role="patient")
    pat = PatientProfile(patient_id="P101", user_id="usr_pat_101", first_name="John", last_name="Doe")

    db_session.add_all([doc_user, doc, pat_user, pat])
    db_session.commit()

    # Assign doctor to patient
    assignment = DoctorPatientAssignment(
        doctor_id="D001",
        patient_id="P101",
        is_active=True,
        notes="Primary cardiologist assignment",
    )
    db_session.add(assignment)
    db_session.commit()

    # Verify duplicate assignment raises IntegrityError at database level
    with pytest.raises(IntegrityError):
        db_session.execute(
            DoctorPatientAssignment.__table__.insert().values(
                doctor_id="D001",
                patient_id="P101",
                is_active=True,
            )
        )
        db_session.commit()


# =============================================================================
# 3. Provenance, Ingestion Events, and Vitals Readings
# =============================================================================

def test_ingestion_event_idempotency_constraint(db_session: Session):
    """Verify that duplicate (source, source_event_id) pairs are rejected."""
    # Setup patient
    u = User(user_id="usr_p101", email="p101@test.com", password_hash="h", role="patient")
    p = PatientProfile(patient_id="P101", user_id="usr_p101", first_name="P", last_name="101")
    db_session.add_all([u, p])
    db_session.commit()

    now = datetime.now(timezone.utc)
    ev1 = IngestionEvent(
        event_id="evt_001",
        patient_id="P101",
        source="kaggle_csv",
        source_event_id="kaggle_P101_2026-10-01T00:00:00Z",
        measured_at=now,
        is_simulated=False,
        mirror_status="pending",
    )
    db_session.add(ev1)
    db_session.commit()

    # Replay same event with identical source and source_event_id
    ev_replay = IngestionEvent(
        event_id="evt_002",
        patient_id="P101",
        source="kaggle_csv",
        source_event_id="kaggle_P101_2026-10-01T00:00:00Z",
        measured_at=now,
        is_simulated=False,
    )
    db_session.add(ev_replay)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_vitals_readings_normalization_and_units(db_session: Session):
    """
    Verify normalized readings per event:
    Stores canonical Celsius value and raw Fahrenheit value for temperature.
    Enforces uniqueness of (event_id, metric_code).
    """
    u = User(user_id="usr_p102", email="p102@test.com", password_hash="h", role="patient")
    p = PatientProfile(patient_id="P102", user_id="usr_p102", first_name="Jane", last_name="Smith")
    now = datetime.now(timezone.utc)
    ev = IngestionEvent(
        event_id="evt_p102_001",
        patient_id="P102",
        source="kaggle_csv",
        source_event_id="kaggle_p102_001",
        measured_at=now,
        is_simulated=False,
    )
    db_session.add_all([u, p, ev])
    db_session.commit()

    # 1. Heart rate reading
    r_hr = VitalsReading(
        event_id="evt_p102_001",
        patient_id="P102",
        metric_code="heart_rate",
        value=Decimal("78.00"),
        unit="bpm",
        raw_value=Decimal("78.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    # 2. SpO2 reading
    r_spo2 = VitalsReading(
        event_id="evt_p102_001",
        patient_id="P102",
        metric_code="spo2",
        value=Decimal("98.50"),
        unit="%",
        raw_value=Decimal("98.50"),
        raw_unit="%",
        quality_status="valid",
        measured_at=now,
    )
    # 3. Temperature reading (Raw: 98.6 degF -> Canonical: 37.00 degC)
    r_temp = VitalsReading(
        event_id="evt_p102_001",
        patient_id="P102",
        metric_code="temperature",
        value=Decimal("37.00"),
        unit="degC",
        raw_value=Decimal("98.60"),
        raw_unit="degF",
        quality_status="valid",
        measured_at=now,
    )
    db_session.add_all([r_hr, r_spo2, r_temp])
    db_session.commit()

    # Query readings for the event
    queried_event = db_session.get(IngestionEvent, "evt_p102_001")
    assert queried_event is not None
    assert len(queried_event.readings) == 3

    temp_reading = [r for r in queried_event.readings if r.metric_code == "temperature"][0]
    assert temp_reading.raw_value == Decimal("98.60")
    assert temp_reading.raw_unit == "degF"
    assert temp_reading.value == Decimal("37.00")
    assert temp_reading.unit == "degC"

    # Enforce at most one reading per metric code per event
    dup_temp = VitalsReading(
        event_id="evt_p102_001",
        patient_id="P102",
        metric_code="temperature",
        value=Decimal("37.10"),
        unit="degC",
        raw_value=Decimal("98.78"),
        raw_unit="degF",
        quality_status="valid",
        measured_at=now,
    )
    db_session.add(dup_temp)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_foreign_key_rejects_orphan_vitals(db_session: Session):
    """Verify that inserting a reading referencing a non-existent event fails."""
    orphan_reading = VitalsReading(
        event_id="non_existent_event",
        patient_id="non_existent_patient",
        metric_code="heart_rate",
        value=Decimal("80.00"),
        unit="bpm",
        raw_value=Decimal("80.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=datetime.now(timezone.utc),
    )
    db_session.add(orphan_reading)
    with pytest.raises(IntegrityError):
        db_session.commit()


# =============================================================================
# 4. Alerts, Assessments, and Lifecycle State
# =============================================================================

def test_alert_lifecycle_and_status_history(db_session: Session):
    """Verify alert creation, lifecycle state changes, and history tracking."""
    # Setup patient and clinician
    p_user = User(user_id="usr_p103", email="p103@test.com", password_hash="h", role="patient")
    p = PatientProfile(patient_id="P103", user_id="usr_p103", first_name="Bob", last_name="Taylor")
    d_user = User(user_id="usr_doc_99", email="doc99@test.com", password_hash="h", role="doctor")
    d = DoctorProfile(doctor_id="D099", user_id="usr_doc_99", first_name="Dr.", last_name="House", license_number="MD-99")
    db_session.add_all([p_user, p, d_user, d])
    db_session.commit()

    # Create new alert
    alert = Alert(
        alert_id="alt_001",
        patient_id="P103",
        severity="HIGH",
        category="vital_threshold",
        reason="Heart rate exceeded 130 bpm (tachycardia)",
        status="NEW",
    )
    db_session.add(alert)
    db_session.commit()

    assert alert.status == "NEW"
    assert alert.acknowledged_at is None

    # Clinician acknowledges alert
    now = datetime.now(timezone.utc)
    alert.status = "ACKNOWLEDGED"
    alert.acknowledged_by = d_user.user_id
    alert.acknowledged_at = now

    history = AlertStatusHistory(
        alert_id=alert.alert_id,
        old_status="NEW",
        new_status="ACKNOWLEDGED",
        actor_id=d_user.user_id,
        note="Reviewed by Dr. House; ordered 12-lead ECG",
        changed_at=now,
    )
    db_session.add(history)
    db_session.commit()

    # Query back
    updated_alert = db_session.get(Alert, "alt_001")
    assert updated_alert is not None
    assert updated_alert.status == "ACKNOWLEDGED"
    assert updated_alert.acknowledged_by == d_user.user_id
    assert len(updated_alert.status_history) == 1
    assert updated_alert.status_history[0].new_status == "ACKNOWLEDGED"


def test_model_assessment_linkage(db_session: Session):
    """Verify Isolation Forest ML assessment records and optional linkage to alerts."""
    u = User(user_id="usr_p104", email="p104@test.com", password_hash="h", role="patient")
    p = PatientProfile(patient_id="P104", user_id="usr_p104", first_name="Alice", last_name="Brown")
    db_session.add_all([u, p])
    db_session.commit()

    assessment = ModelAssessment(
        assessment_id="asm_001",
        patient_id="P104",
        model_version="isolation_forest_v1",
        score=Decimal("-0.2450"),
        result="anomaly",
        features_json='{"heart_rate": 142.0, "spo2": 89.0, "temperature_f": 102.4}',
    )
    db_session.add(assessment)
    db_session.commit()

    alert = Alert(
        alert_id="alt_ml_001",
        patient_id="P104",
        assessment_id="asm_001",
        severity="CRITICAL",
        category="ml_anomaly",
        reason="Multi-vital acute anomaly detected by Isolation Forest (score: -0.2450)",
        status="NEW",
    )
    db_session.add(alert)
    db_session.commit()

    queried_alert = db_session.get(Alert, "alt_ml_001")
    assert queried_alert is not None
    assert queried_alert.assessment is not None
    assert queried_alert.assessment.result == "anomaly"


# =============================================================================
# 5. Direct Messages and Compliance Audit Logs
# =============================================================================

def test_messages_and_audit_trail(db_session: Session):
    """Verify direct message flow and audit trail logging."""
    u_pat = User(user_id="usr_p105", email="p105@test.com", password_hash="h", role="patient")
    p = PatientProfile(patient_id="P105", user_id="usr_p105", first_name="Chris", last_name="Green")
    u_doc = User(user_id="usr_doc_5", email="doc5@test.com", password_hash="h", role="doctor")
    d = DoctorProfile(doctor_id="D005", user_id="usr_doc_5", first_name="Dr.", last_name="Watson", license_number="MD-05")
    db_session.add_all([u_pat, p, u_doc, d])
    db_session.commit()

    # Send message from doctor to patient
    msg = Message(
        message_id="msg_001",
        sender_id=u_doc.user_id,
        receiver_id=u_pat.user_id,
        patient_context_id="P105",
        content="Please take your prescribed medication and rest.",
        is_read=False,
    )
    db_session.add(msg)

    # Log audit event for message dispatch
    audit = AuditLog(
        actor_id=u_doc.user_id,
        action="MESSAGE_SEND",
        target_type="message",
        target_id="msg_001",
        ip_address="127.0.0.1",
        metadata_json='{"patient_id": "P105"}',
    )
    db_session.add(audit)
    db_session.commit()

    # Verify queryability
    unread_messages = db_session.scalars(
        select(Message).where(Message.receiver_id == u_pat.user_id, Message.is_read == False)
    ).all()
    assert len(unread_messages) == 1
    assert unread_messages[0].content == "Please take your prescribed medication and rest."

    logs = db_session.scalars(
        select(AuditLog).where(AuditLog.actor_id == u_doc.user_id)
    ).all()
    assert len(logs) == 1
    assert logs[0].action == "MESSAGE_SEND"


# =============================================================================
# 6. Alembic Migration Script Validation
# =============================================================================

def test_alembic_offline_sql_generation(capsys):
    """Verify that Alembic generates complete, valid MySQL 8 DDL in offline mode."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head", sql=True)
    captured = capsys.readouterr()
    sql_output = captured.out

    # Verify critical DDL markers exist in generated SQL
    assert "CREATE TABLE import_batches" in sql_output
    assert "CREATE TABLE users" in sql_output
    assert "CREATE TABLE patient_profiles" in sql_output
    assert "CREATE TABLE vitals_readings" in sql_output
    assert "CREATE TABLE alerts" in sql_output
    assert "idx_vitals_patient_metric_time" in sql_output
    assert "uq_events_source_source_event_id" in sql_output
    assert "alembic_version" in sql_output

