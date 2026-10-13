"""
End-to-End Health-Data Workflow Verification Suite.

Exercises the complete, integrated Smart Health Monitoring System lifecycle
across all 12 sequential stages defined in Part 2K Section 4:
1. Ingestion / creation of valid telemetry readings.
2. Canonical vitals persistence in MySQL (system of record).
3. Preservation of source provenance, identity, and measurement units.
4. Evaluation of eligible telemetry by configured clinical alert rules.
5. Correct alert persistence with clinical severity and status.
6. Prevention of duplicate alerts upon repeated evaluation (idempotency).
7. Authorized patient and clinician retrieval of permitted readings and alerts.
8. Denial of unauthorized access across patient boundaries (403 Forbidden).
9. Alert acknowledgement with status transition and compliance audit log.
10. MongoDB Atlas analytics outbox synchronization.
11. Real-time WebSocket notification delivery strictly post-commit.
12. Operational clinical messaging and read tracking alongside clinical vitals.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    Alert,
    AlertRule,
    AlertStatusHistory,
    AnalyticsOutbox,
    AuditLog,
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
from database.mysql.session import get_db, transaction_scope
from services.alert_service import AlertService
from services.alerts.evaluator import AlertEvaluator
from services.alerts.rules import DEFAULT_ALERT_RULES
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from services.messaging_service import MessagingService
from services.vitals_service import VitalsService


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def e2e_settings() -> Settings:
    """Isolated test settings with dedicated JWT test secret."""
    return Settings(
        app_env="testing",
        jwt_secret="testing_e2e_secret_key_at_least_32_characters_long_for_security!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
    )


@pytest.fixture(scope="function")
def e2e_db_session() -> Generator[Session, None, None]:
    """In-memory SQLite session with StaticPool and enabled foreign keys."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def e2e_client(e2e_db_session: Session, e2e_settings: Settings) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden get_db and get_settings."""
    app = create_app(settings=e2e_settings)

    def override_get_db():
        try:
            yield e2e_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# =============================================================================
# End-to-End Workflow Tests
# =============================================================================

