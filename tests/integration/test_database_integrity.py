"""
Database Integrity, Relational Constraints, Transaction Atomicity, and Outbox Resilience Test Suite.

Verifies:
1. Foreign key constraints and cascade deletions (patient deletion cascades to telemetry, alerts).
2. Unique constraint enforcement:
   - IngestionEvent (source, source_event_id)
   - VitalsReading (event_id, metric_code)
   - Conversation (patient_id, doctor_id)
   - Message (sender_id, idempotency_key)
3. Transaction atomicity: multi-entity insertions roll back cleanly on errors without residual state.
4. Analytics outbox queueing, retry lifecycle, error recording, and recovery processing.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Generator
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.exceptions import DatabaseError
from database.mysql.models import (
    Alert,
    AlertRule,
    AnalyticsOutbox,
    Base,
    Conversation,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    Message,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.repositories.outbox_repository import OutboxRepository
from database.mysql.session import transaction_scope
from services.alerts.rules import DEFAULT_ALERT_RULES


@pytest.fixture(scope="function")
def integrity_db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable SQLite foreign key enforcement
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    # Pre-populate default alert rules
    for r in DEFAULT_ALERT_RULES:
        rule = AlertRule(
            rule_id=r.rule_id,
            metric_code=r.metric_code,
            operator=r.operator,
            configured_value=r.configured_value,
            duration_seconds=getattr(r, "duration_seconds", 0),
            severity=r.severity,
            is_enabled=r.is_enabled,
            is_demo_only=r.is_demo_only,
            description=r.description,
        )
        session.add(rule)
    session.commit()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# =============================================================================
# 1. Foreign Key Cascades and Constraints
# =============================================================================

def test_patient_cascade_deletion(integrity_db: Session):
    """Verify that deleting a patient cascades to vitals readings and alerts."""
    now = datetime.now(timezone.utc)

    # 1. Create User and Patient
    u = User(user_id="U_CAS_1", email="cascade_test@example.com", password_hash="hash", role="patient", is_active=True)
    p = PatientProfile(patient_id="P_CAS_1", user_id="U_CAS_1", first_name="Cascade", last_name="User", date_of_birth=date(1995, 1, 1), gender="female")
    integrity_db.add_all([u, p])
    integrity_db.commit()

    # 2. Add Ingestion Event and Vitals Readings
    ev = IngestionEvent(event_id="EV_CAS_1", patient_id="P_CAS_1", source="test", source_event_id="SRC_1", measured_at=now)
    integrity_db.add(ev)
    integrity_db.flush()

    rd1 = VitalsReading(event_id="EV_CAS_1", patient_id="P_CAS_1", metric_code="heart_rate", value=Decimal("80.0"), unit="bpm", raw_value=Decimal("80.0"), raw_unit="bpm", measured_at=now)
    rd2 = VitalsReading(event_id="EV_CAS_1", patient_id="P_CAS_1", metric_code="spo2", value=Decimal("99.0"), unit="%", raw_value=Decimal("99.0"), raw_unit="%", measured_at=now)
    alt = Alert(alert_id="ALT_CAS_1", patient_id="P_CAS_1", event_id="EV_CAS_1", rule_id="RULE_HR_HIGH", severity="HIGH", category="vital_threshold", reason="Test Alert", status="NEW", created_at=now)

    integrity_db.add_all([rd1, rd2, alt])
    integrity_db.commit()

    readings_count = integrity_db.scalar(select(func.count(VitalsReading.reading_id)).where(VitalsReading.patient_id == "P_CAS_1"))
    alerts_count = integrity_db.scalar(select(func.count(Alert.alert_id)).where(Alert.patient_id == "P_CAS_1"))
    assert readings_count == 2
    assert alerts_count == 1

    # 3. Delete Patient Profile
    integrity_db.delete(p)
    integrity_db.commit()

    # 4. Verify child records were cascade-deleted
    post_readings = integrity_db.scalar(select(func.count(VitalsReading.reading_id)).where(VitalsReading.patient_id == "P_CAS_1"))
    post_alerts = integrity_db.scalar(select(func.count(Alert.alert_id)).where(Alert.patient_id == "P_CAS_1"))
    assert post_readings == 0
    assert post_alerts == 0


# =============================================================================
# 2. Unique Constraints Enforcement
# =============================================================================

def test_unique_constraints_prevent_duplicates(integrity_db: Session):
    """Verify database-level unique constraints reject duplicate records."""
    now = datetime.now(timezone.utc)

    # 1. IngestionEvent duplicate (source, source_event_id)
    u = User(user_id="U_UQ_1", email="uq_test@example.com", password_hash="hash", role="patient", is_active=True)
    p = PatientProfile(patient_id="P_UQ_1", user_id="U_UQ_1", first_name="Unique", last_name="Test", date_of_birth=date(1992, 2, 2), gender="male")
    integrity_db.add_all([u, p])
    integrity_db.commit()

    ev1 = IngestionEvent(event_id="EV_UQ_1", patient_id="P_UQ_1", source="kaggle_csv", source_event_id="ROW_100", measured_at=now)
    integrity_db.add(ev1)
    integrity_db.commit()

    ev2 = IngestionEvent(event_id="EV_UQ_2", patient_id="P_UQ_1", source="kaggle_csv", source_event_id="ROW_100", measured_at=now)
    integrity_db.add(ev2)
    with pytest.raises(IntegrityError):
        integrity_db.commit()
    integrity_db.rollback()

    # 2. VitalsReading duplicate (event_id, metric_code)
    rd1 = VitalsReading(event_id="EV_UQ_1", patient_id="P_UQ_1", metric_code="heart_rate", value=Decimal("72.0"), unit="bpm", raw_value=Decimal("72.0"), raw_unit="bpm", measured_at=now)
    integrity_db.add(rd1)
    integrity_db.commit()

    rd2 = VitalsReading(event_id="EV_UQ_1", patient_id="P_UQ_1", metric_code="heart_rate", value=Decimal("75.0"), unit="bpm", raw_value=Decimal("75.0"), raw_unit="bpm", measured_at=now)
    integrity_db.add(rd2)
    with pytest.raises(IntegrityError):
        integrity_db.commit()
    integrity_db.rollback()

    # 3. Conversation duplicate (patient_id, doctor_id)
    u_doc = User(user_id="U_DOC_UQ", email="doc_uq@example.com", password_hash="hash", role="doctor", is_active=True)
    d = DoctorProfile(doctor_id="DOC_UQ_1", user_id="U_DOC_UQ", first_name="Doc", last_name="UQ", specialization="GP", license_number="LIC-UQ-1")
    integrity_db.add_all([u_doc, d])
    integrity_db.commit()

    conv1 = Conversation(conversation_id="CONV_UQ_1", patient_id="P_UQ_1", doctor_id="DOC_UQ_1", is_active=True)
    integrity_db.add(conv1)
    integrity_db.commit()

    conv2 = Conversation(conversation_id="CONV_UQ_2", patient_id="P_UQ_1", doctor_id="DOC_UQ_1", is_active=True)
    integrity_db.add(conv2)
    with pytest.raises(IntegrityError):
        integrity_db.commit()
    integrity_db.rollback()

    # 4. Message duplicate (sender_id, idempotency_key)
    msg1 = Message(
        message_id="MSG_UQ_1",
        conversation_id="CONV_UQ_1",
        sender_id="U_UQ_1",
        receiver_id="U_DOC_UQ",
        content="First message",
        idempotency_key="IDEMP_KEY_001",
    )
    integrity_db.add(msg1)
    integrity_db.commit()

    msg2 = Message(
        message_id="MSG_UQ_2",
        conversation_id="CONV_UQ_1",
        sender_id="U_UQ_1",
        receiver_id="U_DOC_UQ",
        content="Duplicate message",
        idempotency_key="IDEMP_KEY_001",
    )
    integrity_db.add(msg2)
    with pytest.raises(IntegrityError):
        integrity_db.commit()
    integrity_db.rollback()


# =============================================================================
# 3. Transaction Atomicity and Rollback
# =============================================================================

def test_transaction_atomicity_and_rollback_on_failure(integrity_db: Session):
    """Verify that multi-statement operations roll back completely when an error occurs."""
    now = datetime.now(timezone.utc)

    u = User(user_id="U_TX_1", email="tx_test@example.com", password_hash="hash", role="patient", is_active=True)
    p = PatientProfile(patient_id="P_TX_1", user_id="U_TX_1", first_name="Tx", last_name="Test", date_of_birth=date(1991, 3, 3), gender="female")
    integrity_db.add_all([u, p])
    integrity_db.commit()

    # Attempt a multi-entity transaction that raises an exception before completion
    with pytest.raises(DatabaseError):
        with transaction_scope(integrity_db) as tx_session:
            ev = IngestionEvent(event_id="EV_TX_FAIL", patient_id="P_TX_1", source="test", source_event_id="FAIL_1", measured_at=now)
            tx_session.add(ev)
            tx_session.flush()

            rd = VitalsReading(event_id="EV_TX_FAIL", patient_id="P_TX_1", metric_code="heart_rate", value=Decimal("88.0"), unit="bpm", raw_value=Decimal("88.0"), raw_unit="bpm", measured_at=now)
            tx_session.add(rd)
            tx_session.flush()

            # Simulate unexpected failure
            raise RuntimeError("Simulated mid-transaction failure")

    # Verify zero residual records persisted from the failed transaction
    remaining_events = integrity_db.scalar(select(func.count(IngestionEvent.event_id)).where(IngestionEvent.event_id == "EV_TX_FAIL"))
    remaining_readings = integrity_db.scalar(select(func.count(VitalsReading.reading_id)).where(VitalsReading.event_id == "EV_TX_FAIL"))
    assert remaining_events == 0
    assert remaining_readings == 0


# =============================================================================
# 4. Analytics Outbox Queueing, Retry Handling, and Recovery
# =============================================================================

def test_analytics_outbox_lifecycle_and_recovery(integrity_db: Session):
    """Verify outbox queueing, retry incrementing, failure transitions, and completion handling."""
    outbox_repo = OutboxRepository(integrity_db)

    # 1. Enqueue outbox items
    entry_1 = outbox_repo.stage_event(
        event_type="telemetry_event",
        aggregate_id="AGG_001",
        payload_json='{"patient_id": "P1", "heart_rate": 75.0}',
        max_attempts=3,
    )
    entry_2 = outbox_repo.stage_event(
        event_type="alert_event",
        aggregate_id="AGG_002",
        payload_json='{"patient_id": "P1", "severity": "HIGH"}',
        max_attempts=3,
    )
    integrity_db.commit()

    # Verify initial pending state
    stats = outbox_repo.get_outbox_stats()
    assert stats["pending"] == 2
    assert stats["processing"] == 0
    assert stats["completed"] == 0

    # 2. Mark Processing
    pending = outbox_repo.get_pending_batch(limit=10)
    assert len(pending) == 2
    outbox_repo.mark_processing(entry_1.outbox_id)
    integrity_db.commit()

    stats = outbox_repo.get_outbox_stats()
    assert stats["processing"] == 1

    # 3. Simulate failure with retry count increment
    outbox_repo.mark_failed(
        outbox_id=entry_1.outbox_id,
        error_message="Simulated connection timeout to MongoDB Atlas cluster",
    )
    integrity_db.commit()

    # Check attempt count was incremented and status reset to pending for retry
    refreshed_1 = integrity_db.get(AnalyticsOutbox, entry_1.outbox_id)
    assert refreshed_1.attempt_count == 1
    assert refreshed_1.status == "pending"
    assert "MongoDB Atlas" in refreshed_1.last_error

    # 4. Process and fail repeatedly to trigger max_attempts limit
    outbox_repo.mark_processing(entry_1.outbox_id)
    outbox_repo.mark_failed(entry_1.outbox_id, error_message="Retry 2 failure")
    outbox_repo.mark_processing(entry_1.outbox_id)
    outbox_repo.mark_failed(entry_1.outbox_id, error_message="Retry 3 failure")
    integrity_db.commit()

    refreshed_1 = integrity_db.get(AnalyticsOutbox, entry_1.outbox_id)
    assert refreshed_1.attempt_count == 3
    assert refreshed_1.status == "failed"

    # 5. Successfully process entry_2
    outbox_repo.mark_processing(entry_2.outbox_id)
    outbox_repo.mark_completed(entry_2.outbox_id)
    integrity_db.commit()

    refreshed_2 = integrity_db.get(AnalyticsOutbox, entry_2.outbox_id)
    assert refreshed_2.status == "completed"
    assert refreshed_2.completed_at is not None
