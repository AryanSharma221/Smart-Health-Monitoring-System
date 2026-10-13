"""
Unit and Integration Tests for Patient Health Readings API.

Verifies:
1. Patient ownership authorization (patient can view only their own records).
2. Clinician care assignment authorization (assigned doctor allowed, unassigned doctor denied).
3. Unauthenticated request rejection (401 Unauthorized).
4. Time-range filtering (inclusive start/end timestamps).
5. Reversed time-range rejection (start_time > end_time -> 400 Bad Request).
6. Pagination enforcement (page, page_size, total_count, total_pages, le=100 cap).
7. Deterministic sorting (measured_at DESC with event_id DESC tie-breaker).
8. Empty history handling (clean empty items list, total_count=0).
9. Response schema safety (omits internal database IDs, secrets, passwords).
10. Preservation of source units (bpm, %, °F raw, °C canonical) and provenance (kaggle vs. simulator).
11. Latest reading query (newest record selection, 404 when no readings exist).
12. Protection against SQL injection in query parameters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
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


# =============================================================================
# Test Fixtures (Isolated In-Memory SQLite Database with StaticPool)
# =============================================================================

@pytest.fixture(scope="function")
def test_settings() -> Settings:
    """Isolated test settings with dedicated JWT test secret."""
    return Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long_for_security!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
    )


@pytest.fixture(scope="function")
def test_db_session() -> Generator[Session, None, None]:
    """In-memory SQLite session with StaticPool for cross-thread test isolation."""
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
def client(test_db_session: Session, test_settings: Settings) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with injected session and configuration."""
    app = create_app(settings=test_settings)

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# Helper: Seed Test Patients, Doctors, and Telemetry Events
# =============================================================================

