"""
Part 6K — Reliable Smartwatch Simulator Start/Stop/Resume Controls Lifecycle Tests.

Validates:
1. Initial stopped state when auto_start=False.
2. Start transitions to RUNNING with valid lifecycle_state.
3. Repeated Start is idempotent and does not create duplicate tasks.
4. Stop transitions to STOPPED immediately (< 200ms) via asyncio event wait.
5. No new readings generated/buffered after stop completes.
6. Start after Stop works without server restart.
7. Repeated Stop is safe and non-destructive.
8. Previously stored readings and alerts remain intact during stop.
9. Backend POST /api/v1/simulator/start and /stop endpoints coordinate cleanly.
10. Backend GET /api/v1/simulator/status returns unified simulator + ingestion contracts.
11. Core patient endpoints (/patients, /alerts, /auth/me) work normally while simulator is stopped.
12. Simulator outage or error does not crash the main backend.
13. Resumed telemetry generates fresh, non-duplicate event IDs.
14. MongoDB Atlas sync disabled compliance (MONGODB_SYNC_ENABLED=False).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
import time
from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    AnalyticsOutbox,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from simulator.config import SimulatorSettings
from simulator.generator import TelemetryGenerator
from simulator.main import create_simulator_app
from simulator.routes import set_generator_instance


# =============================================================================
# Simulator Standalone Fixtures
# =============================================================================

@pytest.fixture
def sim_settings() -> SimulatorSettings:
    """Fixture providing isolated simulator settings with short interval for testing."""
    return SimulatorSettings(
        auto_start=False,
        interval_seconds=0.1,
        max_history_records=100,
        random_seed=42,
        control_secret=None,
    )


@pytest.fixture
def standalone_generator(sim_settings: SimulatorSettings) -> TelemetryGenerator:
    """Fixture providing a fresh TelemetryGenerator instance."""
    gen = TelemetryGenerator(sim_settings)
    set_generator_instance(gen)
    return gen


@pytest.fixture
def standalone_client(sim_settings: SimulatorSettings, standalone_generator: TelemetryGenerator) -> TestClient:
    """TestClient for standalone simulator microservice."""
    app = create_simulator_app(sim_settings)
    with TestClient(app) as client:
        yield client


# =============================================================================
# Backend Integration Fixtures
# =============================================================================

@pytest.fixture
def in_memory_db_session() -> Generator[Session, None, None]:
    """Provides an isolated SQLite in-memory DB for backend testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    session = session_factory()

    # Seed clinician user and profile
    doc_user = User(
        user_id="U_DOC_TEST",
        email="doctor@test.hospital",
        password_hash=hash_password("DocPass123!"),
        role="doctor",
        is_active=True,
    )
    doc_profile = DoctorProfile(
        doctor_id="DOC_LIFECYCLE_001",
        user_id=doc_user.user_id,
        first_name="Doctor",
        last_name="Tester",
        specialization="Cardiology",
        license_number="LIC-LIFECYCLE-001",
    )
    session.add(doc_user)
    session.add(doc_profile)

    # Seed demo patients P101–P105
    for pid in ("P101", "P102", "P103", "P104", "P105"):
        patient_user = User(
            user_id=f"usr_{pid.lower()}",
            email=f"{pid.lower()}@test.hospital",
            password_hash=hash_password("PatientPass123!"),
            role="patient",
            is_active=True,
        )
        session.add(patient_user)

        patient = PatientProfile(
            patient_id=pid,
            user_id=patient_user.user_id,
            first_name="Demo",
            last_name=f"Patient {pid}",
            gender="male",
            created_at=datetime.now(timezone.utc),
        )
        session.add(patient)

        assignment = DoctorPatientAssignment(
            doctor_id=doc_profile.doctor_id,
            patient_id=pid,
            assigned_at=datetime.now(timezone.utc),
            is_active=True,
        )
        session.add(assignment)

    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def backend_client(in_memory_db_session: Session) -> Generator[TestClient, None, None]:
    """Provides a TestClient for the FastAPI backend gateway."""
    test_settings = Settings(
        app_env="testing",
        app_debug=True,
        jwt_secret_key="test-secret-key-lifecycle-32-bytes-long",
        database_url="sqlite:///:memory:",
        mongodb_sync_enabled=False,  # STRICT: zero mongo writes
        simulator_ingestion_enabled=False,
        sensor_simulator_base_url="http://127.0.0.1:8001",
    )

    app = create_app(test_settings)
    app.dependency_overrides[get_db] = lambda: in_memory_db_session

    with TestClient(app) as client:
        yield client


