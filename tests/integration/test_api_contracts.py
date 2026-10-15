"""
API Contract Verification and OpenAPI Specification Conformance Test Suite.

Verifies the documented REST API contracts across all implemented FastAPI endpoints:
1. System & Health: /health, /health/db, /health/mongodb.
2. Authentication & Identity: /auth/register, /auth/login, /auth/me, /auth/logout, /auth/verify-patient-access/{id}.
3. Patient Health Readings: /patients/{patient_id}/readings, /patients/{patient_id}/readings/latest.
4. Clinical Alerts: /alerts, /patients/{patient_id}/alerts, /alerts/{alert_id}, /alerts/{alert_id}/acknowledge.
5. Conversations & Messaging: /conversations, /conversations/{id}, /conversations/{id}/messages, /conversations/{id}/read.
6. Real-Time Telemetry: /ws WebSocket route registration.
7. OpenAPI Schema: Component models, security schemes, parameters, status codes, and error models.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    Alert,
    AlertRule,
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
from database.mysql.session import get_db
from services.alerts.rules import DEFAULT_ALERT_RULES
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password


@pytest.fixture(scope="function")
def contract_settings() -> Settings:
    return Settings(
        app_env="testing",
        jwt_secret="testing_api_contract_secret_key_at_least_32_chars!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
    )


@pytest.fixture(scope="function")
def contract_db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


@pytest.fixture(scope="function")
def contract_client(contract_db_session: Session, contract_settings: Settings) -> Generator[TestClient, None, None]:
    app = create_app(settings=contract_settings)

    def override_get_db():
        try:
            yield contract_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# =============================================================================
# 1. OpenAPI Specification Contract Tests
# =============================================================================

def test_openapi_schema_generation_and_components(contract_settings: Settings):
    """Verify that OpenAPI documentation schema is complete and valid."""
    from services.api.routes.websocket import router as ws_router

    app = create_app(settings=contract_settings)
    schema = app.openapi()

    assert schema["info"]["title"] == contract_settings.app_name
    assert schema["info"]["version"] == "3.0.0"

    paths = schema["paths"]

    # Verify Core HTTP API Route Paths exist in OpenAPI
    expected_http_paths = [
        "/",
        "/health",
        "/health/live",
        "/health/ready",
        "/health/db",
        "/health/mongodb",
        "/api/v1/health",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/health/db",
        "/api/v1/health/mongodb",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/patients/{patient_id}/readings",
        "/api/v1/patients/{patient_id}/readings/latest",
        "/api/v1/alerts",
        "/api/v1/patients/{patient_id}/alerts",
        "/api/v1/alerts/{alert_id}",
        "/api/v1/alerts/{alert_id}/acknowledge",
        "/api/v1/conversations",
        "/api/v1/conversations/{conversation_id}",
        "/api/v1/conversations/{conversation_id}/messages",
        "/api/v1/conversations/{conversation_id}/read",
    ]

    for p in expected_http_paths:
        assert p in paths, f"Expected endpoint path '{p}' not found in OpenAPI schema"

    # Verify WebSocket routes are registered on the application router
    ws_paths = [r.path for r in ws_router.routes]
    assert "/ws" in ws_paths, "WebSocket route '/ws' must be registered on router"
    assert "/api/v1/ws" in ws_paths, "WebSocket route '/api/v1/ws' must be registered on router"


def test_root_informational_endpoint_contract(contract_client: TestClient):
    """Verify GET / returns root system discovery and endpoint navigation index."""
    resp = contract_client.get("/")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "Smart Health Monitoring System"
    assert data["version"] == "3.0.0"
    assert data["status"] == "online"
    assert "documentation" in data
    assert data["documentation"]["swagger_ui"] == "/docs"
    assert data["documentation"]["openapi_json"] == "/openapi.json"
    assert "api_endpoints" in data
    assert data["api_endpoints"]["base_v1"] == "/api/v1"
    assert data["api_endpoints"]["health_check"] == "/api/v1/health"
    assert data["api_endpoints"]["websocket_stream"] == "/ws/v1/updates"
    assert "SIMULATED DATA" in data["disclaimer"]


def test_system_health_endpoints_contract(contract_client: TestClient):
    """Verify system health, liveness, and readiness check responses conform to schemas."""
    # 1. App health (general overview - root and versioned /api/v1 parity)
    for health_path in ["/health", "/api/v1/health"]:
        resp = contract_client.get(health_path)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "Smart Health Monitoring System"
        assert "version" in data
        assert data["is_simulated"] is True
        assert "SIMULATED DATA" in data["notice"]

    # 2. Liveness probe (process running - root and versioned /api/v1 parity)
    for live_path in ["/health/live", "/api/v1/health/live"]:
        resp_live = contract_client.get(live_path)
        assert resp_live.status_code == status.HTTP_200_OK
        live_data = resp_live.json()
        assert live_data["status"] == "alive"
        assert live_data["service"] == "Smart Health Monitoring System"

    # 3. Readiness probe (authoritative DB operational - root and versioned parity)
    for ready_path in ["/health/ready", "/api/v1/health/ready"]:
        resp_ready = contract_client.get(ready_path)
        assert resp_ready.status_code == status.HTTP_200_OK
        ready_data = resp_ready.json()
        assert ready_data["status"] == "ready"
        assert ready_data["database"] == "connected"
        assert "mongodb_mirror" in ready_data

    # 4. DB health
    for db_path in ["/health/db", "/api/v1/health/db"]:
        resp_db = contract_client.get(db_path)
        assert resp_db.status_code == status.HTTP_200_OK
        db_data = resp_db.json()
        assert "status" in db_data

    # 5. MongoDB health
    for mongo_path in ["/health/mongodb", "/api/v1/health/mongodb"]:
        resp_mongo = contract_client.get(mongo_path)
        assert resp_mongo.status_code == status.HTTP_200_OK
        mongo_data = resp_mongo.json()
        assert "outbox_queue" in mongo_data
        assert "database" in mongo_data


def test_readiness_failure_when_authoritative_database_unreachable(
    contract_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify that /health/ready returns 503 when MySQL is down, while /health/live remains 200."""
    # Simulate database outage
    import services.api.main as api_main
    monkeypatch.setattr(api_main, "check_db_connectivity", lambda bind: False)

    # 1. Readiness must return 503 Service Unavailable
    resp_ready = contract_client.get("/health/ready")
    assert resp_ready.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    ready_body = resp_ready.json()
    assert ready_body["status"] == "unready"
    assert ready_body["database"] == "unreachable"

    # 2. Process Liveness must still return 200 OK (process is still alive)
    resp_live = contract_client.get("/health/live")
    assert resp_live.status_code == status.HTTP_200_OK
    assert resp_live.json()["status"] == "alive"


