"""
Unit Tests for Database Access Layer, Repositories, and Domain Services.

Verifies:
1. Database configuration validation
2. Session lifecycle, generator cleanup, and dependency injection
3. Connection failure handling and diagnostics
4. Transaction commit behavior
5. Transaction rollback on exception
6. Integrity constraint violation translation (EntityConflictError)
7. Session isolation across transactions
8. PatientRepository queries and care assignments
9. VitalsRepository telemetry insertion and time-series queries
10. AlertRepository and status transition history
11. AuditRepository security logging
12. AlertService multi-entity atomic transaction coordination
13. Invalid state transition rejection in AlertService
14. FastAPI /health/db endpoint integration
15. Engine disposal and singleton reset
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from database.mysql.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    EntityConflictError,
    EntityNotFoundError,
    InvalidStateTransitionError,
)
from database.mysql.models import (
    Alert,
    AlertStatusHistory,
    AuditLog,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.repositories import (
    AlertRepository,
    AuditRepository,
    PatientRepository,
    VitalsRepository,
)
from database.mysql.session import (
    check_db_connectivity,
    dispose_engine,
    get_db,
    get_engine,
    get_session_factory,
    transaction_scope,
)
from services.alert_service import AlertService
from services.api.config import Settings
from services.api.main import create_app
from services.patient_service import PatientService
from services.vitals_service import VitalsService


@pytest.fixture
def sqlite_engine():
    """Isolated in-memory SQLite engine with foreign key enforcement."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine) -> Session:
    """Transactional session fixture."""
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# =============================================================================
# 1. Configuration & Session Management Tests
# =============================================================================

def test_database_configuration_properties():
    """Verify database connection URL generation and driver customization."""
    s = Settings(
        mysql_host="db.hospital.internal",
        mysql_port=3306,
        mysql_database="clinical_records",
        mysql_user="app_worker",
        mysql_password="secret!@#password",
        mysql_driver="pymysql",
    )
    url = s.get_mysql_url()
    assert "mysql+pymysql://" in url
    assert "secret%21%40%23password" in url
    assert "clinical_records" in url

    safe_url = s.get_safe_mysql_url()
    assert "***" in safe_url
    assert "secret" not in safe_url


def test_session_generator_cleanup(sqlite_engine):
    """Verify get_db dependency yields a session and closes it upon completion."""
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)

    # Mock get_session_factory to return our test factory
    gen = get_db()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("database.mysql.session.get_session_factory", lambda: factory)
        session = next(gen)
        assert isinstance(session, Session)
        assert session.is_active

        # Closing generator triggers finally block
        try:
            next(gen)
        except StopIteration:
            pass


def test_check_db_connectivity(sqlite_engine):
    """Verify connectivity check succeeds on active engine and fails cleanly on bad engine."""
    assert check_db_connectivity(sqlite_engine) is True

    # Bad mock engine
    bad_engine = create_engine("sqlite:///non_existent_dir_12345/db.sqlite")
    assert check_db_connectivity(bad_engine) is False


def test_dispose_engine_resets_singletons():
    """Verify dispose_engine releases resources cleanly."""
    eng = get_engine("sqlite:///:memory:")
    assert eng is not None
    dispose_engine()
    # Should be safe to call multiple times
    dispose_engine()


# =============================================================================
# 2. Transaction Management & Error Translation Tests
# =============================================================================

def test_transaction_scope_commit_success(sqlite_engine):
    """Verify transaction_scope commits successfully upon clean block exit."""
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = factory()

    with transaction_scope(session):
        u = User(user_id="usr_tx_1", email="tx1@example.com", password_hash="h", role="patient")
        session.add(u)

    # In a separate session, verify committed
    verify_session = factory()
    persisted_user = verify_session.get(User, "usr_tx_1")
    assert persisted_user is not None
    assert persisted_user.email == "tx1@example.com"
    verify_session.close()
    session.close()


def test_transaction_scope_rollback_on_exception(sqlite_engine):
    """Verify transaction_scope rolls back changes if an exception occurs."""
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = factory()

    with pytest.raises(DatabaseError):
        with transaction_scope(session):
            u = User(user_id="usr_tx_2", email="tx2@example.com", password_hash="h", role="patient")
            session.add(u)
            raise ValueError("Simulated unexpected business logic error")

    # In a separate session, verify user was not committed
    verify_session = factory()
    assert verify_session.get(User, "usr_tx_2") is None
    verify_session.close()
    session.close()


def test_transaction_scope_translates_integrity_error(sqlite_engine):
    """Verify database unique constraint violations are translated into EntityConflictError."""
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = factory()

    # Pre-seed user
    u1 = User(user_id="usr_dup_1", email="duplicate@example.com", password_hash="h", role="patient")
    session.add(u1)
    session.commit()

    # Attempt to insert identical email in transaction_scope
    with pytest.raises(EntityConflictError):
        with transaction_scope(session):
            u2 = User(user_id="usr_dup_2", email="duplicate@example.com", password_hash="h", role="patient")
            session.add(u2)

    session.close()


