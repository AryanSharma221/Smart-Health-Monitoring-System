"""
Unit and Integration Tests for MongoDB Atlas Analytics Mirror, Outbox, and Recovery.

Verifies:
1. Centralized MongoDB client configuration, URI credential redaction, and offline resilience.
2. Analytics document serialization, unit preservation, and privacy (zero credentials/tokens).
3. Monotonic alert state protection against out-of-order event delivery.
4. Idempotent upserts on stable identities (_id = event_id / alert_id) preventing duplicates.
5. Distinction between distinct events sharing identical measurement values.
6. Transactional outbox staging, retry bounds, failure recovery, and diagnostic reporting.
7. Safe degraded operation: MySQL operations always succeed even when MongoDB fails.
8. Diagnostic health probe (/health/mongodb) reporting outbox statistics without leaking credentials.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Generator
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mongodb.client import (
    check_mongo_connectivity,
    close_mongo_client,
    ensure_indexes,
    get_mongo_client,
    get_mongo_database,
    sanitize_mongo_uri,
)
from database.mongodb.collections import (
    ALERT_INDEXES,
    ALERTS_COLLECTION,
    TELEMETRY_COLLECTION,
    TELEMETRY_INDEXES,
)
from database.mongodb.repositories.alert_mirror_repository import AlertMirrorRepository
from database.mongodb.repositories.telemetry_mirror_repository import (
    TelemetryMirrorRepository,
)
from database.mysql.models import (
    Alert,
    AnalyticsOutbox,
    Base,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.repositories.outbox_repository import OutboxRepository
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import hash_password
from services.sync.outbox_service import OutboxSyncService
from services.sync.serialization import (
    build_alert_document,
    build_telemetry_document,
    document_to_json,
    json_to_document,
)


# =============================================================================
# Test Database Fixtures (In-Memory SQLite with StaticPool & In-Memory MongoMock)
# =============================================================================

@pytest.fixture(scope="function")
def test_settings() -> Settings:
    """Isolated test settings with mock MongoDB Atlas configuration."""
    return Settings(
        app_env="testing",
        jwt_secret="mongodb_mirror_test_secret_at_least_32_characters!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        mongodb_uri="mongodb+srv://test_user:SuperSecretPassword123@cluster0.test.mongodb.net/?retryWrites=true&w=majority",
        mongodb_database="test_health_analytics",
        mongodb_server_selection_timeout_ms=1000,
        mongodb_connect_timeout_ms=1000,
    )


@pytest.fixture(scope="function")
def test_db_session() -> Generator[Session, None, None]:
    """In-memory SQLite session with StaticPool."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def mock_mongo_db() -> Generator[mongomock.Database, None, None]:
    """Isolated in-memory mongomock Database."""
    client = mongomock.MongoClient()
    db = client["test_health_analytics"]
    yield db
    client.close()