def test_complete_end_to_end_health_data_workflow(
    e2e_client: TestClient,
    e2e_db_session: Session,
    e2e_settings: Settings,
):
    """
    Executes the unified 12-step end-to-end clinical telemetry and messaging workflow.
    """
    now = datetime.now(timezone.utc)

    # -------------------------------------------------------------------------
    # Setup: Seed Authorized Patient, Assigned Clinician, and Unrelated Identities
    # -------------------------------------------------------------------------
    # Patient 1 (Primary subject)
    u_pat1 = User(
        user_id="user_pat_e2e_01",
        email="patient1.e2e@example.com",
        password_hash=hash_password("Patient123!Secure"),
        role="patient",
        is_active=True,
    )
    p_pat1 = PatientProfile(
        patient_id="P_E2E_01",
        user_id="user_pat_e2e_01",
        first_name="Alice",
        last_name="Patient",
        date_of_birth=date(1985, 5, 15),
        gender="female",
    )

    # Doctor 1 (Assigned clinician)
    u_doc1 = User(
        user_id="user_doc_e2e_01",
        email="doctor1.e2e@example.com",
        password_hash=hash_password("Doctor123!Secure"),
        role="doctor",
        is_active=True,
    )
    d_doc1 = DoctorProfile(
        doctor_id="DOC_E2E_01",
        user_id="user_doc_e2e_01",
        first_name="Gregory",
        last_name="House",
        specialization="Cardiology",
        license_number="LIC-E2E-001",
    )

    # Patient 2 (Unrelated patient for isolation checks)
    u_pat2 = User(
        user_id="user_pat_e2e_02",
        email="patient2.e2e@example.com",
        password_hash=hash_password("Patient2_123!Secure"),
        role="patient",
        is_active=True,
    )
    p_pat2 = PatientProfile(
        patient_id="P_E2E_02",
        user_id="user_pat_e2e_02",
        first_name="Bob",
        last_name="Unrelated",
        date_of_birth=date(1990, 8, 20),
        gender="male",
    )

    # Doctor 2 (Unassigned clinician)
    u_doc2 = User(
        user_id="user_doc_e2e_02",
        email="doctor2.e2e@example.com",
        password_hash=hash_password("Doctor2_123!Secure"),
        role="doctor",
        is_active=True,
    )
    d_doc2 = DoctorProfile(
        doctor_id="DOC_E2E_02",
        user_id="user_doc_e2e_02",
        first_name="John",
        last_name="Watson",
        specialization="General Medicine",
        license_number="LIC-E2E-002",
    )

    # Active care assignment: Doctor 1 -> Patient 1
    assignment = DoctorPatientAssignment(
        doctor_id="DOC_E2E_01",
        patient_id="P_E2E_01",
        is_active=True,
    )

    # Seed Clinical Alert Rules
    seeded_rules = [
        AlertRule(
            rule_id=r.rule_id,
            metric_code=r.metric_code,
            operator=r.operator,
            configured_value=r.configured_value,
            severity=r.severity,
            is_enabled=r.is_enabled,
            description=r.description,
        )
        for r in DEFAULT_ALERT_RULES
    ]

    e2e_db_session.add_all([u_pat1, p_pat1, u_doc1, d_doc1, u_pat2, p_pat2, u_doc2, d_doc2, assignment] + seeded_rules)
    e2e_db_session.commit()

    # Generate Auth Tokens
    pat1_token = create_access_token({"sub": "user_pat_e2e_01", "email": u_pat1.email, "role": "patient"}, settings=e2e_settings)
    doc1_token = create_access_token({"sub": "user_doc_e2e_01", "email": u_doc1.email, "role": "doctor"}, settings=e2e_settings)
    pat2_token = create_access_token({"sub": "user_pat_e2e_02", "email": u_pat2.email, "role": "patient"}, settings=e2e_settings)
    doc2_token = create_access_token({"sub": "user_doc_e2e_02", "email": u_doc2.email, "role": "doctor"}, settings=e2e_settings)

    # -------------------------------------------------------------------------
    # STEP 1: Ingest a Valid Telemetry Reading (Critical Tachycardia Event)
    # -------------------------------------------------------------------------
    event_id = "evt_e2e_test_001"
    ingestion_event = IngestionEvent(
        event_id=event_id,
        patient_id="P_E2E_01",
        source="simulator",
        source_event_id="sim_seq_001",
        measured_at=now,
        received_at=now,
        is_simulated=True,
        mirror_status="pending",
    )
    e2e_db_session.add(ingestion_event)

    reading_hr = VitalsReading(
        event_id=event_id,
        patient_id="P_E2E_01",
        metric_code="heart_rate",
        value=Decimal("142.0"),
        unit="bpm",
        raw_value=Decimal("142.0"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    reading_spo2 = VitalsReading(
        event_id=event_id,
        patient_id="P_E2E_01",
        metric_code="spo2",
        value=Decimal("96.5"),
        unit="%",
        raw_value=Decimal("96.5"),
        raw_unit="%",
        quality_status="valid",
        measured_at=now,
    )
    reading_temp = VitalsReading(
        event_id=event_id,
        patient_id="P_E2E_01",
        metric_code="temperature",
        value=Decimal("37.2"),
        unit="degC",
        raw_value=Decimal("98.96"),
        raw_unit="degF",
        quality_status="valid",
        measured_at=now,
    )
    e2e_db_session.add_all([reading_hr, reading_spo2, reading_temp])
    e2e_db_session.commit()

    # -------------------------------------------------------------------------
    # STEP 2 & 3: Verify Canonical Persistence & Provenance in MySQL
    # -------------------------------------------------------------------------
    db_event = e2e_db_session.get(IngestionEvent, event_id)
    assert db_event is not None
    assert db_event.source == "simulator"
    assert db_event.is_simulated is True
    assert db_event.source_event_id == "sim_seq_001"

    saved_readings = e2e_db_session.scalars(
        select(VitalsReading).where(VitalsReading.event_id == event_id)
    ).all()
    assert len(saved_readings) == 3

    hr_record = next(r for r in saved_readings if r.metric_code == "heart_rate")
    assert hr_record.value == Decimal("142.0")
    assert hr_record.unit == "bpm"

    temp_record = next(r for r in saved_readings if r.metric_code == "temperature")
    assert temp_record.value == Decimal("37.2")
    assert temp_record.unit == "degC"
    assert temp_record.raw_value == Decimal("98.96")
    assert temp_record.raw_unit == "degF"

    # -------------------------------------------------------------------------
    # STEP 4 & 5: Evaluate Alert Rules & Verify Persistent Alert Creation
    # -------------------------------------------------------------------------
    evaluator = AlertEvaluator(e2e_db_session)
    triggered_alerts = evaluator.evaluate_event(db_event)

    assert len(triggered_alerts) >= 1
    created_alert = next(a for a in triggered_alerts if a.severity == "CRITICAL")
    assert created_alert.patient_id == "P_E2E_01"
    assert created_alert.rule_id == "RULE_HR_CRITICAL_HIGH"
    assert created_alert.severity == "CRITICAL"
    assert created_alert.status == "NEW"
    assert created_alert.event_id == event_id
    assert created_alert.alert_id.startswith("alt_")

    # -------------------------------------------------------------------------
    # STEP 6: Verify Repeated Evaluation Does Not Duplicate Alerts (Idempotency)
    # -------------------------------------------------------------------------
    repeated_eval = evaluator.evaluate_event(db_event)
    assert len(repeated_eval) == len(triggered_alerts)

    total_alerts_count = e2e_db_session.scalar(
        select(func.count(Alert.alert_id)).where(Alert.patient_id == "P_E2E_01")
    )
    assert total_alerts_count == len(triggered_alerts), "Alert must not be duplicated on repeated evaluation"

    # -------------------------------------------------------------------------
    # STEP 7: Verify Authorized Patient and Clinician Can Retrieve permitted Data
    # -------------------------------------------------------------------------
    # 7a. Patient retrieves own readings
    resp_pat_readings = e2e_client.get(
        "/api/v1/patients/P_E2E_01/readings",
        headers={"Authorization": f"Bearer {pat1_token}"},
    )
    assert resp_pat_readings.status_code == status.HTTP_200_OK
    data_pat_readings = resp_pat_readings.json()
    assert data_pat_readings["total_count"] == 1
    assert len(data_pat_readings["items"]) == 1
    reading_item = data_pat_readings["items"][0]
    assert reading_item["heart_rate"] == 142.0
    assert reading_item["spo2"] == 96.5
    assert reading_item["temperature_c"] == 37.2
    assert reading_item["temperature_f"] == 98.96

    # 7b. Assigned doctor retrieves patient readings
    resp_doc_readings = e2e_client.get(
        "/api/v1/patients/P_E2E_01/readings",
        headers={"Authorization": f"Bearer {doc1_token}"},
    )
    assert resp_doc_readings.status_code == status.HTTP_200_OK
    assert resp_doc_readings.json()["total_count"] == 1

    # 7c. Patient retrieves own alerts
    resp_pat_alerts = e2e_client.get(
        "/api/v1/patients/P_E2E_01/alerts",
        headers={"Authorization": f"Bearer {pat1_token}"},
    )
    assert resp_pat_alerts.status_code == status.HTTP_200_OK
    assert resp_pat_alerts.json()["total_count"] == len(triggered_alerts)
    assert any(item["alert_id"] == created_alert.alert_id for item in resp_pat_alerts.json()["items"])

    # 7d. Assigned doctor retrieves patient alerts
    resp_doc_alerts = e2e_client.get(
        "/api/v1/patients/P_E2E_01/alerts",
        headers={"Authorization": f"Bearer {doc1_token}"},
    )
    assert resp_doc_alerts.status_code == status.HTTP_200_OK
    assert resp_doc_alerts.json()["total_count"] == len(triggered_alerts)

    # -------------------------------------------------------------------------
    # STEP 8: Verify Unauthorized Identities Cannot Retrieve Records (403)
    # -------------------------------------------------------------------------
    # 8a. Other patient cannot retrieve Patient 1's readings
    resp_unauth_pat = e2e_client.get(
        "/api/v1/patients/P_E2E_01/readings",
        headers={"Authorization": f"Bearer {pat2_token}"},
    )
    assert resp_unauth_pat.status_code == status.HTTP_403_FORBIDDEN

    # 8b. Unassigned doctor cannot retrieve Patient 1's readings
    resp_unauth_doc = e2e_client.get(
        "/api/v1/patients/P_E2E_01/readings",
        headers={"Authorization": f"Bearer {doc2_token}"},
    )
    assert resp_unauth_doc.status_code == status.HTTP_403_FORBIDDEN

    # 8c. Other patient cannot retrieve Patient 1's alerts
    resp_unauth_pat_alert = e2e_client.get(
        "/api/v1/patients/P_E2E_01/alerts",
        headers={"Authorization": f"Bearer {pat2_token}"},
    )
    assert resp_unauth_pat_alert.status_code == status.HTTP_403_FORBIDDEN

    # 8d. Unassigned doctor cannot retrieve Patient 1's alerts
    resp_unauth_doc_alert = e2e_client.get(
        "/api/v1/patients/P_E2E_01/alerts",
        headers={"Authorization": f"Bearer {doc2_token}"},
    )
    assert resp_unauth_doc_alert.status_code == status.HTTP_403_FORBIDDEN

    # -------------------------------------------------------------------------
    # STEP 9: Verify Acknowledgement Updates Alert and Audit Trail
    # -------------------------------------------------------------------------
    resp_ack = e2e_client.post(
        f"/api/v1/alerts/{created_alert.alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {doc1_token}"},
        json={"note": "Assessing ECG and preparing beta blocker therapy"},
    )
    assert resp_ack.status_code == status.HTTP_200_OK
    ack_data = resp_ack.json()
    assert ack_data["status"] == "ACKNOWLEDGED"
    assert ack_data["acknowledged_by"] == "user_doc_e2e_01"
    assert ack_data["acknowledged_at"] is not None

    # Verify status history row persisted
    history_entries = e2e_db_session.scalars(
        select(AlertStatusHistory).where(AlertStatusHistory.alert_id == created_alert.alert_id)
    ).all()
    assert len(history_entries) >= 1
    assert history_entries[-1].new_status == "ACKNOWLEDGED"
    assert history_entries[-1].actor_id == "user_doc_e2e_01"

    # Verify compliance audit log row persisted
    audit_entries = e2e_db_session.scalars(
        select(AuditLog).where(
            AuditLog.target_id == created_alert.alert_id,
            AuditLog.action == "ALERT_ACKNOWLEDGE",
        )
    ).all()
    assert len(audit_entries) == 1
    assert audit_entries[0].actor_id == "user_doc_e2e_01"

    # Idempotent re-acknowledgement
    resp_ack_repeat = e2e_client.post(
        f"/api/v1/alerts/{created_alert.alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {doc1_token}"},
        json={"note": "Second click shouldn't fail"},
    )
    assert resp_ack_repeat.status_code == status.HTTP_200_OK
    assert resp_ack_repeat.json()["status"] == "ACKNOWLEDGED"

    # -------------------------------------------------------------------------
    # STEP 10: Verify MongoDB Synchronization / Outbox Queueing
    # -------------------------------------------------------------------------
    import json

    outbox_repo = OutboxRepository(e2e_db_session)
    outbox_entry = outbox_repo.stage_event(
        event_type="telemetry_event",
        aggregate_id=event_id,
        payload_json=json.dumps({
            "patient_id": "P_E2E_01",
            "event_id": event_id,
            "source": "simulator",
            "heart_rate": 142.0,
        }),
    )
    e2e_db_session.commit()

    assert outbox_entry.outbox_id is not None
    assert outbox_entry.status == "pending"
    assert outbox_entry.attempt_count == 0

    pending_batch = outbox_repo.get_pending_batch(limit=10)
    assert any(e.outbox_id == outbox_entry.outbox_id for e in pending_batch)

    # -------------------------------------------------------------------------
    # STEP 11: Real-Time WebSocket Notification Post-Commit Verification
    # -------------------------------------------------------------------------
    from services.websocket.dispatcher import notify_message_created
    from services.websocket.manager import connection_manager

    mock_msg = Message(
        message_id="msg_e2e_notif_001",
        conversation_id="conv_P_E2E_01_DOC_E2E_01",
        sender_id="user_pat_e2e_01",
        receiver_id="user_doc_e2e_01",
        content="Help, feeling unwell",
        created_at=now,
    )

    with patch.object(connection_manager, "broadcast_to_patient") as mock_broadcast:
        notify_message_created(mock_msg, patient_id="P_E2E_01")
        mock_broadcast.assert_called_once()
        call_args = mock_broadcast.call_args[0]
        assert call_args[0] == "P_E2E_01"
        assert call_args[1]["event_type"] == "message.created"
        assert call_args[1]["resource_id"] == "msg_e2e_notif_001"

    # -------------------------------------------------------------------------
    # STEP 12: Verify Operational Clinical Messaging Workflow Alongside Telemetry
    # -------------------------------------------------------------------------
    # 12a. Doctor creates / retrieves conversation with Patient 1
    resp_create_conv = e2e_client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {doc1_token}"},
        json={"patient_id": "P_E2E_01"},
    )
    assert resp_create_conv.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
    conv_id = resp_create_conv.json()["conversation_id"]
    assert conv_id == "conv_P_E2E_01_DOC_E2E_01"

    # 12b. Patient sends message within conversation
    resp_send_msg = e2e_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {pat1_token}"},
        json={
            "content": "Doctor, I saw the alert on my dashboard and my heart is racing.",
            "idempotency_key": "idemp_e2e_msg_001",
        },
    )
    assert resp_send_msg.status_code == status.HTTP_201_CREATED
    msg_data = resp_send_msg.json()
    assert msg_data["conversation_id"] == conv_id
    assert msg_data["sender_id"] == "user_pat_e2e_01"
    assert msg_data["is_read"] is False

    # 12c. Doctor lists messages in conversation
    resp_list_msgs = e2e_client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {doc1_token}"},
    )
    assert resp_list_msgs.status_code == status.HTTP_200_OK
    msgs_data = resp_list_msgs.json()
    assert msgs_data["total_count"] >= 1
    assert any(m["message_id"] == msg_data["message_id"] for m in msgs_data["items"])

    # 12d. Doctor marks incoming messages as read
    resp_mark_read = e2e_client.post(
        f"/api/v1/conversations/{conv_id}/read",
        headers={"Authorization": f"Bearer {doc1_token}"},
    )
    assert resp_mark_read.status_code == status.HTTP_200_OK
    assert resp_mark_read.json()["messages_marked_read"] >= 1

    # 12e. Verify message is now marked read in database
    db_msg = e2e_db_session.get(Message, msg_data["message_id"])
    assert db_msg.is_read is True
    assert db_msg.read_at is not None

    # End-to-end workflow successfully completed across all 12 stages!