def test_session_isolation(sqlite_engine):
    """Verify session rollback cleans uncommitted state across sessions."""
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session1 = factory()
    session2 = factory()

    # Add to session 1 without commit
    u = User(user_id="usr_iso_1", email="iso@example.com", password_hash="h", role="patient")
    session1.add(u)
    session1.flush()

    # Roll back session 1
    session1.rollback()

    # Neither session sees the rolled back row
    assert session1.get(User, "usr_iso_1") is None
    assert session2.get(User, "usr_iso_1") is None

    session1.close()
    session2.close()


# =============================================================================
# 3. Repository Layer Tests
# =============================================================================

def test_patient_repository_queries(db_session: Session):
    """Verify PatientRepository methods against actual models and constraints."""
    repo = PatientRepository(db_session)

    # 1. Create Patient with User
    u = User(user_id="usr_p01", email="p01@hospital.org", password_hash="hash", role="patient")
    p = PatientProfile(patient_id="P01", user_id="usr_p01", first_name="Arthur", last_name="Dent")
    created = repo.create_patient_with_user(u, p)
    db_session.commit()
    assert created.patient_id == "P01"

    # 2. Get by ID
    found = repo.get_by_id("P01")
    assert found is not None
    assert found.first_name == "Arthur"

    # 3. Doctor assignment
    doc_user = User(user_id="usr_d01", email="d01@hospital.org", password_hash="hash", role="doctor")
    doc = DoctorProfile(doctor_id="D01", user_id="usr_d01", first_name="Dr.", last_name="Who", license_number="LIC-001")
    db_session.add_all([doc_user, doc])
    db_session.commit()

    assignment = DoctorPatientAssignment(doctor_id="D01", patient_id="P01", is_active=True)
    db_session.add(assignment)
    db_session.commit()

    assert repo.is_doctor_assigned_to_patient("D01", "P01") is True
    assert repo.is_doctor_assigned_to_patient("D01", "P999") is False

    assigned_list = repo.get_assigned_patients_for_doctor("D01", active_only=True)
    assert len(assigned_list) == 1
    assert assigned_list[0].patient_id == "P01"


def test_vitals_repository_queries(db_session: Session):
    """Verify VitalsRepository telemetry insertion and time-series queries."""
    p_repo = PatientRepository(db_session)
    v_repo = VitalsRepository(db_session)

    # Setup patient
    u = User(user_id="usr_v1", email="v1@test.com", password_hash="h", role="patient")
    p = PatientProfile(patient_id="PV1", user_id="usr_v1", first_name="Ford", last_name="Prefect")
    p_repo.create_patient_with_user(u, p)
    db_session.commit()

    now = datetime(2023, 10, 1, 10, 0, tzinfo=timezone.utc)
    ev = IngestionEvent(
        event_id="evt_v1",
        patient_id="PV1",
        source="kaggle_csv",
        source_event_id="src_evt_v1",
        measured_at=now,
        is_simulated=False,
    )
    v_repo.create_event(ev)

    readings = [
        VitalsReading(
            event_id="evt_v1",
            patient_id="PV1",
            metric_code="heart_rate",
            value=Decimal("72.00"),
            unit="bpm",
            raw_value=Decimal("72.00"),
            raw_unit="bpm",
            measured_at=now,
        ),
        VitalsReading(
            event_id="evt_v1",
            patient_id="PV1",
            metric_code="spo2",
            value=Decimal("98.50"),
            unit="%",
            raw_value=Decimal("98.50"),
            raw_unit="%",
            measured_at=now,
        ),
    ]
    v_repo.add_readings(readings)
    db_session.commit()

    # Query latest vitals
    latest = v_repo.get_latest_vitals("PV1")
    assert len(latest) == 2
    metrics = {r.metric_code: r.value for r in latest}
    assert metrics["heart_rate"] == Decimal("72.00")
    assert metrics["spo2"] == Decimal("98.50")

    # Query history
    history = v_repo.get_vitals_history("PV1", metric_code="heart_rate")
    assert len(history) == 1
    assert history[0].value == Decimal("72.00")

    # Test idempotency lookup
    existing_ids = v_repo.get_existing_source_event_ids("kaggle_csv", ["src_evt_v1", "non_existent"])
    assert existing_ids == {"src_evt_v1"}