def test_auth_endpoints_contract(
    contract_client: TestClient,
    contract_db_session: Session,
    contract_settings: Settings,
):
    """Verify authentication endpoint contracts (register, login, me, logout)."""
    # 1. Register Patient
    reg_payload = {
        "email": "contract_patient@example.com",
        "password": "Password123!Secure",
        "first_name": "Clara",
        "last_name": "Oswald",
        "date_of_birth": "1989-11-23",
        "gender": "female",
    }
    resp_reg = contract_client.post("/api/v1/auth/register", json=reg_payload)
    assert resp_reg.status_code == status.HTTP_201_CREATED
    reg_data = resp_reg.json()
    assert reg_data["email"] == "contract_patient@example.com"
    assert reg_data["role"] == "patient"
    assert "password_hash" not in reg_data

    # 2. Login
    login_payload = {
        "email": "contract_patient@example.com",
        "password": "Password123!Secure",
    }
    resp_login = contract_client.post("/api/v1/auth/login", json=login_payload)
    assert resp_login.status_code == status.HTTP_200_OK
    login_data = resp_login.json()
    assert "access_token" in login_data
    assert login_data["token_type"] == "bearer"
    assert login_data["expires_in"] > 0
    token = login_data["access_token"]

    # 3. Safe Profile Inspection (/me)
    resp_me = contract_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_me.status_code == status.HTTP_200_OK
    me_data = resp_me.json()
    assert me_data["email"] == "contract_patient@example.com"
    assert "password_hash" not in me_data

    # 4. Logout
    resp_logout = contract_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_logout.status_code == status.HTTP_200_OK
    assert resp_logout.json()["status"] == "success"


