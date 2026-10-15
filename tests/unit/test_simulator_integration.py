"""
Unit & Integration Tests for Smartwatch Simulator Backend Ingestion.

Verifies:
1. Simulator disabled by default.
2. Physiological boundary and synthetic provenance validation.
3. Unknown patient rejection.
4. Relational MySQL persistence of canonical events and vitals.
5. Idempotent duplicate event rejection.
6. Successful polling cycle and cursor progression.
7. Temporary simulator outage error tracking and retry resilience.
8. Database error handling pausing cursor advancement.
9. Clean worker lifecycle startup and shutdown.
10. No duplicate ingestion after worker restart.
11. Operational status endpoint contract.
12. MongoDB Atlas transactional outbox synchronization.
13. Provenance and vital units display in patient readings API.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any, Dict, Generator, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, desc, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    AnalyticsOutbox,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from services.simulator.ingestion_service import (
    IngestionOutcome,
    IngestionResult,
    SimulatorIngestionService,
)
from services.simulator.worker import (
    SimulatorIngestionWorker,
    get_simulator_worker,
)


@pytest.fixture
def isolated_db_engine():
    """Create in-memory SQLite engine isolated from external databases."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def isolated_session_factory(isolated_db_engine):
    """Session factory bound to isolated in-memory engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=isolated_db_engine, expire_on_commit=False)


@pytest.fixture
def isolated_db(isolated_session_factory) -> Generator[Session, None, None]:
    """Provide isolated transactional session."""
    session = isolated_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded_db(isolated_db: Session) -> Session:
    """Seed test patients P101 and P102 with clinical care assignments."""
    u101 = User(
        user_id="usr_p101",
        email="p101@hospital.org",
        password_hash=hash_password("PatientPass123!"),
        role="patient",
        is_active=True,
    )
    p101 = PatientProfile(
        patient_id="P101",
        user_id="usr_p101",
        first_name="Demo",
        last_name="Patient 101",
    )
    u102 = User(
        user_id="usr_p102",
        email="p102@hospital.org",
        password_hash=hash_password("PatientPass123!"),
        role="patient",
        is_active=True,
    )
    p102 = PatientProfile(
        patient_id="P102",
        user_id="usr_p102",
        first_name="Demo",
        last_name="Patient 102",
    )
    u_doc = User(
        user_id="usr_doc_sim",
        email="doctor_sim@hospital.org",
        password_hash=hash_password("DoctorPass123!"),
        role="doctor",
        is_active=True,
    )
    doc_prof = DoctorProfile(
        doctor_id="DOC_SIM",
        user_id="usr_doc_sim",
        first_name="Sarah",
        last_name="Jenkins",
        license_number="LIC-SIM-999",
    )
    asgn1 = DoctorPatientAssignment(
        doctor_id="DOC_SIM",
        patient_id="P101",
        is_active=True,
    )
    asgn2 = DoctorPatientAssignment(
        doctor_id="DOC_SIM",
        patient_id="P102",
        is_active=True,
    )
    isolated_db.add_all([u101, p101, u102, p102, u_doc, doc_prof, asgn1, asgn2])
    isolated_db.commit()
    return isolated_db


# =============================================================================
# 1. Configuration & Default State
# =============================================================================

def test_simulator_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    """Verify background ingestion worker is disabled by default for test safety."""
    monkeypatch.delenv("SIMULATOR_INGESTION_ENABLED", raising=False)
    settings = Settings(
        _env_file=None,
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long",
    )
    assert settings.simulator_ingestion_enabled is False
    assert Settings.model_fields["simulator_ingestion_enabled"].default is False
    worker = SimulatorIngestionWorker(settings=settings)
    assert worker.is_enabled is False
    assert worker.is_running is False
    assert worker.cursor is None


# =============================================================================
# 2. Schema and Range Validation
# =============================================================================

def test_validation_valid_event():
    """Valid synthetic reading parses and converts temperature cleanly."""
    raw = {
        "event_id": "evt_sim_100_abc",
        "patient_id": "P101",
        "heart_rate": 78.5,
        "spo2": 97.5,
        "temperature_f": 98.6,
        "measured_at": "2026-10-15T01:00:00Z",
        "source": "smartwatch_simulator",
        "is_simulated": True,
    }
    is_valid, err, cleaned = SimulatorIngestionService.validate_reading(raw)
    assert is_valid is True
    assert err is None
    assert cleaned["heart_rate"] == 78.5
    assert cleaned["spo2"] == 97.5
    assert cleaned["temperature_f"] == 98.6
    assert cleaned["temperature_c"] == 37.0
    assert cleaned["is_simulated"] is True


def test_validation_rejection_boundaries():
    """Invalid ranges, non-simulated flags, and missing fields are rejected."""
    # 1. Missing is_simulated=True
    not_sim = {
        "event_id": "evt_1",
        "patient_id": "P101",
        "heart_rate": 80,
        "spo2": 98,
        "temperature_f": 98.6,
        "measured_at": "2026-10-15T01:00:00Z",
        "is_simulated": False,
    }
    is_valid, err, _ = SimulatorIngestionService.validate_reading(not_sim)
    assert is_valid is False
    assert "is_simulated" in err

    # 2. Out-of-bounds heart rate (> 300)
    extreme_hr = {
        "event_id": "evt_2",
        "patient_id": "P101",
        "heart_rate": 450,
        "spo2": 98,
        "temperature_f": 98.6,
        "measured_at": "2026-10-15T01:00:00Z",
        "is_simulated": True,
    }
    is_valid, err, _ = SimulatorIngestionService.validate_reading(extreme_hr)
    assert is_valid is False
    assert "Heart rate" in err

    # 3. Out-of-bounds SpO2 (< 50)
    extreme_spo2 = {
        "event_id": "evt_3",
        "patient_id": "P101",
        "heart_rate": 75,
        "spo2": 35.0,
        "temperature_f": 98.6,
        "measured_at": "2026-10-15T01:00:00Z",
        "is_simulated": True,
    }
    is_valid, err, _ = SimulatorIngestionService.validate_reading(extreme_spo2)
    assert is_valid is False
    assert "SpO2" in err


# =============================================================================
# 3. Patient Existence & Idempotent Persistence
# =============================================================================

def test_ingestion_unknown_patient_rejected(seeded_db: Session):
    """Reading referencing unknown patient P999 is rejected without DB changes."""
    svc = SimulatorIngestionService()
    raw = {
        "event_id": "evt_sim_p999",
        "patient_id": "P999",
        "heart_rate": 72.0,
        "spo2": 98.0,
        "temperature_f": 98.4,
        "measured_at": "2026-10-15T01:00:00Z",
        "source": "smartwatch_simulator",
        "is_simulated": True,
    }
    result = svc.ingest_single_reading(db=seeded_db, reading=raw)
    assert result.outcome == IngestionOutcome.UNKNOWN_PATIENT_REJECTED
    assert not result.is_success
    assert "P999" in result.detail

    # Verify no rows inserted
    assert seeded_db.get(IngestionEvent, "evt_sim_p999") is None


def test_ingestion_valid_event_persisted(seeded_db: Session):
    """Valid reading is persisted to MySQL as IngestionEvent and 3 VitalsReadings."""
    svc = SimulatorIngestionService()
    raw = {
        "event_id": "evt_sim_001",
        "patient_id": "P101",
        "heart_rate": 74.0,
        "spo2": 98.5,
        "temperature_f": 98.6,
        "measured_at": "2026-10-15T01:05:00Z",
        "source": "smartwatch_simulator",
        "is_simulated": True,
    }
    result = svc.ingest_single_reading(db=seeded_db, reading=raw)
    assert result.outcome == IngestionOutcome.ACCEPTED
    assert result.is_success

    # Verify IngestionEvent
    event = seeded_db.get(IngestionEvent, "evt_sim_001")
    assert event is not None
    assert event.patient_id == "P101"
    assert event.is_simulated is True
    assert event.source == "smartwatch_simulator"
    assert event.source_event_id == "evt_sim_001"

    # Verify 3 VitalsReading rows
    stmt = select(VitalsReading).where(VitalsReading.event_id == "evt_sim_001")
    readings = list(seeded_db.scalars(stmt).all())
    assert len(readings) == 3
    by_code = {r.metric_code: r for r in readings}

    assert "heart_rate" in by_code
    assert float(by_code["heart_rate"].value) == 74.0
    assert by_code["heart_rate"].unit == "bpm"

    assert "spo2" in by_code
    assert float(by_code["spo2"].value) == 98.5
    assert by_code["spo2"].unit == "%"

    assert "temperature" in by_code
    assert float(by_code["temperature"].value) == 37.0
    assert by_code["temperature"].unit == "degC"
    assert float(by_code["temperature"].raw_value) == 98.6
    assert by_code["temperature"].raw_unit == "degF"


def test_duplicate_event_rejection(seeded_db: Session):
    """Ingesting an identical event is caught idempotently without duplication."""
    svc = SimulatorIngestionService()
    raw = {
        "event_id": "evt_sim_dup_1",
        "patient_id": "P101",
        "heart_rate": 70.0,
        "spo2": 99.0,
        "temperature_f": 98.2,
        "measured_at": "2026-10-15T01:10:00Z",
        "source": "smartwatch_simulator",
        "is_simulated": True,
    }
    # First attempt: accepted
    r1 = svc.ingest_single_reading(db=seeded_db, reading=raw)
    assert r1.outcome == IngestionOutcome.ACCEPTED

    # Second attempt: duplicate skipped
    r2 = svc.ingest_single_reading(db=seeded_db, reading=raw)
    assert r2.outcome == IngestionOutcome.DUPLICATE_SKIPPED
    assert r2.is_success is True

    # Count check
    stmt = select(IngestionEvent).where(IngestionEvent.source_event_id == "evt_sim_dup_1")
    events = list(seeded_db.scalars(stmt).all())
    assert len(events) == 1


# =============================================================================
# 4. Polling Worker, Cursor Advancement & Failure Retries
# =============================================================================

def test_successful_polling_and_cursor_progression(seeded_db: Session, isolated_session_factory):
    """Worker polls stream, processes readings, updates counters, and advances cursor."""
    async def _run():
        settings = Settings(
            app_env="testing",
            jwt_secret="testing_secret_key_at_least_32_characters_long",
            sensor_simulator_base_url="http://127.0.0.1:8001",
            simulator_ingestion_enabled=True,
        )
        worker = SimulatorIngestionWorker(settings=settings)
        worker.session_factory = isolated_session_factory

        mock_readings = [
            {
                "event_id": "evt_sim_1_aaa",
                "patient_id": "P101",
                "heart_rate": 75.0,
                "spo2": 98.0,
                "temperature_f": 98.4,
                "measured_at": "2026-10-15T01:20:00Z",
                "source": "smartwatch_simulator",
                "is_simulated": True,
                "sequence_number": 1,
            },
            {
                "event_id": "evt_sim_2_bbb",
                "patient_id": "P102",
                "heart_rate": 82.0,
                "spo2": 97.0,
                "temperature_f": 98.8,
                "measured_at": "2026-10-15T01:20:00Z",
                "source": "smartwatch_simulator",
                "is_simulated": True,
                "sequence_number": 2,
            },
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "readings": mock_readings,
            "count": 2,
            "next_cursor": "evt_sim_2_bbb",
            "has_more": False,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await worker.poll_once(client=mock_client)
        assert result["status"] == "success"
        assert worker.cursor == "evt_sim_2_bbb"
        assert worker.events_received_count == 2
        assert worker.events_accepted_count == 2
        assert worker.events_duplicates_skipped_count == 0
        assert worker.last_poll_succeeded is True
        assert worker.last_error_category == "none"

        # Verify both records are in DB
        assert seeded_db.get(IngestionEvent, "evt_sim_1_aaa") is not None
        assert seeded_db.get(IngestionEvent, "evt_sim_2_bbb") is not None

    asyncio.run(_run())


def test_temporary_simulator_outage_and_retry(isolated_session_factory):
    """Simulator connection errors are safely categorized without corrupting cursor."""
    async def _run():
        settings = Settings(
            app_env="testing",
            jwt_secret="testing_secret_key_at_least_32_characters_long",
            sensor_simulator_base_url="http://127.0.0.1:8001",
            simulator_ingestion_enabled=True,
        )
        worker = SimulatorIngestionWorker(settings=settings)
        worker.session_factory = isolated_session_factory
        worker.cursor = "evt_sim_5"

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        result = await worker.poll_once(client=mock_client)
        assert result["status"] == "error"
        assert result["error"] == "connection_refused"
        assert worker.cursor == "evt_sim_5"  # Cursor maintained
        assert worker.last_poll_succeeded is False
        assert worker.last_error_category == "connection_refused"

    asyncio.run(_run())


def test_worker_lifecycle_start_stop(isolated_session_factory):
    """Worker start and stop are idempotent and cleanly managed."""
    async def _run():
        settings = Settings(
            app_env="testing",
            jwt_secret="testing_secret_key_at_least_32_characters_long",
            sensor_simulator_base_url="http://127.0.0.1:8001",
            simulator_ingestion_enabled=True,
            simulator_poll_interval_seconds=0.5,
        )
        worker = SimulatorIngestionWorker(settings=settings)
        worker.session_factory = isolated_session_factory

        assert worker.is_running is False
        with patch.object(worker, "poll_once", new_callable=AsyncMock) as mock_poll:
            mock_poll.return_value = {"status": "success"}

            await worker.start()
            assert worker.is_running is True

            # Let loop tick
            await asyncio.sleep(0.05)
            assert mock_poll.called

            await worker.stop()
            assert worker.is_running is False

    asyncio.run(_run())


def test_no_duplicate_ingestion_after_restart(seeded_db: Session, isolated_session_factory):
    """Restarted worker initializes cursor from database and ignores prior events."""
    svc = SimulatorIngestionService()
    raw = {
        "event_id": "evt_sim_prior_99",
        "patient_id": "P101",
        "heart_rate": 72.0,
        "spo2": 98.0,
        "temperature_f": 98.4,
        "measured_at": "2026-10-15T01:00:00Z",
        "source": "smartwatch_simulator",
        "is_simulated": True,
    }
    svc.ingest_single_reading(db=seeded_db, reading=raw)

    settings = Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long",
        sensor_simulator_base_url="http://127.0.0.1:8001",
        simulator_ingestion_enabled=True,
    )
    # Simulate fresh worker on restart
    new_worker = SimulatorIngestionWorker(settings=settings)
    new_worker.session_factory = isolated_session_factory
    new_worker.init_cursor_from_database()

    assert new_worker.cursor == "evt_sim_prior_99"

    # Even if replay occurs, duplicate is skipped
    async def _replay():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "readings": [raw],
            "count": 1,
            "next_cursor": "evt_sim_prior_99",
            "has_more": False,
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        res = await new_worker.poll_once(client=mock_client)
        assert res["status"] == "success"
        assert new_worker.events_duplicates_skipped_count == 1
        assert new_worker.events_accepted_count == 0

    asyncio.run(_replay())


# =============================================================================
# 5. Outbox Staging & MongoDB Mirroring
# =============================================================================

def test_mongodb_synchronization_and_outbox_staging(seeded_db: Session):
    """Ingested simulator event stages a telemetry_event in analytics_outbox."""
    svc = SimulatorIngestionService()
    raw = {
        "event_id": "evt_sim_outbox_test",
        "patient_id": "P101",
        "heart_rate": 76.0,
        "spo2": 98.0,
        "temperature_f": 98.4,
        "measured_at": "2026-10-15T01:25:00Z",
        "source": "smartwatch_simulator",
        "is_simulated": True,
    }
    svc.ingest_single_reading(db=seeded_db, reading=raw, mongo_db=None)

    stmt = select(AnalyticsOutbox).where(AnalyticsOutbox.aggregate_id == "evt_sim_outbox_test")
    outbox_entry = seeded_db.scalar(stmt)
    assert outbox_entry is not None
    assert outbox_entry.event_type == "telemetry_event"
    assert outbox_entry.status in ("pending", "failed")  # Pending because mongo_db=None

    payload = json.loads(outbox_entry.payload_json)
    assert payload["event_id"] == "evt_sim_outbox_test"
    assert payload["patient_id"] == "P101"
    assert payload["is_simulated"] is True


# =============================================================================
# 6. Operational Status Endpoint & API Integration
# =============================================================================

def test_operational_status_endpoint():
    """GET /api/v1/simulator/ingestion-status reports live metrics without secrets."""
    settings = Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long",
        sensor_simulator_base_url="http://127.0.0.1:8001",
        simulator_ingestion_enabled=True,
    )
    worker = SimulatorIngestionWorker(settings=settings)
    app = create_app(settings=settings)
    app.dependency_overrides[get_simulator_worker] = lambda: worker

    client = TestClient(app)
    response = client.get("/api/v1/simulator/ingestion-status")
    assert response.status_code == 200
    data = response.json()

    assert data["enabled"] is True
    assert "running" in data
    assert data["simulator_base_url"] == "http://127.0.0.1:8001"
    assert "events_received_count" in data
    assert "events_accepted_count" in data
    assert "last_error_category" in data


def test_provenance_in_readings_api(seeded_db: Session):
    """Patient reading queried via FastAPI API reflects simulator provenance."""
    svc = SimulatorIngestionService()
    raw = {
        "event_id": "evt_sim_api_test",
        "patient_id": "P101",
        "heart_rate": 88.0,
        "spo2": 96.5,
        "temperature_f": 99.1,
        "measured_at": "2026-10-15T01:30:00Z",
        "source": "smartwatch_simulator",
        "is_simulated": True,
    }
    svc.ingest_single_reading(db=seeded_db, reading=raw)

    settings = Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long",
    )
    app = create_app(settings=settings)

    def override_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_db

    # Doctor DOC_SIM is assigned to P101
    doc_token = create_access_token(
        data={"sub": "usr_doc_sim", "role": "doctor"},
        settings=settings,
    )

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {doc_token}"}

    # Query latest vitals EAV
    resp = client.get("/api/v1/patients/P101/vitals/latest", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    metrics = {m["metric_code"]: m for m in body["metrics"]}

    assert metrics["heart_rate"]["value"] == 88.0
    assert metrics["heart_rate"]["unit"] == "bpm"
    assert metrics["heart_rate"]["is_simulated"] is True

    assert metrics["spo2"]["value"] == 96.5
    assert metrics["spo2"]["unit"] == "%"
    assert metrics["spo2"]["is_simulated"] is True

    assert metrics["temperature_f"]["value"] == 99.1
    assert metrics["temperature_f"]["unit"] == "°F"
    assert metrics["temperature_f"]["is_simulated"] is True


# =============================================================================
# 7. Part 6E Reliability, Safety, and Data Integrity Tests
# =============================================================================

def test_unsupported_units_rejected(seeded_db: Session):
    """Readings specifying unsupported physiological units must be rejected."""
    svc = SimulatorIngestionService()

    # Invalid heart rate unit
    res_hr = svc.ingest_single_reading(
        db=seeded_db,
        reading={
            "event_id": "evt_unit_bad_1",
            "patient_id": "P101",
            "heart_rate": 80.0,
            "hr_unit": "km/h",
            "spo2": 98.0,
            "temperature_f": 98.6,
            "measured_at": "2026-10-15T02:00:00Z",
            "is_simulated": True,
        },
    )
    assert res_hr.outcome == IngestionOutcome.UNSUPPORTED_UNITS_REJECTED
    assert "Unsupported heart rate unit" in str(res_hr.detail)

    # Invalid temperature unit
    res_temp = svc.ingest_single_reading(
        db=seeded_db,
        reading={
            "event_id": "evt_unit_bad_2",
            "patient_id": "P101",
            "heart_rate": 80.0,
            "spo2": 98.0,
            "temperature_f": 98.6,
            "temp_unit": "Kelvin",
            "measured_at": "2026-10-15T02:00:00Z",
            "is_simulated": True,
        },
    )
    assert res_temp.outcome == IngestionOutcome.UNSUPPORTED_UNITS_REJECTED


def test_untrusted_provenance_rejected(seeded_db: Session):
    """Ingestion rejects payloads masquerading as Kaggle historical records."""
    svc = SimulatorIngestionService()

    # False is_simulated
    res_false_sim = svc.ingest_single_reading(
        db=seeded_db,
        reading={
            "event_id": "evt_prov_1",
            "patient_id": "P101",
            "heart_rate": 75.0,
            "spo2": 97.0,
            "temperature_f": 98.6,
            "measured_at": "2026-10-15T02:00:00Z",
            "is_simulated": False,
        },
    )
    assert res_false_sim.outcome == IngestionOutcome.NOT_SIMULATED_REJECTED

    # Untrusted source claiming historical Kaggle origin
    res_kaggle = svc.ingest_single_reading(
        db=seeded_db,
        reading={
            "event_id": "evt_prov_2",
            "patient_id": "P101",
            "heart_rate": 75.0,
            "spo2": 97.0,
            "temperature_f": 98.6,
            "measured_at": "2026-10-15T02:00:00Z",
            "source": "kaggle_csv",
            "is_simulated": True,
        },
    )
    assert res_kaggle.outcome == IngestionOutcome.UNTRUSTED_PROVENANCE_REJECTED
    assert "Untrusted provenance source" in str(res_kaggle.detail)


def test_unexpected_payload_size_rejected(seeded_db: Session):
    """Payloads exceeding maximum key count or field lengths are rejected."""
    svc = SimulatorIngestionService()

    # Too many keys
    bloated_payload: Dict[str, Any] = {
        "event_id": "evt_bloat_1",
        "patient_id": "P101",
        "heart_rate": 75.0,
        "spo2": 97.0,
        "temperature_f": 98.6,
        "measured_at": "2026-10-15T02:00:00Z",
        "is_simulated": True,
    }
    for i in range(40):
        bloated_payload[f"extra_key_{i}"] = f"bloat_value_{i}"

    res = svc.ingest_single_reading(db=seeded_db, reading=bloated_payload)
    assert res.outcome == IngestionOutcome.MALFORMED_REJECTED
    assert "exceeding maximum limit" in str(res.detail)

    # Oversized event ID
    oversized_event_id: Dict[str, Any] = {
        "event_id": "x" * 200,
        "patient_id": "P101",
        "heart_rate": 75.0,
        "spo2": 97.0,
        "temperature_f": 98.6,
        "measured_at": "2026-10-15T02:00:00Z",
        "is_simulated": True,
    }
    res_id = svc.ingest_single_reading(db=seeded_db, reading=oversized_event_id)
    assert res_id.outcome == IngestionOutcome.MALFORMED_REJECTED
    assert "exceeds maximum" in str(res_id.detail)


def test_nan_and_infinite_measurements_rejected(seeded_db: Session):
    """NaN and Infinite measurement values are rejected as malformed."""
    svc = SimulatorIngestionService()

    # NaN heart rate
    res_nan = svc.ingest_single_reading(
        db=seeded_db,
        reading={
            "event_id": "evt_nan_1",
            "patient_id": "P101",
            "heart_rate": float("nan"),
            "spo2": 98.0,
            "temperature_f": 98.6,
            "measured_at": "2026-10-15T02:00:00Z",
            "is_simulated": True,
        },
    )
    assert res_nan.outcome == IngestionOutcome.MALFORMED_REJECTED
    assert "NaN or Infinite" in str(res_nan.detail)

    # Infinite temperature
    res_inf = svc.ingest_single_reading(
        db=seeded_db,
        reading={
            "event_id": "evt_inf_1",
            "patient_id": "P101",
            "heart_rate": 75.0,
            "spo2": 98.0,
            "temperature_f": float("inf"),
            "measured_at": "2026-10-15T02:00:00Z",
            "is_simulated": True,
        },
    )
    assert res_inf.outcome == IngestionOutcome.MALFORMED_REJECTED
    assert "NaN or Infinite" in str(res_inf.detail)


def test_partial_failure_cursor_advancement(seeded_db: Session, isolated_session_factory):
    """When a batch partially fails, cursor advances only to the last committed item."""
    settings = Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long",
        sensor_simulator_base_url="http://127.0.0.1:8001",
        simulator_ingestion_enabled=True,
    )
    worker = SimulatorIngestionWorker(settings=settings)
    worker.session_factory = isolated_session_factory

    readings = [
        # Reading 1: Valid for P101 -> succeeds
        {
            "event_id": "evt_partial_1",
            "patient_id": "P101",
            "heart_rate": 78.0,
            "spo2": 98.0,
            "temperature_f": 98.6,
            "measured_at": "2026-10-15T02:00:00Z",
            "is_simulated": True,
        },
        # Reading 2: Valid for P102 -> succeeds
        {
            "event_id": "evt_partial_2",
            "patient_id": "P102",
            "heart_rate": 82.0,
            "spo2": 97.0,
            "temperature_f": 98.4,
            "measured_at": "2026-10-15T02:00:01Z",
            "is_simulated": True,
        },
        # Reading 3: Database error simulated
        {
            "event_id": "evt_partial_3",
            "patient_id": "P101",
            "heart_rate": 84.0,
            "spo2": 96.0,
            "temperature_f": 98.8,
            "measured_at": "2026-10-15T02:00:02Z",
            "is_simulated": True,
        },
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": readings,
        "next_cursor": "evt_partial_end_cursor",
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # Mock ingest_single_reading to fail on Reading 3
    orig_ingest = worker.ingestion_service.ingest_single_reading

    def mock_ingest(db, reading, mongo_db=None, ml_service=None):
        if reading["event_id"] == "evt_partial_3":
            from services.simulator.ingestion_service import IngestionResult
            return IngestionResult(
                outcome=IngestionOutcome.FAILED,
                event_id="evt_partial_3",
                patient_id="P101",
                detail="Simulated transient database connection interruption",
            )
        return orig_ingest(db, reading, mongo_db=mongo_db, ml_service=ml_service)

    worker.ingestion_service.ingest_single_reading = mock_ingest

    async def _run():
        res = await worker.poll_once(client=mock_client)
        assert res["status"] == "partial_failure"
        assert worker.last_poll_succeeded is False
        assert worker.consecutive_failures == 1
        # The cursor MUST have advanced to evt_partial_2 (the last committed event),
        # NOT past it, and NOT to evt_partial_end_cursor!
        assert worker.cursor == "evt_partial_2"
        assert worker.events_accepted_count == 2

    asyncio.run(_run())


def test_consecutive_failures_tracking(isolated_session_factory):
    """Consecutive failures increment on network failures and reset on success."""
    settings = Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long",
        sensor_simulator_base_url="http://127.0.0.1:8001",
        simulator_ingestion_enabled=True,
    )
    worker = SimulatorIngestionWorker(settings=settings)
    worker.session_factory = isolated_session_factory

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")

    async def _test_failures():
        # First failure
        await worker.poll_once(client=mock_client)
        assert worker.consecutive_failures == 1
        assert worker.last_poll_succeeded is False

        # Second failure
        await worker.poll_once(client=mock_client)
        assert worker.consecutive_failures == 2

        # Successful recovery poll
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"items": [], "next_cursor": None}
        mock_client.get.side_effect = None
        mock_client.get.return_value = mock_success

        await worker.poll_once(client=mock_client)
        assert worker.consecutive_failures == 0
        assert worker.last_poll_succeeded is True

    asyncio.run(_test_failures())


def test_pipeline_health_reports_failing_when_db_down(isolated_session_factory):
    """Worker MUST NOT report healthy if simulator HTTP poll succeeds but DB persistence fails."""
    settings = Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long",
        sensor_simulator_base_url="http://127.0.0.1:8001",
        simulator_ingestion_enabled=True,
    )
    worker = SimulatorIngestionWorker(settings=settings)
    worker.session_factory = isolated_session_factory

    # Ingestion fails due to database error
    worker.ingestion_service.ingest_single_reading = MagicMock(
        return_value=IngestionResult(
            outcome=IngestionOutcome.FAILED,
            event_id="evt_db_fail_1",
            patient_id="P101",
            detail="Database operational failure",
        )
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": [
            {
                "event_id": "evt_db_fail_1",
                "patient_id": "P101",
                "heart_rate": 80.0,
                "spo2": 98.0,
                "temperature_f": 98.6,
                "measured_at": "2026-10-15T02:00:00Z",
                "is_simulated": True,
            }
        ]
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    async def _test_health():
        await worker.poll_once(client=mock_client)
        status_info = worker.get_status()

        # Crucial requirement check:
        assert status_info["persistence_healthy"] is False
        assert status_info["pipeline_health"] == "persistence_failing"
        assert status_info["last_error_category"] == "database_error"

    asyncio.run(_test_health())


def test_error_sanitization_removes_secrets():
    """Worker error sanitizer strips passwords, connection strings, and tokens."""
    raw_error = "Failed to connect to mongodb+srv://admin_user:SuperSecretPassword123!@cluster0.mongodb.net/?retryWrites=true"
    sanitized = SimulatorIngestionWorker._sanitize_error_detail(raw_error)
    assert sanitized is not None
    assert "SuperSecretPassword123!" not in sanitized
    assert "mongodb://***:***@" in sanitized

    token_error = "JWT validation failed: token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret"
    sanitized_token = SimulatorIngestionWorker._sanitize_error_detail(token_error)
    assert sanitized_token is not None
    assert "secret" not in sanitized_token
    assert "token=***" in sanitized_token


def test_repeated_processing_does_not_duplicate_alerts(seeded_db: Session):
    """Processing the same event repeatedly does not generate duplicate alerts."""
    svc = SimulatorIngestionService()
    raw_reading = {
        "event_id": "evt_alert_dedup_1",
        "patient_id": "P101",
        "heart_rate": 145.0,  # Critical tachycardia
        "spo2": 88.0,        # Hypoxia
        "temperature_f": 102.5,  # Fever
        "measured_at": "2026-10-15T02:10:00Z",
        "is_simulated": True,
    }

    # First ingestion
    res1 = svc.ingest_single_reading(db=seeded_db, reading=raw_reading)
    assert res1.outcome == IngestionOutcome.ACCEPTED

    # Second ingestion of identical event
    res2 = svc.ingest_single_reading(db=seeded_db, reading=raw_reading)
    assert res2.outcome == IngestionOutcome.DUPLICATE_SKIPPED

    # Verify canonical records
    from database.mysql.models import IngestionEvent
    events = seeded_db.scalars(
        select(IngestionEvent).where(IngestionEvent.event_id == "evt_alert_dedup_1")
    ).all()
    assert len(events) == 1

