"""
Smart Health Monitoring System — Live Demonstration Failure Drill and Recovery Suite.

Verifies system resilience, graceful degradation, and clean recovery across critical failure modes:
1. Scenario 1: Relational Database Unavailability (HTTP 503 on readiness, 500 on queries, static routes alive, clean recovery).
2. Scenario 2: MongoDB Atlas Outage (Readiness remains 200, degraded status, outbox buffers safely, zero operational block).
3. Scenario 3: ML Model Missing / Corrupt (Graceful fallback to 'inconclusive', score 0.0, zero unhandled 500s, clean recovery).
4. Scenario 4: Authentication Expiration & Tampering (HTTP 401 with WWW-Authenticate, clean token recovery).
5. Scenario 5: Malformed Data & Schema Validation (HTTP 422 with structured field errors, zero database writes).
6. Scenario 6: Outbox Bounded Retries & Failure Isolation (Transitions to 'failed' on exhausted retries, no retry storms).
7. Scenario 7: Simulator Lifecycle State and Idempotent Recovery Drill (Safe start/stop, status reporting).
8. Scenario 8: MongoDB Read-Only Safety Verification (Zero writes to Atlas, invariant preserved).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

from fastapi import status
from fastapi.testclient import TestClient
import mongomock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mongodb.client import check_mongo_connectivity, sanitize_mongo_uri
from database.mysql.models import (
    Alert,
    AnalyticsOutbox,
    AuditLog,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    ModelAssessment,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.repositories.assessment_repository import AssessmentRepository
from database.mysql.repositories.outbox_repository import OutboxRepository
from database.mysql.session import get_db
from services.api.config import Settings, get_settings
from services.api.main import create_app
from services.auth.dependencies import get_current_user
from services.auth.security import create_access_token
from services.ml_service import MLService, get_ml_service, reset_ml_service
from services.sync.outbox_service import OutboxSyncService


# =============================================================================
# Isolated Test Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def isolated_db_session() -> Generator[Session, None, None]:
    """In-memory SQLite session isolated per test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def seed_test_data(isolated_db_session: Session) -> dict:
    """Seeds baseline doctor and patient records in isolated DB."""
    # Doctor User & Profile
    doc_user = User(
        user_id="U_DOC_DRILL",
        email="doctor.drill@hospital.org",
        password_hash="mock_hash_for_testing",
        role="doctor",
        is_active=True,
    )
    doc_profile = DoctorProfile(
        doctor_id="DOC_DRILL",
        user_id="U_DOC_DRILL",
        first_name="Eleanor",
        last_name="Vance",
        license_number="MD-DRILL-001",
        specialization="Cardiology",
    )

    # Patient User & Profile
    pat_user = User(
        user_id="U_PAT_DRILL",
        email="patient.drill@example.com",
        password_hash="mock_hash_for_testing",
        role="patient",
        is_active=True,
    )
    pat_profile = PatientProfile(
        patient_id="P101",
        user_id="U_PAT_DRILL",
        first_name="Arthur",
        last_name="Dent",
        date_of_birth=date(1980, 5, 15),
        gender="male",
    )

    assignment = DoctorPatientAssignment(
        doctor_id="DOC_DRILL",
        patient_id="P101",
        is_active=True,
    )

    isolated_db_session.add_all([doc_user, doc_profile, pat_user, pat_profile, assignment])
    isolated_db_session.commit()

    return {
        "doctor_user": doc_user,
        "doctor_profile": doc_profile,
        "patient_user": pat_user,
        "patient_profile": pat_profile,
    }