def seed_environment(session: Session, test_settings: Settings) -> dict:
    """Seeds test data: 2 patients, 2 doctors (1 assigned, 1 unassigned), and readings."""
    # 1. Patient 1 (P101)
    u_p1 = User(
        user_id="usr_p101",
        email="p101@test.local",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="patient",
        is_active=True,
    )
    prof_p1 = PatientProfile(
        patient_id="P101",
        user_id="usr_p101",
        first_name="Alice",
        last_name="Patient",
    )

    # 2. Patient 2 (P102 - with NO readings)
    u_p2 = User(
        user_id="usr_p102",
        email="p102@test.local",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="patient",
        is_active=True,
    )
    prof_p2 = PatientProfile(
        patient_id="P102",
        user_id="usr_p102",
        first_name="Bob",
        last_name="Patient",
    )

    # 3. Doctor 1 (DOC-001 - assigned to P101)
    u_d1 = User(
        user_id="usr_doc1",
        email="doc1@hospital.org",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="doctor",
        is_active=True,
    )
    prof_d1 = DoctorProfile(
        doctor_id="DOC-001",
        user_id="usr_doc1",
        first_name="Carol",
        last_name="Doctor",
        specialization="Cardiology",
        license_number="MD-001",
    )
    assignment = DoctorPatientAssignment(
        doctor_id="DOC-001",
        patient_id="P101",
        is_active=True,
    )

    # 4. Doctor 2 (DOC-002 - unassigned)
    u_d2 = User(
        user_id="usr_doc2",
        email="doc2@hospital.org",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="doctor",
        is_active=True,
    )
    prof_d2 = DoctorProfile(
        doctor_id="DOC-002",
        user_id="usr_doc2",
        first_name="Dave",
        last_name="Doctor",
        specialization="Internal Medicine",
        license_number="MD-002",
    )

    session.add_all([u_p1, prof_p1, u_p2, prof_p2, u_d1, prof_d1, assignment, u_d2, prof_d2])
    session.commit()

    # 5. Telemetry Readings for P101 (3 distinct timestamp events)
    base_time = datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc)

    # Event 1 (Oldest: 10:00)
    e1 = IngestionEvent(
        event_id="evt_001",
        patient_id="P101",
        source="kaggle",
        source_event_id="kag_001",
        measured_at=base_time,
        is_simulated=False,
    )
    r1_hr = VitalsReading(
        event_id="evt_001",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("72.00"),
        unit="bpm",
        raw_value=Decimal("72.00"),
        raw_unit="bpm",
        measured_at=base_time,
    )
    r1_sp = VitalsReading(
        event_id="evt_001",
        patient_id="P101",
        metric_code="spo2",
        value=Decimal("98.50"),
        unit="%",
        raw_value=Decimal("98.50"),
        raw_unit="%",
        measured_at=base_time,
    )
    r1_temp = VitalsReading(
        event_id="evt_001",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("37.00"),
        unit="degC",
        raw_value=Decimal("98.60"),
        raw_unit="degF",
        measured_at=base_time,
    )

    # Event 2 (Middle: 10:30)
    time_2 = base_time + timedelta(minutes=30)
    e2 = IngestionEvent(
        event_id="evt_002",
        patient_id="P101",
        source="kaggle",
        source_event_id="kag_002",
        measured_at=time_2,
        is_simulated=False,
    )
    r2_hr = VitalsReading(
        event_id="evt_002",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("78.00"),
        unit="bpm",
        raw_value=Decimal("78.00"),
        raw_unit="bpm",
        measured_at=time_2,
    )
    r2_sp = VitalsReading(
        event_id="evt_002",
        patient_id="P101",
        metric_code="spo2",
        value=Decimal("97.00"),
        unit="%",
        raw_value=Decimal("97.00"),
        raw_unit="%",
        measured_at=time_2,
    )
    r2_temp = VitalsReading(
        event_id="evt_002",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("37.22"),
        unit="degC",
        raw_value=Decimal("99.00"),
        raw_unit="degF",
        measured_at=time_2,
    )

    # Event 3 (Newest: 11:00 - Simulated record)
    time_3 = base_time + timedelta(minutes=60)
    e3 = IngestionEvent(
        event_id="evt_003",
        patient_id="P101",
        source="simulator",
        source_event_id="sim_001",
        measured_at=time_3,
        is_simulated=True,
    )
    r3_hr = VitalsReading(
        event_id="evt_003",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("85.00"),
        unit="bpm",
        raw_value=Decimal("85.00"),
        raw_unit="bpm",
        measured_at=time_3,
    )
    r3_sp = VitalsReading(
        event_id="evt_003",
        patient_id="P101",
        metric_code="spo2",
        value=Decimal("96.00"),
        unit="%",
        raw_value=Decimal("96.00"),
        raw_unit="%",
        measured_at=time_3,
    )
    r3_temp = VitalsReading(
        event_id="evt_003",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("37.50"),
        unit="degC",
        raw_value=Decimal("99.50"),
        raw_unit="degF",
        measured_at=time_3,
    )

    # Event 4 (Identical timestamp tie-breaker test: also 11:00 but different event_id)
    e4 = IngestionEvent(
        event_id="evt_004_tie",
        patient_id="P101",
        source="simulator",
        source_event_id="sim_002",
        measured_at=time_3,
        is_simulated=True,
    )
    r4_hr = VitalsReading(
        event_id="evt_004_tie",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("86.00"),
        unit="bpm",
        raw_value=Decimal("86.00"),
        raw_unit="bpm",
        measured_at=time_3,
    )

    session.add_all([e1, r1_hr, r1_sp, r1_temp, e2, r2_hr, r2_sp, r2_temp, e3, r3_hr, r3_sp, r3_temp, e4, r4_hr])
    session.commit()

    # Generate JWT tokens
    p1_token = create_access_token({"sub": "usr_p101", "role": "patient"}, settings=test_settings)
    p2_token = create_access_token({"sub": "usr_p102", "role": "patient"}, settings=test_settings)
    d1_token = create_access_token({"sub": "usr_doc1", "role": "doctor"}, settings=test_settings)
    d2_token = create_access_token({"sub": "usr_doc2", "role": "doctor"}, settings=test_settings)

    return {
        "p1_token": p1_token,
        "p2_token": p2_token,
        "d1_token": d1_token,
        "d2_token": d2_token,
        "base_time": base_time,
    }


# =============================================================================
# 1. Authorization Tests (Scenarios 1-5, 16)
# =============================================================================