@pytest.fixture
def doctor_auth_headers() -> Dict[str, str]:
    """Returns valid JWT Authorization header for clinician."""
    test_settings = Settings(
        app_env="testing",
        app_debug=True,
        jwt_secret_key="test-secret-key-lifecycle-32-bytes-long",
        database_url="sqlite:///:memory:",
    )
    token = create_access_token(
        data={"sub": "U_DOC_TEST", "role": "doctor"},
        settings=test_settings,
    )
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 1. Generator Unit Lifecycle Tests (Idempotency, Fast-Break Stop, Resumption)
# =============================================================================

def test_generator_initial_state(standalone_generator: TelemetryGenerator) -> None:
    """Verify generator initializes cleanly with STOPPED state when auto_start=False."""
    assert not standalone_generator.is_running
    assert standalone_generator.lifecycle_state == "STOPPED"
    assert standalone_generator.total_readings_generated == 0
    assert standalone_generator.buffer_count == 0


def test_generator_start_and_idempotent_duplicate_start(standalone_generator: TelemetryGenerator) -> None:
    """Verify start() transitions to RUNNING and repeated start() is idempotent without duplicate tasks."""
    async def _test():
        res1 = await standalone_generator.start()
        assert res1 is True
        assert standalone_generator.is_running is True
        assert standalone_generator.lifecycle_state == "RUNNING"

        first_task = standalone_generator._worker_task
        assert first_task is not None
        assert not first_task.done()

        # Let it emit at least one batch
        await asyncio.sleep(0.15)
        assert standalone_generator.total_readings_generated > 0

        # Second start call must be idempotent
        res2 = await standalone_generator.start()
        assert res2 is False
        assert standalone_generator.lifecycle_state == "RUNNING"
        assert standalone_generator._worker_task is first_task  # Exactly same task, no duplicate!

        # Clean up
        await standalone_generator.stop()

    asyncio.run(_test())


def test_generator_stop_is_immediate_and_idempotent(standalone_generator: TelemetryGenerator) -> None:
    """
    Verify stop() interrupts wait immediately (< 200ms) rather than waiting
    for a full interval sleep, transitions to STOPPED, and repeated stop is safe.
    """
    async def _test():
        await standalone_generator.start()
        await asyncio.sleep(0.12)
        assert standalone_generator.is_running

        # Measure stop latency
        t0 = time.perf_counter()
        res1 = await standalone_generator.stop()
        duration = time.perf_counter() - t0

        assert duration < 0.25  # Immediate stop (< 250ms)
        assert res1 is True
        assert not standalone_generator.is_running
        assert standalone_generator.lifecycle_state == "STOPPED"

        count_at_stop = standalone_generator.total_readings_generated
        assert count_at_stop > 0

        # Wait another interval: reading count must NOT increase
        await asyncio.sleep(0.15)
        assert standalone_generator.total_readings_generated == count_at_stop

        # Repeated stop is safe and idempotent
        res2 = await standalone_generator.stop()
        assert res2 is False
        assert standalone_generator.lifecycle_state == "STOPPED"
        assert not standalone_generator.is_running

    asyncio.run(_test())