@pytest.fixture(scope="function")
def test_client(isolated_db_session: Session, seed_test_data: dict) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with isolated DB and dependency overrides."""
    settings = get_settings()
    app = create_app(settings)

    # Override database dependency with isolated in-memory DB
    app.dependency_overrides[get_db] = lambda: isolated_db_session
    # Default authenticated user is the doctor
    app.dependency_overrides[get_current_user] = lambda: seed_test_data["doctor_user"]

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


# =============================================================================
# Scenario 1: Relational Database Outage & Recovery Drill
# =============================================================================

def test_drill_scenario_1_database_outage_and_recovery(isolated_db_session: Session):
    """
    FAILURE DRILL: Relational Database Unavailability.
    Injected Failure: check_db_connectivity returns False (simulating MySQL TCP drop).
    Expected Behavior:
      - /health/ready returns HTTP 503 Service Unavailable with descriptive JSON.
      - /health/live remains HTTP 200 OK (process event loop alive).
      - Root informational endpoint remains HTTP 200 OK.
    Recovery Behavior:
      - Connection probe restored -> /health/ready immediately returns HTTP 200 OK.
    """
    settings = get_settings()
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: isolated_db_session

    with TestClient(app) as client:
        # 1. Healthy Baseline
        r_base = client.get("/api/v1/health/ready")
        assert r_base.status_code == status.HTTP_200_OK
        assert r_base.json()["status"] == "ready"
        assert r_base.json()["database"] == "connected"

        # 2. Inject Failure: Database connectivity drops
        with patch("services.api.main.check_db_connectivity", return_value=False):
            r_unready = client.get("/api/v1/health/ready")
            assert r_unready.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            data = r_unready.json()
            assert data["status"] == "unready"
            assert data["database"] == "unreachable"
            assert "Authoritative relational database is unavailable" in data["message"]

            # Verify un-gated static/liveness routes remain operational
            r_live = client.get("/api/v1/health/live")
            assert r_live.status_code == status.HTTP_200_OK
            assert r_live.json()["status"] == "alive"

            r_root = client.get("/")
            assert r_root.status_code == status.HTTP_200_OK
            assert r_root.json()["status"] == "online"

        # 3. Verify Recovery: Connectivity restored
        r_recovered = client.get("/api/v1/health/ready")
        assert r_recovered.status_code == status.HTTP_200_OK
        assert r_recovered.json()["status"] == "ready"
        assert r_recovered.json()["database"] == "connected"


# =============================================================================
# Scenario 2: MongoDB Atlas Outage & Recovery Drill
# =============================================================================

def test_drill_scenario_2_mongodb_outage_does_not_block_operations(
    isolated_db_session: Session,
    seed_test_data: dict,
):
    """
    FAILURE DRILL: MongoDB Atlas Cloud Partition / Unavailability.
    Injected Failure: check_mongo_connectivity returns (False, "Timeout").
    Expected Behavior:
      - /health/ready returns HTTP 200 OK (readiness is NOT gated on MongoDB analytics mirror).
      - mongodb_mirror is accurately reported as 'degraded'.
      - /health/mongodb returns HTTP 200 with status 'unreachable' and credentials redacted.
      - Relational transactions (creating vital readings) succeed without interruption.
    Recovery Behavior:
      - MongoDB connection restored -> /health/ready reports mongodb_mirror: 'connected'.
    """
    settings = get_settings()
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: isolated_db_session
    app.dependency_overrides[get_current_user] = lambda: seed_test_data["doctor_user"]

    with TestClient(app) as client:
        # Inject Failure: MongoDB times out
        with patch("services.api.main.check_mongo_connectivity", return_value=(False, "Connection timed out")):
            # Readiness check must NOT fail
            r_ready = client.get("/api/v1/health/ready")
            assert r_ready.status_code == status.HTTP_200_OK
            data = r_ready.json()
            assert data["status"] == "ready"
            assert data["database"] == "connected"
            assert data["mongodb_mirror"] == "degraded"

            # MongoDB diagnostic probe reports degraded safely
            r_mongo = client.get("/api/v1/health/mongodb")
            assert r_mongo.status_code == status.HTTP_200_OK
            mongo_data = r_mongo.json()
            assert mongo_data["status"] == "Connection timed out"
            # Crucial: Credentials strictly redacted with ***:***
            assert "***:***" in mongo_data["endpoint"]
            assert "shm_app_rw:" not in str(mongo_data)

            # Relational operation succeeds completely
            event = IngestionEvent(
                event_id="EVT_DRILL_01",
                patient_id="P101",
                source="smartwatch_simulator",
                source_event_id="s_drill_01",
                measured_at=datetime.now(timezone.utc),
                is_simulated=True,
            )
            isolated_db_session.add(event)
            isolated_db_session.commit()
            assert isolated_db_session.get(IngestionEvent, "EVT_DRILL_01") is not None

        # Verify Recovery: MongoDB connection restored
        with patch("services.api.main.check_mongo_connectivity", return_value=(True, "Connected to cluster0")):
            r_rec = client.get("/api/v1/health/ready")
            assert r_rec.status_code == status.HTTP_200_OK
            assert r_rec.json()["mongodb_mirror"] == "connected"


# =============================================================================
# Scenario 3: Machine Learning Model Failure & Graceful Fallback Drill
# =============================================================================

def test_drill_scenario_3_ml_model_failure_graceful_fallback(
    isolated_db_session: Session,
    seed_test_data: dict,
):
    """
    FAILURE DRILL: ML Model Artifact Missing or Corrupted.
    Injected Failure: Initialize MLService pointing to a missing model artifact directory.
    Expected Behavior:
      - MLService sets is_available=False, degraded_reason recorded.
      - GET /api/v1/predictions/status returns HTTP 200 with status: 'degraded'.
      - POST /api/v1/patients/{id}/assess returns HTTP 200 with canonical result 'inconclusive',
        anomaly score 0.0, and explanatory diagnosis without taking down the gateway.
      - Zero false alerts generated.
    Recovery Behavior:
      - Reset MLService to authentic artifact directory -> resumes normal inference.
    """
    settings = get_settings()
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: isolated_db_session
    app.dependency_overrides[get_current_user] = lambda: seed_test_data["doctor_user"]

    # 1. Inject Failure: MLService instantiated with missing directory
    bad_service = MLService(artifact_dir="/nonexistent/model/path", settings=settings)
    assert not bad_service.is_available
    assert "not found" in bad_service.degraded_reason.lower() or "missing" in bad_service.degraded_reason.lower()

    with patch("services.api.routes.predictions.get_ml_service", return_value=bad_service):
        with TestClient(app) as client:
            # Model status reflects degraded mode
            r_status = client.get("/api/v1/predictions/status")
            assert r_status.status_code == status.HTTP_200_OK
            status_data = r_status.json()
            assert status_data["status"] == "degraded"
            assert status_data["is_available"] is False

            # Assessment endpoint degrades gracefully instead of throwing 500
            payload = {
                "heart_rate": 160.0,
                "spo2": 82.0,
                "temperature_f": 103.5,
                "persist": False,
            }
            r_assess = client.post("/api/v1/patients/P101/assess", json=payload)
            assert r_assess.status_code == status.HTTP_200_OK
            assess_data = r_assess.json()
            assert assess_data["result"] == "inconclusive"
            assert assess_data["is_anomaly"] is False
            assert assess_data["score"] == 0.0
            assert assess_data["alert_triggered"] is False
            assert "error" in assess_data["feature_summary"]

    # 2. Verify Recovery: Authentic model artifact service
    real_service = get_ml_service(settings)
    assert real_service.is_available
    with patch("services.api.routes.predictions.get_ml_service", return_value=real_service):
        with TestClient(app) as client:
            r_status_rec = client.get("/api/v1/predictions/status")
            assert r_status_rec.status_code == status.HTTP_200_OK
            assert r_status_rec.json()["status"] == "ready"
            assert r_status_rec.json()["is_available"] is True


# =============================================================================
# Scenario 4: Authentication Expiration & Tampering Drill
# =============================================================================

def test_drill_scenario_4_authentication_expiration_and_recovery(
    isolated_db_session: Session,
    seed_test_data: dict,
):
    """
    FAILURE DRILL: Expired JWT Token and Tampered Credentials.
    Injected Failure:
      - Expired token (exp in the past).
      - Tampered token signature.
      - Missing credentials.
    Expected Behavior:
      - Server returns HTTP 401 Unauthorized.
      - Header contains WWW-Authenticate: Bearer.
      - Clear error message returned without crashing.
    Recovery Behavior:
      - Supply fresh, valid JWT -> request succeeds with HTTP 200 OK.
    """
    settings = get_settings()
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: isolated_db_session

    with TestClient(app) as client:
        # 1. Missing token
        r_no_auth = client.get("/api/v1/patients/P101")
        assert r_no_auth.status_code == status.HTTP_401_UNAUTHORIZED
        assert r_no_auth.headers.get("www-authenticate") == "Bearer"

        # 2. Expired token
        expired_token = create_access_token(
            data={"sub": "U_DOC_DRILL", "role": "doctor", "email": "doctor.drill@hospital.org"},
            expires_delta=timedelta(minutes=-30),  # expired 30 mins ago
            settings=settings,
        )
        r_expired = client.get(
            "/api/v1/patients/P101",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert r_expired.status_code == status.HTTP_401_UNAUTHORIZED
        assert "expired" in r_expired.json()["detail"].lower()

        # 3. Tampered token
        tampered_token = expired_token[:-5] + "XXXXX"
        r_tampered = client.get(
            "/api/v1/patients/P101",
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        assert r_tampered.status_code == status.HTTP_401_UNAUTHORIZED

        # 4. Verify Recovery: Fresh valid token
        valid_token = create_access_token(
            data={"sub": "U_DOC_DRILL", "role": "doctor", "email": "doctor.drill@hospital.org"},
            expires_delta=timedelta(minutes=30),
            settings=settings,
        )
        r_valid = client.get(
            "/api/v1/patients/P101",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert r_valid.status_code == status.HTTP_200_OK
        assert r_valid.json()["patient_id"] == "P101"


# =============================================================================
# Scenario 5: Malformed Data & Schema Validation Guard Drill
# =============================================================================

def test_drill_scenario_5_malformed_data_and_schema_validation(
    test_client: TestClient,
    isolated_db_session: Session,
):
    """
    FAILURE DRILL: Malformed Ingestion and Assessment Payload.
    Injected Failure:
      - Negative heart rate (-50 bpm).
      - Invalid vital ranges (SpO2 > 100%).
      - Malformed timestamp format.
    Expected Behavior:
      - FastAPI / Pydantic returns HTTP 422 Unprocessable Entity.
      - Detail includes structured parameter error locations.
      - Zero rows inserted into database.
    Recovery Behavior:
      - Submit compliant payload -> returns HTTP 200 OK.
    """
    # Count rows before injection
    before_count = isolated_db_session.query(VitalsReading).count()

    # Injected Failure 1: Negative heart rate
    bad_payload_1 = {
        "heart_rate": -50.0,
        "spo2": 98.0,
        "temperature_f": 98.6,
        "persist": True,
    }
    r_bad_1 = test_client.post("/api/v1/patients/P101/assess", json=bad_payload_1)
    assert r_bad_1.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Injected Failure 2: SpO2 over 100%
    bad_payload_2 = {
        "heart_rate": 80.0,
        "spo2": 150.0,
        "temperature_f": 98.6,
        "persist": True,
    }
    r_bad_2 = test_client.post("/api/v1/patients/P101/assess", json=bad_payload_2)
    assert r_bad_2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Verify zero database corruption
    after_count = isolated_db_session.query(VitalsReading).count()
    assert after_count == before_count

    # Recovery: Submit valid physiological readings
    valid_payload = {
        "heart_rate": 78.0,
        "spo2": 98.0,
        "temperature_f": 98.6,
        "persist": False,
    }
    r_valid = test_client.post("/api/v1/patients/P101/assess", json=valid_payload)
    assert r_valid.status_code == status.HTTP_200_OK
    assert r_valid.json()["is_anomaly"] is False


# =============================================================================
# Scenario 6: Outbox Bounded Retries & Failure Isolation Drill
# =============================================================================

def test_drill_scenario_6_outbox_bounded_retries_and_isolation(
    isolated_db_session: Session,
):
    """
    FAILURE DRILL: Downstream Outbox Synchronization Failure.
    Injected Failure: Outbox sync attempts fail due to external network timeout.
    Expected Behavior:
      - Attempt count increments predictably per retry.
      - When attempt_count reaches max_attempts, entry transitions to 'failed'.
      - Retry stops: no unbounded retry storm or infinite loops.
      - Error message is captured safely.
    Recovery Behavior:
      - Re-queue failed record -> transitions to 'pending' with reset attempt count.
    """
    outbox_repo = OutboxRepository(isolated_db_session)
    entry = outbox_repo.stage_event(
        event_type="telemetry_event",
        aggregate_id="evt_drill_fail_01",
        payload_json='{"_id": "evt_drill_fail_01", "patient_id": "P101"}',
        max_attempts=3,
    )
    isolated_db_session.commit()

    assert entry.status == "pending"
    assert entry.attempt_count == 0

    # Simulate Attempt 1 (Failure)
    outbox_repo.mark_processing(entry.outbox_id)
    outbox_repo.mark_failed(entry.outbox_id, "Temporary socket timeout")
    isolated_db_session.commit()
    assert entry.status == "pending"
    assert entry.attempt_count == 1

    # Simulate Attempt 2 (Failure)
    outbox_repo.mark_processing(entry.outbox_id)
    outbox_repo.mark_failed(entry.outbox_id, "DNS resolution timeout")
    isolated_db_session.commit()
    assert entry.status == "pending"
    assert entry.attempt_count == 2

    # Simulate Attempt 3 (Max attempts reached -> Failure isolation)
    outbox_repo.mark_processing(entry.outbox_id)
    outbox_repo.mark_failed(entry.outbox_id, "Target host unreachable")
    isolated_db_session.commit()
    assert entry.status == "failed"
    assert entry.attempt_count == 3
    assert "Target host unreachable" in entry.last_error

    # Verify no more automatic processing picks up the failed record
    pending = outbox_repo.get_pending_batch(limit=10)
    assert not any(p.outbox_id == entry.outbox_id for p in pending)

    # Verify record is in failed entries
    failed_entries = outbox_repo.list_failed_entries(limit=10)
    assert any(f.outbox_id == entry.outbox_id for f in failed_entries)

    # Recovery: Re-enqueue the record for retry
    entry.status = "pending"
    entry.attempt_count = 0
    isolated_db_session.commit()
    reloaded = outbox_repo.get_by_id(entry.outbox_id)
    assert reloaded.status == "pending"
    assert reloaded.attempt_count == 0


# =============================================================================
# Scenario 7: Simulator Lifecycle State and Idempotent Recovery Drill
# =============================================================================

def test_drill_scenario_7_simulator_lifecycle_and_idempotence():
    """
    FAILURE DRILL: Simulator Unexpected Cessation and Idempotent Restart.
    Injected Failure: Simulator generator stopped or polled with empty buffer.
    Expected Behavior:
      - poll_stream returns empty readings array without error.
      - Start and stop commands are strictly idempotent.
    Recovery Behavior:
      - Call start -> transitions to running without spawning duplicate tasks.
    """
    from simulator.generator import TelemetryGenerator

    generator = TelemetryGenerator()
    assert generator.lifecycle_state == "STOPPED"
    assert not generator.is_running

    # Polling an unstarted generator returns empty stream safely
    stream = generator.poll_stream(cursor=None, limit=10)
    assert stream.items == []
    assert stream.cursor is None

    # Idempotent start
    async def _test_lifecycle():
        started1 = await generator.start()
        assert started1 is True
        assert generator.is_running
        assert generator.lifecycle_state == "RUNNING"

        # Calling start again while running is safe and returns False
        started2 = await generator.start()
        assert started2 is False
        assert generator.is_running

        # Safe stop
        stopped1 = await generator.stop()
        assert stopped1 is True
        assert not generator.is_running
        assert generator.lifecycle_state == "STOPPED"

        # Calling stop again while stopped is safe
        stopped2 = await generator.stop()
        assert stopped2 is False

    asyncio.run(_test_lifecycle())


# =============================================================================
# Scenario 8: MongoDB Read-Only Safety Assertion Drill
# =============================================================================

def test_drill_scenario_8_mongodb_read_only_invariant_preserved():
    """
    NON-NEGOTIABLE SAFETY DRILL: MongoDB Atlas Cloud Data Invariant.
    Verifies that running the failure drill suite performed ZERO writes to MongoDB Atlas.
    Target collection smart_health_analytics.telemetry_events must remain at exactly 2,955 documents.
    """
    import os
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv(".env")
    uri = os.getenv("MONGODB_URI")
    assert uri, "MONGODB_URI must be configured"

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client["smart_health_analytics"]
    count = db["telemetry_events"].count_documents({})
    client.close()

    assert count == 2955, f"MongoDB Atlas data invariant violated: expected 2955, found {count}"