def test_authorized_patient_retrieves_own_readings(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 1: Authorized patient P101 successfully retrieves their readings."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["total_count"] == 4
    assert len(body["items"]) == 4


def test_patient_cannot_retrieve_another_patient_readings(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 2: Patient P102 attempting to access P101 receives 403 Forbidden."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings",
        headers={"Authorization": f"Bearer {data['p2_token']}"},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "only access your own" in resp.json()["detail"].lower()


def test_assigned_clinician_retrieves_authorized_patient_readings(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 3: Assigned doctor DOC-001 can access P101 readings."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings",
        headers={"Authorization": f"Bearer {data['d1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["total_count"] == 4


def test_unassigned_clinician_is_denied_access(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 4: Unassigned doctor DOC-002 is denied access (403 Forbidden)."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings",
        headers={"Authorization": f"Bearer {data['d2_token']}"},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "not assigned" in resp.json()["detail"].lower()


def test_unauthenticated_requests_are_rejected(client: TestClient):
    """Scenario 5: Unauthenticated request rejected with 401 Unauthorized."""
    resp = client.get("/api/v1/patients/P101/readings")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_unauthorized_users_cannot_retrieve_latest_reading(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 16: Unauthorized patient and unassigned doctor cannot access latest reading."""
    data = seed_environment(test_db_session, test_settings)

    # Patient 2 accessing Patient 1's latest reading
    resp_p2 = client.get(
        "/api/v1/patients/P101/readings/latest",
        headers={"Authorization": f"Bearer {data['p2_token']}"},
    )
    assert resp_p2.status_code == status.HTTP_403_FORBIDDEN

    # Unassigned doctor accessing Patient 1's latest reading
    resp_d2 = client.get(
        "/api/v1/patients/P101/readings/latest",
        headers={"Authorization": f"Bearer {data['d2_token']}"},
    )
    assert resp_d2.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# 2. Time-Range Filtering Tests (Scenarios 6, 7)
# =============================================================================

def test_time_range_filters_return_expected_records(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 6: Start and end timestamp filters return inclusive subset."""
    data = seed_environment(test_db_session, test_settings)
    base_time = data["base_time"]

    # Filter exactly for Event 2 (10:15 to 10:45)
    t_start = (base_time + timedelta(minutes=15)).isoformat()
    t_end = (base_time + timedelta(minutes=45)).isoformat()

    resp = client.get(
        "/api/v1/patients/P101/readings",
        params={"start_time": t_start, "end_time": t_end},
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["total_count"] == 1
    assert body["items"][0]["event_id"] == "evt_002"
    assert body["items"][0]["heart_rate"] == 78.0


def test_invalid_or_reversed_time_ranges_are_rejected(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 7: start_time > end_time is rejected with 400 Bad Request."""
    data = seed_environment(test_db_session, test_settings)
    base_time = data["base_time"]

    t_start = (base_time + timedelta(hours=2)).isoformat()
    t_end = base_time.isoformat()

    resp = client.get(
        "/api/v1/patients/P101/readings",
        params={"start_time": t_start, "end_time": t_end},
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "cannot be later than end_time" in resp.json()["detail"].lower()


# =============================================================================
# 3. Pagination & Deterministic Sorting Tests (Scenarios 8, 9, 10)
# =============================================================================

def test_pagination_respects_page_size_limits(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 8: Pagination bounds items, computes total_pages, and rejects page_size > 100."""
    data = seed_environment(test_db_session, test_settings)

    # Page 1 with page_size=2
    resp_p1 = client.get(
        "/api/v1/patients/P101/readings?page=1&page_size=2",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp_p1.status_code == status.HTTP_200_OK
    b1 = resp_p1.json()
    assert b1["page"] == 1
    assert b1["page_size"] == 2
    assert b1["total_count"] == 4
    assert b1["total_pages"] == 2
    assert b1["has_next"] is True
    assert b1["has_previous"] is False
    assert len(b1["items"]) == 2

    # Page 2 with page_size=2
    resp_p2 = client.get(
        "/api/v1/patients/P101/readings?page=2&page_size=2",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp_p2.status_code == status.HTTP_200_OK
    b2 = resp_p2.json()
    assert b2["page"] == 2
    assert b2["has_next"] is False
    assert b2["has_previous"] is True
    assert len(b2["items"]) == 2

    # Enforce maximum page size limit (page_size > 100 rejected)
    resp_oversize = client.get(
        "/api/v1/patients/P101/readings?page=1&page_size=101",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp_oversize.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_ordering_is_deterministic_when_timestamps_match(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 9: Events with identical timestamps are stably ordered by event_id DESC."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings?page=1&page_size=10",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]

    # First two items have identical measured_at (11:00)
    assert items[0]["measured_at"] == items[1]["measured_at"]
    # Tie-breaker on event_id DESC: evt_004_tie > evt_003
    assert items[0]["event_id"] == "evt_004_tie"
    assert items[1]["event_id"] == "evt_003"


def test_empty_history_returns_documented_response(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 10: Patient P102 with zero readings returns empty items list and total_count=0."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P102/readings",
        headers={"Authorization": f"Bearer {data['p2_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["items"] == []
    assert body["total_count"] == 0
    assert body["total_pages"] == 0
    assert body["has_next"] is False
    assert body["has_previous"] is False


# =============================================================================
# 4. Response Schemas, Units, and Provenance Tests (Scenarios 11, 12)
# =============================================================================

def test_responses_contain_only_permitted_fields(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 11: Responses omit internal DB primary keys, user tables, and secrets."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    item = resp.json()["items"][0]

    expected_keys = {
        "event_id",
        "patient_id",
        "measured_at",
        "source",
        "is_simulated",
        "heart_rate",
        "spo2",
        "temperature_f",
        "temperature_c",
    }
    assert set(item.keys()) == expected_keys

    # Ensure no secrets or internal SQLAlchemy artifacts leak
    forbidden_substrings = ["password", "secret", "hash", "user_id"]
    for k in item.keys():
        for f in forbidden_substrings:
            assert f not in k.lower()


def test_units_and_source_provenance_preserved(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 12: Kaggle historical records preserve raw Fahrenheit and differentiate from simulator."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    items = {i["event_id"]: i for i in resp.json()["items"]}

    # Kaggle event (evt_001):
    kag_item = items["evt_001"]
    assert kag_item["source"] == "kaggle"
    assert kag_item["is_simulated"] is False
    assert kag_item["heart_rate"] == 72.0
    assert kag_item["spo2"] == 98.5
    assert kag_item["temperature_f"] == 98.6  # Raw Fahrenheit from Kaggle
    assert kag_item["temperature_c"] == 37.0  # Canonical Celsius

    # Simulator event (evt_003):
    sim_item = items["evt_003"]
    assert sim_item["source"] == "simulator"
    assert sim_item["is_simulated"] is True


# =============================================================================
# 5. Latest Reading Tests (Scenarios 13, 14, 15)
# =============================================================================

def test_newest_record_is_selected_correctly(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 13 & 14: Newest record is returned with deterministic tie-breaking."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P101/readings/latest",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    # At 11:00, evt_004_tie has higher tie-breaker than evt_003
    assert body["event_id"] == "evt_004_tie"
    assert body["patient_id"] == "P101"
    assert body["heart_rate"] == 86.0


def test_patient_without_readings_receives_404(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 15: Patient P102 without readings receives 404 Not Found."""
    data = seed_environment(test_db_session, test_settings)

    resp = client.get(
        "/api/v1/patients/P102/readings/latest",
        headers={"Authorization": f"Bearer {data['p2_token']}"},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "no readings found" in resp.json()["detail"].lower()


# =============================================================================
# 6. Reliability & Security Tests (Scenarios 18-21)
# =============================================================================

def test_query_parameters_cannot_inject_sql(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Scenario 20: SQL injection payload in query parameters safely handled/rejected."""
    data = seed_environment(test_db_session, test_settings)

    sql_payload = "' OR 1=1 --"
    resp = client.get(
        f"/api/v1/patients/P101/readings?source={sql_payload}",
        headers={"Authorization": f"Bearer {data['p1_token']}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["total_count"] == 0  # No records match the literal injection string