@pytest.fixture(scope="function")
def client(test_db_session: Session, test_settings: Settings) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with injected SQLite session and configuration."""
    app = create_app(settings=test_settings)

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# 1. Configuration, Security, and Client Lifecycle Tests
# =============================================================================

def test_sanitize_mongo_uri_redacts_credentials():
    """Verify passwords and usernames are completely stripped from logged URIs."""
    raw_uri = "mongodb+srv://admin_user:P@ssw0rd!#123@cluster0.test.mongodb.net/analytics?retryWrites=true"
    sanitized = sanitize_mongo_uri(raw_uri)
    assert "admin_user" not in sanitized
    assert "P@ssw0rd!#123" not in sanitized
    assert "mongodb+srv://***:***@cluster0.test.mongodb.net/analytics" in sanitized

    # Empty and None cases
    assert sanitize_mongo_uri("") == "<not-configured>"


def test_missing_mongo_uri_handled_gracefully():
    """Verify application runs in offline mode when MONGODB_URI is not set."""
    offline_settings = Settings(mongodb_uri="")
    assert offline_settings.mongodb_uri == ""
    assert offline_settings.is_mongo_configured is False

    is_connected, desc = check_mongo_connectivity(offline_settings)
    assert is_connected is False
    assert desc == "not_configured"

    # get_mongo_client returns None without error
    client = get_mongo_client(offline_settings)
    assert client is None


def test_client_cleanup_lifecycle():
    """Verify close_mongo_client safely releases connections."""
    close_mongo_client()  # Safe to call when none active
    close_mongo_client()


def test_ensure_indexes_creates_specs(mock_mongo_db: mongomock.Database):
    """Verify analytics indexes are created on collections."""
    result = ensure_indexes(mock_mongo_db)
    assert TELEMETRY_COLLECTION in result
    assert ALERTS_COLLECTION in result
    assert len(result[TELEMETRY_COLLECTION]) == len(TELEMETRY_INDEXES)
    assert len(result[ALERTS_COLLECTION]) == len(ALERT_INDEXES)


# =============================================================================
# 2. Document Mapping & Privacy Tests
# =============================================================================

def test_build_telemetry_document_preserves_units_and_privacy():
    """Verify telemetry document captures physiological metrics and provenance without secrets."""
    now = datetime.now(timezone.utc)
    event = IngestionEvent(
        event_id="evt_map_001",
        patient_id="P101",
        source="simulator",
        source_event_id="sim_100",
        measured_at=now,
        is_simulated=True,
    )
    r_hr = VitalsReading(
        event_id="evt_map_001",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("84.50"),
        unit="bpm",
        raw_value=Decimal("84.50"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    r_temp = VitalsReading(
        event_id="evt_map_001",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("37.00"),
        unit="degC",
        raw_value=Decimal("98.60"),
        raw_unit="degF",
        quality_status="valid",
        measured_at=now,
    )
    event.readings = [r_hr, r_temp]

    doc = build_telemetry_document(event)

    assert doc["_id"] == "evt_map_001"
    assert doc["patient_id"] == "P101"
    assert doc["source"] == "simulator"
    assert doc["is_simulated"] is True
    assert doc["metrics"]["heart_rate"] == 84.5
    assert doc["metrics"]["temperature_c"] == 37.0
    assert doc["metrics"]["temperature_f"] == 98.6
    assert doc["metrics"]["spo2"] is None
    assert doc["schema_version"] == 1

    # Security check: no credentials or user profiles
    doc_str = json.dumps(doc, default=str)
    assert "password" not in doc_str
    assert "token" not in doc_str
    assert "secret" not in doc_str


def test_build_alert_document_preserves_monotonic_rank():
    """Verify alert document sets state_rank correctly for lifecycle states."""
    now = datetime.now(timezone.utc)
    alert = Alert(
        alert_id="alt_map_001",
        patient_id="P101",
        event_id="evt_map_001",
        rule_id="RULE_HR_HIGH",
        severity="HIGH",
        category="vital_threshold",
        reason="Heart rate elevated",
        status="NEW",
        created_at=now,
    )
    doc_new = build_alert_document(alert)
    assert doc_new["_id"] == "alt_map_001"
    assert doc_new["status"] == "NEW"
    assert doc_new["state_rank"] == 1

    # Update to ACKNOWLEDGED
    alert.status = "ACKNOWLEDGED"
    alert.acknowledged_by = "usr_doc1"
    alert.acknowledged_at = now
    doc_ack = build_alert_document(alert)
    assert doc_ack["status"] == "ACKNOWLEDGED"
    assert doc_ack["state_rank"] == 2
    assert doc_ack["acknowledged_by"] == "usr_doc1"

    # Update to RESOLVED
    alert.status = "RESOLVED"
    doc_res = build_alert_document(alert)
    assert doc_res["status"] == "RESOLVED"
    assert doc_res["state_rank"] == 3


def test_document_serialization_roundtrip():
    """Verify JSON serialization and deserialization roundtrip maintains datetime semantics."""
    now = datetime.now(timezone.utc)
    original = {
        "_id": "evt_test",
        "measured_at": now,
        "value": Decimal("98.60"),
        "patient": "P101",
    }
    json_str = document_to_json(original)
    restored = json_to_document(json_str)

    assert restored["_id"] == "evt_test"
    assert restored["patient"] == "P101"
    assert isinstance(restored["measured_at"], datetime)


# =============================================================================
# 3. Idempotent Repository Operations Tests
# =============================================================================

def test_telemetry_repository_idempotent_upsert(mock_mongo_db: mongomock.Database):
    """Verify repeated upsert of same telemetry event does not duplicate documents."""
    repo = TelemetryMirrorRepository(mock_mongo_db)
    now = datetime.now(timezone.utc)

    doc = {
        "_id": "evt_idem_1",
        "event_id": "evt_idem_1",
        "patient_id": "P101",
        "measured_at": now,
        "metrics": {"heart_rate": 80.0},
    }

    # 1. First upsert
    assert repo.upsert_event(doc) is True
    assert repo.count_events(patient_id="P101") == 1

    # 2. Second upsert (same event_id)
    doc_updated = dict(doc)
    doc_updated["metrics"] = {"heart_rate": 82.0}
    assert repo.upsert_event(doc_updated) is True

    # Document count must still be 1, but with updated values
    assert repo.count_events(patient_id="P101") == 1
    persisted = repo.get_by_id("evt_idem_1")
    assert persisted is not None
    assert persisted["metrics"]["heart_rate"] == 82.0


def test_identical_measurements_different_events_remain_distinct(mock_mongo_db: mongomock.Database):
    """Verify that different legitimate events with identical measurements are NOT deduplicated."""
    repo = TelemetryMirrorRepository(mock_mongo_db)
    now = datetime.now(timezone.utc)

    # Event A
    doc_a = {
        "_id": "evt_distinct_A",
        "event_id": "evt_distinct_A",
        "patient_id": "P101",
        "measured_at": now,
        "metrics": {"heart_rate": 72.0, "spo2": 98.0},
    }
    # Event B (different event_id, exact same values and timestamp)
    doc_b = {
        "_id": "evt_distinct_B",
        "event_id": "evt_distinct_B",
        "patient_id": "P101",
        "measured_at": now,
        "metrics": {"heart_rate": 72.0, "spo2": 98.0},
    }

    repo.upsert_event(doc_a)
    repo.upsert_event(doc_b)

    assert repo.count_events(patient_id="P101") == 2
    assert repo.get_by_id("evt_distinct_A") is not None
    assert repo.get_by_id("evt_distinct_B") is not None


def test_alert_monotonic_state_conflict_resolution(mock_mongo_db: mongomock.Database):
    """Verify out-of-order event delivery cannot downgrade an ACKNOWLEDGED alert back to NEW."""
    repo = AlertMirrorRepository(mock_mongo_db)
    now = datetime.now(timezone.utc)

    # 1. Newer state arrives first: ACKNOWLEDGED (rank 2)
    doc_ack = {
        "_id": "alt_conflict_1",
        "alert_id": "alt_conflict_1",
        "patient_id": "P101",
        "status": "ACKNOWLEDGED",
        "state_rank": 2,
        "acknowledged_by": "usr_doc1",
        "acknowledged_at": now,
        "reason": "Initial alert reason",
    }
    repo.upsert_alert(doc_ack)
    assert repo.get_by_id("alt_conflict_1")["status"] == "ACKNOWLEDGED"

    # 2. Delayed, out-of-order event arrives: NEW (rank 1)
    doc_delayed_new = {
        "_id": "alt_conflict_1",
        "alert_id": "alt_conflict_1",
        "patient_id": "P101",
        "status": "NEW",
        "state_rank": 1,
        "acknowledged_by": None,
        "acknowledged_at": None,
        "reason": "Updated description",
    }
    repo.upsert_alert(doc_delayed_new)

    # Status MUST remain ACKNOWLEDGED and keep its actor/timestamp
    persisted = repo.get_by_id("alt_conflict_1")
    assert persisted["status"] == "ACKNOWLEDGED"
    assert persisted["state_rank"] == 2
    assert persisted["acknowledged_at"] is not None
    time_diff = abs(persisted["acknowledged_at"].replace(tzinfo=timezone.utc).timestamp() - now.timestamp())
    assert time_diff < 0.01


# =============================================================================
# 4. Outbox Staging, Retry, and Failure Recovery Tests
# =============================================================================

def test_outbox_staging_and_processing_batch(
    test_db_session: Session,
    mock_mongo_db: mongomock.Database,
):
    """Verify outbox records are staged, processed, and updated to completed."""
    sync_service = OutboxSyncService(test_db_session, mongo_db=mock_mongo_db)
    now = datetime.now(timezone.utc)

    # 1. Seed IngestionEvent in SQLite
    patient = PatientProfile(patient_id="P101", user_id="usr_p1", first_name="A", last_name="P")
    event = IngestionEvent(
        event_id="evt_outbox_01",
        patient_id="P101",
        source="simulator",
        source_event_id="s1",
        measured_at=now,
        is_simulated=True,
    )
    test_db_session.add_all([patient, event])
    test_db_session.commit()

    # 2. Stage to outbox
    outbox_entry = sync_service.stage_telemetry(event)
    test_db_session.commit()

    assert outbox_entry.status == "pending"
    assert outbox_entry.attempt_count == 0

    # 3. Process outbox batch
    summary = sync_service.process_outbox_batch(limit=10)
    test_db_session.commit()

    assert summary["status"] == "processed"
    assert summary["processed"] == 1
    assert summary["succeeded"] == 1
    assert summary["failed"] == 0

    # Verify MongoDB received document
    telemetry_repo = TelemetryMirrorRepository(mock_mongo_db)
    doc = telemetry_repo.get_by_id("evt_outbox_01")
    assert doc is not None
    assert doc["patient_id"] == "P101"

    # Verify outbox entry is completed and IngestionEvent is mirrored
    reloaded_outbox = sync_service.outbox_repo.get_by_id(outbox_entry.outbox_id)
    assert reloaded_outbox.status == "completed"
    assert reloaded_outbox.completed_at is not None

    reloaded_event = test_db_session.get(IngestionEvent, "evt_outbox_01")
    assert reloaded_event.mirror_status == "mirrored"


def test_outbox_exhausted_retries_marked_failed(test_db_session: Session):
    """Verify outbox entry transitions to 'failed' when max_attempts is reached."""
    outbox_repo = OutboxRepository(test_db_session)
    entry = outbox_repo.stage_event(
        event_type="telemetry_event",
        aggregate_id="evt_fail_01",
        payload_json='{"_id": "evt_fail_01"}',
        max_attempts=2,
    )
    test_db_session.commit()

    # Attempt 1: marks pending for retry
    outbox_repo.mark_processing(entry.outbox_id)
    outbox_repo.mark_failed(entry.outbox_id, "Network timeout")
    test_db_session.commit()
    assert entry.status == "pending"
    assert entry.attempt_count == 1

    # Attempt 2: max_attempts reached -> marks failed
    outbox_repo.mark_processing(entry.outbox_id)
    outbox_repo.mark_failed(entry.outbox_id, "DNS resolution failure")
    test_db_session.commit()
    assert entry.status == "failed"
    assert entry.attempt_count == 2
    assert "DNS resolution failure" in entry.last_error

    # Outbox stats count failed
    stats = outbox_repo.get_outbox_stats()
    assert stats["failed"] == 1


def test_mysql_success_is_never_aborted_by_mongodb_outage(
    test_db_session: Session,
    mock_mongo_db: mongomock.Database,
):
    """
    CRITICAL DISTRIBUTED SYSTEM REQUIREMENT:
    MySQL write MUST NOT fail solely because MongoDB is down.
    The event is safely staged in the outbox as pending.
    """
    now = datetime.now(timezone.utc)
    patient = PatientProfile(patient_id="P101", user_id="usr_p1", first_name="A", last_name="P")
    event = IngestionEvent(
        event_id="evt_resilient_01",
        patient_id="P101",
        source="simulator",
        source_event_id="s_res",
        measured_at=now,
        is_simulated=True,
    )
    test_db_session.add_all([patient, event])
    test_db_session.commit()

    # Simulate MongoDB throwing ConnectionFailure on upsert
    broken_mongo = MagicMock()
    broken_mongo.__getitem__.return_value.replace_one.side_effect = ConnectionFailure("Atlas connection timeout")

    sync_service = OutboxSyncService(test_db_session, mongo_db=broken_mongo)
    synced = sync_service.sync_telemetry_immediate(event)
    test_db_session.commit()

    # Immediate sync returns False, but NO exception is raised to abort MySQL
    assert synced is False

    # Event remains persisted in MySQL
    saved_event = test_db_session.get(IngestionEvent, "evt_resilient_01")
    assert saved_event is not None

    # Event is safely in outbox awaiting retry recovery
    outbox_entries = sync_service.outbox_repo.get_pending_batch()
    assert any(e.aggregate_id == "evt_resilient_01" for e in outbox_entries)


# =============================================================================
# 5. Diagnostic Health Probe Tests
# =============================================================================

def test_api_health_mongodb_endpoint(client: TestClient, test_db_session: Session):
    """Verify /health/mongodb endpoint reports sanitized status and outbox statistics."""
    # Seed an outbox entry
    repo = OutboxRepository(test_db_session)
    repo.stage_event("telemetry_event", "evt_diag_01", "{}")
    test_db_session.commit()

    response = client.get("/health/mongodb")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "database" in data
    assert "endpoint" in data
    assert "outbox_queue" in data
    assert data["outbox_queue"]["pending"] >= 1

    # Security check: Endpoint string must NEVER contain real passwords
    assert "SuperSecretPassword123" not in data["endpoint"]
    assert "test_user" not in data["endpoint"]
    assert "***:***" in data["endpoint"]


def test_outbox_processing_when_mongodb_is_none(test_db_session: Session):
    """Verify outbox batch processing handles unconfigured/None mongodb cleanly."""
    sync_service = OutboxSyncService(test_db_session, mongo_db=None)
    res = sync_service.process_outbox_batch()
    assert res["status"] == "mongodb_unavailable"
    assert res["processed"] == 0


def test_telemetry_find_by_patient_and_time_range(mock_mongo_db: mongomock.Database):
    """Verify time-range filtered point queries on telemetry mirror."""
    repo = TelemetryMirrorRepository(mock_mongo_db)
    base_time = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)

    # Seed 3 events across time
    for i in range(3):
        t = datetime(2026, 10, 13, 10, i * 15, 0, tzinfo=timezone.utc)
        doc = {
            "_id": f"evt_time_{i}",
            "event_id": f"evt_time_{i}",
            "patient_id": "P101",
            "measured_at": t,
            "metrics": {"heart_rate": 70.0 + i},
        }
        repo.upsert_event(doc)

    # 1. Query all
    all_events = repo.find_by_patient("P101")
    assert len(all_events) == 3
    # Ordered descending: newest first
    assert all_events[0]["_id"] == "evt_time_2"

    # 2. Query with time window: between 10:10 and 10:35
    filtered = repo.find_by_patient(
        "P101",
        start_time=datetime(2026, 10, 13, 10, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 13, 10, 35, 0, tzinfo=timezone.utc),
    )
    assert len(filtered) == 2
    assert [e["_id"] for e in filtered] == ["evt_time_2", "evt_time_1"]


def test_alert_find_by_patient_and_status(mock_mongo_db: mongomock.Database):
    """Verify filtered alert queries by patient and lifecycle status."""
    repo = AlertMirrorRepository(mock_mongo_db)
    now = datetime.now(timezone.utc)

    repo.upsert_alert({
        "_id": "alt_q_1",
        "alert_id": "alt_q_1",
        "patient_id": "P101",
        "status": "NEW",
        "created_at": now,
    })
    repo.upsert_alert({
        "_id": "alt_q_2",
        "alert_id": "alt_q_2",
        "patient_id": "P101",
        "status": "ACKNOWLEDGED",
        "created_at": now,
    })

    new_alerts = repo.find_by_patient("P101", status="NEW")
    assert len(new_alerts) == 1
    assert new_alerts[0]["_id"] == "alt_q_1"

    ack_alerts = repo.find_by_patient("P101", status="ACKNOWLEDGED")
    assert len(ack_alerts) == 1
    assert ack_alerts[0]["_id"] == "alt_q_2"


def test_sync_alert_immediate_success_and_offline(
    test_db_session: Session,
    mock_mongo_db: mongomock.Database,
):
    """Verify immediate alert synchronization succeeds when online and stages when offline."""
    now = datetime.now(timezone.utc)
    patient = PatientProfile(patient_id="P101", user_id="usr_p1", first_name="A", last_name="P")
    alert = Alert(
        alert_id="alt_imm_01",
        patient_id="P101",
        severity="HIGH",
        category="vital_threshold",
        reason="Immediate test",
        status="NEW",
        created_at=now,
    )
    test_db_session.add_all([patient, alert])
    test_db_session.commit()

    # 1. Online immediate sync
    sync_online = OutboxSyncService(test_db_session, mongo_db=mock_mongo_db)
    assert sync_online.sync_alert_immediate(alert) is True
    assert AlertMirrorRepository(mock_mongo_db).get_by_id("alt_imm_01") is not None

    # 2. Offline immediate sync
    alert_offline = Alert(
        alert_id="alt_imm_off",
        patient_id="P101",
        severity="MEDIUM",
        category="vital_threshold",
        reason="Offline test",
        status="NEW",
        created_at=now,
    )
    test_db_session.add(alert_offline)
    test_db_session.commit()

    sync_offline = OutboxSyncService(test_db_session, mongo_db=None)
    assert sync_offline.sync_alert_immediate(alert_offline) is False
    # Staged in outbox as pending
    pending = sync_offline.outbox_repo.get_pending_batch()
    assert any(e.aggregate_id == "alt_imm_off" for e in pending)


def test_interrupted_worker_resumes_processing_status(test_db_session: Session):
    """Verify a worker crash leaving an event in 'processing' status is not permanently lost."""
    repo = OutboxRepository(test_db_session)
    entry = repo.stage_event("telemetry_event", "evt_crash_01", "{}")
    test_db_session.commit()

    # Worker started processing and then crashed
    repo.mark_processing(entry.outbox_id)
    test_db_session.commit()
    assert entry.status == "processing"

    # Next worker iteration must retrieve it for recovery
    pending = repo.get_pending_batch()
    assert any(e.outbox_id == entry.outbox_id for e in pending)