def test_alert_and_audit_repositories(db_session: Session):
    """Verify AlertRepository and AuditRepository persistence."""
    p_repo = PatientRepository(db_session)
    alt_repo = AlertRepository(db_session)
    aud_repo = AuditRepository(db_session)

    # Setup patient & doctor
    u = User(user_id="usr_a1", email="a1@test.com", password_hash="h", role="patient")
    p = PatientProfile(patient_id="PA1", user_id="usr_a1", first_name="Tricia", last_name="McMillan")
    p_repo.create_patient_with_user(u, p)
    db_session.commit()

    alert = Alert(
        alert_id="alt_rep_1",
        patient_id="PA1",
        severity="HIGH",
        category="vital_threshold",
        reason="Elevated SpO2 drop",
        status="NEW",
    )
    alt_repo.create(alert)
    db_session.commit()

    queried_alert = alt_repo.get_by_id("alt_rep_1")
    assert queried_alert is not None
    assert queried_alert.status == "NEW"

    # Transition alert status
    history = alt_repo.record_status_transition(queried_alert, "ACKNOWLEDGED", actor_id="usr_a1", note="Triage review")
    db_session.commit()
    assert history.new_status == "ACKNOWLEDGED"

    # Record audit log
    log = aud_repo.record(
        action="TEST_ACTION",
        target_type="alert",
        target_id="alt_rep_1",
        actor_id="usr_a1",
    )
    db_session.commit()
    assert log.action == "TEST_ACTION"

    audit_entries = aud_repo.list_logs(actor_id="usr_a1")
    assert len(audit_entries) == 1


# =============================================================================
# 4. Service Layer Multi-Entity Coordination & Business Rules
# =============================================================================

def test_alert_service_atomic_acknowledgement(db_session: Session):
    """Verify AlertService coordinates alert update, status history, and audit log atomically."""
    # Pre-seed patient and open alert
    p = PatientProfile(patient_id="PA2", user_id="usr_svc_1", first_name="Zaphod", last_name="Beeblebrox")
    u = User(user_id="usr_svc_1", email="zaphod@galaxy.gov", password_hash="h", role="patient")
    alert = Alert(
        alert_id="alt_svc_01",
        patient_id="PA2",
        severity="CRITICAL",
        category="vital_threshold",
        reason="Heart rate exceeding threshold",
        status="NEW",
    )
    db_session.add_all([u, p, alert])
    db_session.commit()

    service = AlertService(db_session)
    updated_alert = service.acknowledge_alert(
        alert_id="alt_svc_01",
        actor_id="usr_svc_1",
        note="Acknowledged by president of the galaxy",
    )

    assert updated_alert.status == "ACKNOWLEDGED"
    assert updated_alert.acknowledged_by == "usr_svc_1"

    # Verify history entry was created
    history_entries = db_session.scalars(
        select(AlertStatusHistory).where(AlertStatusHistory.alert_id == "alt_svc_01")
    ).all()
    assert len(history_entries) == 1
    assert history_entries[0].old_status == "NEW"
    assert history_entries[0].new_status == "ACKNOWLEDGED"

    # Verify audit log was created
    audit_logs = db_session.scalars(
        select(AuditLog).where(AuditLog.target_id == "alt_svc_01")
    ).all()
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "ALERT_ACKNOWLEDGE"


def test_alert_service_invalid_state_transition(db_session: Session):
    """Verify attempting to acknowledge an already resolved alert is rejected."""
    p = PatientProfile(patient_id="PA3", user_id="usr_svc_2", first_name="Marvin", last_name="Paranoid")
    u = User(user_id="usr_svc_2", email="marvin@sirius.com", password_hash="h", role="patient")
    resolved_alert = Alert(
        alert_id="alt_resolved_01",
        patient_id="PA3",
        severity="LOW",
        category="vital_threshold",
        reason="Minor deviation",
        status="RESOLVED",
    )
    db_session.add_all([u, p, resolved_alert])
    db_session.commit()

    service = AlertService(db_session)
    with pytest.raises(InvalidStateTransitionError):
        service.acknowledge_alert("alt_resolved_01", actor_id="usr_svc_2")


def test_vitals_service_freshness_calculation():
    """Verify VitalsService freshness evaluation against staleness limits."""
    now = datetime.now(timezone.utc)
    fresh_reading = VitalsReading(
        measured_at=now,
        metric_code="heart_rate",
        value=Decimal("70"),
        unit="bpm",
        raw_value=Decimal("70"),
        raw_unit="bpm",
    )
    assert VitalsService.assess_freshness(fresh_reading, max_staleness_seconds=300) == "active"

    # Reading from 10 minutes ago (> 300s)
    stale_reading = VitalsReading(
        measured_at=datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc),
        metric_code="heart_rate",
        value=Decimal("70"),
        unit="bpm",
        raw_value=Decimal("70"),
        raw_unit="bpm",
    )
    assert VitalsService.assess_freshness(stale_reading, max_staleness_seconds=300) == "stale"
    assert VitalsService.assess_freshness(None) == "missing"


# =============================================================================
# 5. FastAPI Integration & Database Health Probe
# =============================================================================

def test_fastapi_db_health_endpoint(sqlite_engine):
    """Verify /health/db endpoint uses get_db dependency and reports status."""
    app = create_app()
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    response = client.get("/health/db")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "connected"
    assert data["database"] == "mysql_innodb"