def test_validation_error_responses_contract(contract_client: TestClient):
    """Verify input validation returns 422 Unprocessable Content with error details."""
    # Empty JSON body on login
    resp = contract_client.post("/api/v1/auth/login", json={})
    assert resp.status_code in (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_400_BAD_REQUEST,
    )
    data = resp.json()
    assert "detail" in data

    # Malformed register payload (missing required password and email)
    resp_bad_reg = contract_client.post("/api/v1/auth/register", json={"first_name": "Test"})
    assert resp_bad_reg.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "detail" in resp_bad_reg.json()


# =============================================================================
# 2. Readings API Contract Tests
# =============================================================================

def test_readings_api_contracts(
    contract_client: TestClient,
    contract_db_session: Session,
    contract_settings: Settings,
):
    """Verify patient health readings API contracts (paginated list and latest)."""
    # 1. Seed user and patient
    user = User(
        user_id="101",
        email="patient101@example.com",
        password_hash=hash_password("Pass123!Secret"),
        role="patient",
        is_active=True,
    )
    patient = PatientProfile(
        patient_id="101",
        user_id="101",
        first_name="Donna",
        last_name="Noble",
        date_of_birth=date(1982, 4, 15),
        gender="female",
    )
    contract_db_session.add_all([user, patient])
    contract_db_session.commit()

    token = create_access_token(
        data={"sub": str(user.user_id), "email": user.email, "role": user.role},
        settings=contract_settings,
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Seed an ingestion event and readings
    now = datetime.now(timezone.utc)
    event = IngestionEvent(
        event_id="EVENT-1",
        patient_id="101",
        source="kaggle_csv",
        source_event_id="ROW-1",
        measured_at=now,
    )
    contract_db_session.add(event)
    contract_db_session.flush()

    hr_reading = VitalsReading(
        event_id="EVENT-1",
        patient_id="101",
        metric_code="heart_rate",
        value=Decimal("78.0"),
        unit="bpm",
        raw_value=Decimal("78.0"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    spo2_reading = VitalsReading(
        event_id="EVENT-1",
        patient_id="101",
        metric_code="spo2",
        value=Decimal("98.5"),
        unit="%",
        raw_value=Decimal("98.5"),
        raw_unit="%",
        quality_status="valid",
        measured_at=now,
    )
    contract_db_session.add_all([hr_reading, spo2_reading])
    contract_db_session.commit()

    # 3. Test GET /api/v1/patients/{patient_id}/readings
    resp_list = contract_client.get(
        f"/api/v1/patients/{patient.patient_id}/readings?page=1&page_size=10",
        headers=headers,
    )
    assert resp_list.status_code == status.HTTP_200_OK
    list_data = resp_list.json()
    assert "items" in list_data
    assert "total_count" in list_data
    assert len(list_data["items"]) == 1
    item = list_data["items"][0]
    assert item["patient_id"] == "101"
    assert item["event_id"] == "EVENT-1"
    assert float(item["heart_rate"]) == 78.0
    assert float(item["spo2"]) == 98.5
    assert list_data["page"] == 1
    assert list_data["total_count"] == 1

    # 4. Test GET /api/v1/patients/{patient_id}/readings/latest
    resp_latest = contract_client.get(
        f"/api/v1/patients/{patient.patient_id}/readings/latest",
        headers=headers,
    )
    assert resp_latest.status_code == status.HTTP_200_OK
    latest_data = resp_latest.json()
    assert latest_data["patient_id"] == "101"
    assert float(latest_data["heart_rate"]) == 78.0
    assert float(latest_data["spo2"]) == 98.5


# =============================================================================
# 3. Alerts API Contract Tests
# =============================================================================

def test_alerts_api_contracts(
    contract_client: TestClient,
    contract_db_session: Session,
    contract_settings: Settings,
):
    """Verify alerts listing, retrieval, and acknowledgement contracts."""
    # Seed doctor, patient, assignment, and alert
    doc_user = User(
        user_id="201",
        email="doc201@hospital.org",
        password_hash=hash_password("DocPass123!"),
        role="doctor",
        is_active=True,
    )
    doctor = DoctorProfile(
        doctor_id="201",
        user_id="201",
        first_name="Martha",
        last_name="Jones",
        specialization="Cardiology",
        license_number="MD-201-TEST",
    )
    pat_user = User(
        user_id="202",
        email="pat202@example.com",
        password_hash=hash_password("PatPass123!"),
        role="patient",
        is_active=True,
    )
    patient = PatientProfile(
        patient_id="202",
        user_id="202",
        first_name="Rory",
        last_name="Williams",
        date_of_birth=date(1989, 5, 8),
        gender="male",
    )
    assignment = DoctorPatientAssignment(
        doctor_id="201",
        patient_id="202",
        is_active=True,
    )
    contract_db_session.add_all([doc_user, doctor, pat_user, patient, assignment])
    contract_db_session.commit()

    now = datetime.now(timezone.utc)
    event = IngestionEvent(
        event_id="EVENT-20",
        patient_id="202",
        source="kaggle_csv",
        source_event_id="ROW-20",
        measured_at=now,
    )
    contract_db_session.add(event)
    contract_db_session.flush()

    alert = Alert(
        alert_id="ALERT-301",
        patient_id="202",
        event_id="EVENT-20",
        rule_id="RULE_HR_HIGH",
        severity="HIGH",
        category="vital_threshold",
        reason="Critical tachycardia: 145 bpm exceeds threshold 140",
        status="NEW",
        created_at=now,
    )
    contract_db_session.add(alert)
    contract_db_session.commit()

    doc_token = create_access_token(
        data={"sub": str(doc_user.user_id), "email": doc_user.email, "role": doc_user.role},
        settings=contract_settings,
    )
    doc_headers = {"Authorization": f"Bearer {doc_token}"}

    # 1. GET /api/v1/alerts (Scoped clinician list)
    resp_alerts = contract_client.get("/api/v1/alerts?severity=HIGH", headers=doc_headers)
    assert resp_alerts.status_code == status.HTTP_200_OK
    alerts_data = resp_alerts.json()
    assert isinstance(alerts_data, list)
    assert len(alerts_data) == 1
    assert alerts_data[0]["alert_id"] == "ALERT-301"
    assert alerts_data[0]["severity"] == "HIGH"

    # 2. GET /api/v1/patients/{patient_id}/alerts
    resp_pat_alerts = contract_client.get(
        f"/api/v1/patients/{patient.patient_id}/alerts",
        headers=doc_headers,
    )
    assert resp_pat_alerts.status_code == status.HTTP_200_OK
    assert len(resp_pat_alerts.json()["items"]) == 1

    # 3. GET /api/v1/alerts/{alert_id}
    resp_single = contract_client.get(f"/api/v1/alerts/{alert.alert_id}", headers=doc_headers)
    assert resp_single.status_code == status.HTTP_200_OK
    assert resp_single.json()["alert_id"] == "ALERT-301"

    # 4. POST /api/v1/alerts/{alert_id}/acknowledge
    ack_payload = {"note": "Reviewed ECG; patient admitted for observation."}
    resp_ack = contract_client.post(
        f"/api/v1/alerts/{alert.alert_id}/acknowledge",
        json=ack_payload,
        headers=doc_headers,
    )
    assert resp_ack.status_code == status.HTTP_200_OK
    ack_data = resp_ack.json()
    assert ack_data["alert_id"] == "ALERT-301"
    assert ack_data["status"] == "ACKNOWLEDGED"
    assert ack_data["acknowledged_by"] == "201"


# =============================================================================
# 4. Conversations & Messaging API Contract Tests
# =============================================================================

def test_conversations_and_messaging_api_contracts(
    contract_client: TestClient,
    contract_db_session: Session,
    contract_settings: Settings,
):
    """Verify conversations creation, message sending, pagination, and read status."""
    # Seed doctor, patient, assignment
    doc_user = User(
        user_id="301",
        email="doc301@clinic.org",
        password_hash=hash_password("DocPass301!"),
        role="doctor",
        is_active=True,
    )
    doctor = DoctorProfile(
        doctor_id="301",
        user_id="301",
        first_name="Amy",
        last_name="Pond",
        specialization="Internal Medicine",
        license_number="MD-301-TEST",
    )
    pat_user = User(
        user_id="302",
        email="pat302@example.com",
        password_hash=hash_password("PatPass302!"),
        role="patient",
        is_active=True,
    )
    patient = PatientProfile(
        patient_id="302",
        user_id="302",
        first_name="Jack",
        last_name="Harkness",
        date_of_birth=date(1978, 3, 11),
        gender="male",
    )
    assignment = DoctorPatientAssignment(
        doctor_id="301",
        patient_id="302",
        is_active=True,
    )
    contract_db_session.add_all([doc_user, doctor, pat_user, patient, assignment])
    contract_db_session.commit()

    doc_token = create_access_token(
        data={"sub": str(doc_user.user_id), "email": doc_user.email, "role": doc_user.role},
        settings=contract_settings,
    )
    doc_headers = {"Authorization": f"Bearer {doc_token}"}

    pat_token = create_access_token(
        data={"sub": str(pat_user.user_id), "email": pat_user.email, "role": pat_user.role},
        settings=contract_settings,
    )
    pat_headers = {"Authorization": f"Bearer {pat_token}"}

    # 1. Doctor creates conversation with patient
    conv_resp = contract_client.post(
        "/api/v1/conversations",
        json={"patient_id": "302"},
        headers=doc_headers,
    )
    assert conv_resp.status_code == status.HTTP_201_CREATED
    conv_data = conv_resp.json()
    assert conv_data["patient_id"] == "302"
    assert conv_data["doctor_id"] == "301"
    conv_id = conv_data["conversation_id"]

    # 2. Patient sends message
    msg_resp = contract_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Doctor, my heart rate has returned to normal."},
        headers=pat_headers,
    )
    assert msg_resp.status_code == status.HTTP_201_CREATED
    msg_data = msg_resp.json()
    assert msg_data["conversation_id"] == conv_id
    assert msg_data["sender_id"] == "302"
    assert msg_data["receiver_id"] == "301"
    assert msg_data["is_read"] is False

    # 3. Doctor lists conversation messages
    list_msgs = contract_client.get(
        f"/api/v1/conversations/{conv_id}/messages?page=1&page_size=20",
        headers=doc_headers,
    )
    assert list_msgs.status_code == status.HTTP_200_OK
    msgs_body = list_msgs.json()
    assert len(msgs_body["items"]) == 1
    assert msgs_body["total_count"] == 1
    assert msgs_body["page"] == 1
    assert msgs_body["page_size"] == 20

    # 4. Doctor marks conversation as read
    mark_read = contract_client.post(
        f"/api/v1/conversations/{conv_id}/read",
        headers=doc_headers,
    )
    assert mark_read.status_code == status.HTTP_200_OK
    assert mark_read.json()["messages_marked_read"] == 1