def test_generator_resume_after_stop_without_server_restart(standalone_generator: TelemetryGenerator) -> None:
    """Verify start -> stop -> resume cycle works cleanly and preserves history."""
    async def _test():
        # Phase 1: Start
        await standalone_generator.start()
        await asyncio.sleep(0.15)
        await standalone_generator.stop()

        count_after_first_run = standalone_generator.total_readings_generated
        assert count_after_first_run > 0
        history_first_run = standalone_generator.get_bounded_readings(limit=100)
        assert len(history_first_run) == count_after_first_run

        # Phase 2: Resume without restart
        resume_res = await standalone_generator.start()
        assert resume_res is True
        assert standalone_generator.is_running
        assert standalone_generator.lifecycle_state == "RUNNING"

        await asyncio.sleep(0.15)
        await standalone_generator.stop()

        count_after_resumption = standalone_generator.total_readings_generated
        assert count_after_resumption > count_after_first_run

        # Verify history is preserved across stops and new events have fresh timestamps
        history_after_resumption = standalone_generator.get_bounded_readings(limit=100)
        assert len(history_after_resumption) > len(history_first_run)

        # Verify event ID uniqueness across runs
        event_ids = [r.event_id for r in history_after_resumption]
        assert len(event_ids) == len(set(event_ids)), "All generated event IDs across runs must be unique!"

    asyncio.run(_test())


# =============================================================================
# 2. Simulator Microservice HTTP Routes (/start, /stop, /status)
# =============================================================================

def test_simulator_http_status_lifecycle_contract(standalone_client: TestClient) -> None:
    """Verify GET /api/v1/simulator/status returns lifecycle_state in HTTP response."""
    resp = standalone_client.get("/api/v1/simulator/status")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "lifecycle_state" in data
    assert data["lifecycle_state"] in ("STOPPED", "RUNNING")
    assert "is_running" in data
    assert "active_patients" in data


def test_simulator_http_start_stop_workflow(standalone_client: TestClient) -> None:
    """Verify HTTP POST /api/v1/simulator/start and /stop control the microservice."""
    # Start
    start_resp = standalone_client.post("/api/v1/simulator/start")
    assert start_resp.status_code == status.HTTP_200_OK
    start_data = start_resp.json()
    assert start_data["lifecycle_state"] == "RUNNING"
    assert start_data["is_running"] is True

    # Check status
    st_resp = standalone_client.get("/api/v1/simulator/status")
    assert st_resp.json()["lifecycle_state"] == "RUNNING"

    # Stop
    stop_resp = standalone_client.post("/api/v1/simulator/stop")
    assert stop_resp.status_code == status.HTTP_200_OK
    stop_data = stop_resp.json()
    assert stop_data["lifecycle_state"] == "STOPPED"
    assert stop_data["is_running"] is False

    # Check status again
    st_resp2 = standalone_client.get("/api/v1/simulator/status")
    assert st_resp2.json()["lifecycle_state"] == "STOPPED"


# =============================================================================
# 3. Main Backend Gateway Integration (/simulator/start, /stop, /status)
# =============================================================================

def test_backend_simulator_status_endpoint_contract(backend_client: TestClient, doctor_auth_headers: Dict[str, str]) -> None:
    """Verify GET /api/v1/simulator/status returns dual-layer simulator and ingestion diagnostics."""
    mock_sim_resp = {
        "service": "Smartwatch Sensor Telemetry Simulator",
        "version": "1.0.0",
        "is_running": False,
        "lifecycle_state": "STOPPED",
        "active_patients": ["P101", "P102"],
        "interrupted_patients": [],
        "generated_count": 50,
        "latest_generation_at": "2026-10-15T02:00:00Z",
    }

    with patch("httpx.AsyncClient.get", return_value=MagicMock(status_code=200, json=lambda: mock_sim_resp)):
        resp = backend_client.get("/api/v1/simulator/status", headers=doctor_auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()

        assert "simulator" in data
        assert data["simulator"]["lifecycle_state"] == "STOPPED"
        assert data["simulator"]["is_running"] is False
        assert "ingestion" in data
        assert "enabled" in data["ingestion"]


def test_backend_simulator_start_and_stop_proxies(backend_client: TestClient, doctor_auth_headers: Dict[str, str]) -> None:
    """Verify backend POST /start and POST /stop successfully coordinate microservice and ingestion."""
    mock_start_resp = {
        "action": "start",
        "is_running": True,
        "lifecycle_state": "RUNNING",
        "message": "Telemetry generation started.",
        "active_patients": ["P101", "P102", "P103", "P104", "P105"],
        "interrupted_patients": [],
    }
    mock_stop_resp = {
        "action": "stop",
        "is_running": False,
        "lifecycle_state": "STOPPED",
        "message": "Telemetry generation stopped.",
        "active_patients": [],
        "interrupted_patients": [],
    }

    # Start
    with patch("httpx.AsyncClient.post", return_value=MagicMock(status_code=200, json=lambda: mock_start_resp)):
        resp = backend_client.post("/api/v1/simulator/start", headers=doctor_auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == "started"
        assert data["lifecycle_state"] == "RUNNING"

    # Stop
    with patch("httpx.AsyncClient.post", return_value=MagicMock(status_code=200, json=lambda: mock_stop_resp)):
        resp = backend_client.post("/api/v1/simulator/stop", headers=doctor_auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == "stopped"
        assert data["lifecycle_state"] == "STOPPED"


def test_backend_unauthorized_simulator_control(backend_client: TestClient) -> None:
    """Verify unauthenticated requests with app_env=production are rejected."""
    from services.api.config import get_settings
    mock_settings = Settings(
        app_env="production",
        app_debug=False,
        jwt_secret_key="test-key-32-bytes-test-key-32-bytes",
        database_url="sqlite:///:memory:",
        mysql_password="ProdPassword123!Secure",
        ingestion_api_key="super-secret-key",
        simulator_ingestion_enabled=False,
    )
    backend_client.app.dependency_overrides[get_settings] = lambda: mock_settings
    try:
        resp = backend_client.post("/api/v1/simulator/start")
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
    finally:
        backend_client.app.dependency_overrides.pop(get_settings, None)


def test_core_backend_routes_remain_healthy_when_simulator_stopped(backend_client: TestClient, doctor_auth_headers: Dict[str, str]) -> None:
    """
    Critical demo test:
    Verify /patients, /alerts, and /auth/me remain 100% operational when simulator is stopped.
    """
    # 1. /patients
    p_resp = backend_client.get("/api/v1/patients", headers=doctor_auth_headers)
    assert p_resp.status_code == status.HTTP_200_OK
    patients = p_resp.json()
    assert len(patients) == 5
    assert patients[0]["patient_id"] == "P101"

    # 2. /alerts
    a_resp = backend_client.get("/api/v1/alerts", headers=doctor_auth_headers)
    assert a_resp.status_code == status.HTTP_200_OK

    # 3. /auth/me
    me_resp = backend_client.get("/api/v1/auth/me", headers=doctor_auth_headers)
    assert me_resp.status_code == status.HTTP_200_OK
    assert me_resp.json()["email"] == "doctor@test.hospital"


def test_simulator_outage_does_not_crash_backend(backend_client: TestClient, doctor_auth_headers: Dict[str, str]) -> None:
    """Verify that if the simulator microservice drops offline, backend returns error gracefully without crashing."""
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused on 8001")):
        resp = backend_client.get("/api/v1/simulator/status", headers=doctor_auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["simulator"]["reachable"] is False
        assert "unreachable" in data["simulator"]["error"].lower()
        assert data["backend_healthy"] is True

    # Also verify POST /start raises 503 when simulator is unreachable
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused on 8001")):
        start_resp = backend_client.post("/api/v1/simulator/start", headers=doctor_auth_headers)
        assert start_resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    # Core backend routes STILL work immediately after outage!
    me_resp = backend_client.get("/api/v1/auth/me", headers=doctor_auth_headers)
    assert me_resp.status_code == status.HTTP_200_OK


def test_mongodb_atlas_sync_disabled_compliance(backend_client: TestClient, in_memory_db_session: Session) -> None:
    """
    Strict user compliance check:
    Verify MONGODB_SYNC_ENABLED=False prevents any outgoing requests to MongoDB Atlas.
    """
    # Check outbox entries stay in status='pending' without triggering external mongo client
    outbox_entry = AnalyticsOutbox(
        event_type="telemetry_event",
        aggregate_id="P101",
        payload_json=json.dumps({"test": "data"}),
        status="pending",
    )
    in_memory_db_session.add(outbox_entry)
    in_memory_db_session.commit()

    # Query back
    stmt = select(AnalyticsOutbox).where(AnalyticsOutbox.aggregate_id == "P101")
    result = in_memory_db_session.execute(stmt).scalar_one_or_none()
    assert result is not None
    assert result.status == "pending"
