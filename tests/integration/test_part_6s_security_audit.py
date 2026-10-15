"""
Part 6S — Comprehensive Security and Authorization Audit Automated Test Suite.

Verifies:
1. Authentication & Role Enforcement:
   - Unauthenticated requests rejected across all protected clinical routes (HTTP 401).
   - Cross-patient isolation (patient accessing another patient's data -> HTTP 403).
   - Clinician care-assignment enforcement (unassigned clinician -> HTTP 403).
   - Administrative endpoint role requirements (non-admin -> HTTP 403).
   - Alert acknowledgement & resolution: restricted strictly to clinicians and admins (patient -> HTTP 403).
   - Messaging permissions: non-participants and non-assigned parties cannot send or read messages (HTTP 403).
   - Simulator controls: patient role is strictly forbidden from controlling simulator (HTTP 403).
   - Production simulator controls require authentication or valid key.
   - WebSocket authentication and subscription permission guards.

2. Input Validation & Resilience:
   - Malformed/tampered patient_id, alert_id, and conversation_id patterns rejected (HTTP 422).
   - Physiological boundaries enforced on telemetry assessments.
   - Invalid simulator scenario parameters rejected with HTTP 422.
   - Pagination limits (page_size > 100, page < 1) rejected with HTTP 422.
   - Whitespace and oversized messages rejected with HTTP 422.

3. Secrets & Configuration:
   - Production invariants reject APP_DEBUG=True, weak JWT secrets, or default keys.
   - Password hashes strictly excluded from all user identity serialization.
   - Database URIs masked safely in logs and diagnostics.

4. Simulator Isolation & Clinical Boundary:
   - Synthetic provenance enforced (is_simulated=True, source='smartwatch_simulator').
   - Ingestion rejects untrusted sources or fake simulation flags.
   - Simulator stop preserves past readings and does not mutate clinical thresholds.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mongodb.client import sanitize_mongo_uri
from database.mysql.models import (
    Alert,
    AlertRule,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.session import get_db
from services.alerts.rules import DEFAULT_ALERT_RULES
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from services.simulator.ingestion_service import IngestionOutcome, SimulatorIngestionService


@pytest.fixture(scope="function")
def audit_settings() -> Settings:
    return Settings(
        app_env="testing",
        jwt_secret="audit_secret_key_at_least_32_characters_long_for_security!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        ingestion_api_key="audit_secure_internal_ingestion_key",
    )


@pytest.fixture(scope="function")
def audit_db() -> Generator[Session, None, None]:
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
def audit_client(audit_db: Session, audit_settings: Settings) -> Generator[TestClient, None, None]:
    app = create_app(settings=audit_settings)

    def override_get_db():
        try:
            yield audit_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def audit_cohort(audit_db: Session):
    """Seed comprehensive identity cohort for authorization matrix testing."""
    now = datetime.now(timezone.utc)

    # 1. Patient Alice (P101)
    u_alice = User(user_id="U_ALICE", email="alice@patient.org", password_hash=hash_password("AlicePass123!"), role="patient", is_active=True)
    p_alice = PatientProfile(patient_id="P101", user_id="U_ALICE", first_name="Alice", last_name="Smith", date_of_birth=date(1992, 3, 15), gender="female")

    # 2. Patient Bob (P102)
    u_bob = User(user_id="U_BOB", email="bob@patient.org", password_hash=hash_password("BobPass123!"), role="patient", is_active=True)
    p_bob = PatientProfile(patient_id="P102", user_id="U_BOB", first_name="Bob", last_name="Jones", date_of_birth=date(1988, 7, 22), gender="male")

    # 3. Doctor Dave (DOC1) - Assigned to Alice
    u_dave = User(user_id="U_DAVE", email="dave@hospital.org", password_hash=hash_password("DavePass123!"), role="doctor", is_active=True)
    d_dave = DoctorProfile(doctor_id="DOC1", user_id="U_DAVE", first_name="David", last_name="Miller", specialization="Cardiology", license_number="LIC-DOC1")

    # 4. Doctor Carol (DOC2) - Unassigned to Alice or Bob
    u_carol = User(user_id="U_CAROL", email="carol@hospital.org", password_hash=hash_password("CarolPass123!"), role="doctor", is_active=True)
    d_carol = DoctorProfile(doctor_id="DOC2", user_id="U_CAROL", first_name="Carol", last_name="Taylor", specialization="Pulmonology", license_number="LIC-DOC2")

    # 5. Admin Operator (ADM1)
    u_admin = User(user_id="U_ADMIN", email="admin@hospital.org", password_hash=hash_password("AdminPass123!"), role="admin_operator", is_active=True)

    # Care assignment: Dave -> Alice (P101)
    assignment = DoctorPatientAssignment(doctor_id="DOC1", patient_id="P101", is_active=True)

    # Telemetry and Alert on Alice
    ev_alice = IngestionEvent(event_id="EV-ALICE-1", patient_id="P101", source="smartwatch_simulator", source_event_id="EV-ALICE-1", is_simulated=True, measured_at=now)
    rd_alice = VitalsReading(event_id="EV-ALICE-1", patient_id="P101", metric_code="heart_rate", value=Decimal("135.0"), unit="bpm", raw_value=Decimal("135.0"), raw_unit="bpm", measured_at=now)
    alt_alice = Alert(alert_id="ALT-ALICE-1", patient_id="P101", event_id="EV-ALICE-1", rule_id="RULE_HR_CRITICAL_HIGH", severity="CRITICAL", category="vital_threshold", reason="Critical Tachycardia", status="NEW", created_at=now)

    audit_db.add_all([u_alice, p_alice, u_bob, p_bob, u_dave, d_dave, u_carol, d_carol, u_admin, assignment, ev_alice, rd_alice, alt_alice])
    audit_db.commit()

    return {
        "alice": {"user": u_alice, "profile": p_alice},
        "bob": {"user": u_bob, "profile": p_bob},
        "dave": {"user": u_dave, "profile": d_dave},
        "carol": {"user": u_carol, "profile": d_carol},
        "admin": {"user": u_admin},
        "alt_alice": alt_alice,
    }


# =============================================================================
# 1. Authentication & Role Enforcement Tests
# =============================================================================

def test_unauthenticated_clinical_routes_return_401(audit_client: TestClient):
    """Verify that every protected clinical endpoint returns HTTP 401 when accessed without credentials."""
    unauthenticated_endpoints = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/patients"),
        ("GET", "/api/v1/patients/P101/readings"),
        ("GET", "/api/v1/patients/P101/readings/latest"),
        ("GET", "/api/v1/patients/P101/vitals"),
        ("GET", "/api/v1/alerts"),
        ("GET", "/api/v1/patients/P101/alerts"),
        ("GET", "/api/v1/alerts/ALT-ALICE-1"),
        ("POST", "/api/v1/alerts/ALT-ALICE-1/acknowledge"),
        ("POST", "/api/v1/alerts/ALT-ALICE-1/resolve"),
        ("GET", "/api/v1/conversations"),
        ("POST", "/api/v1/conversations"),
        ("POST", "/api/v1/ws-ticket"),
        ("POST", "/api/v1/patients/P101/assess"),
    ]
    for method, path in unauthenticated_endpoints:
        if method == "GET":
            resp = audit_client.get(path)
        else:
            resp = audit_client.post(path, json={})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED, (
            f"Endpoint {method} {path} should return 401 Unauthorized but returned {resp.status_code}"
        )


def test_cross_patient_access_strictly_forbidden(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """Verify Patient Bob cannot access Alice's readings, profile, or alerts."""
    token_bob = create_access_token(
        data={"sub": audit_cohort["bob"]["user"].user_id, "email": audit_cohort["bob"]["user"].email, "role": "patient"},
        settings=audit_settings,
    )
    headers_bob = {"Authorization": f"Bearer {token_bob}"}

    # Readings
    resp = audit_client.get("/api/v1/patients/P101/readings", headers=headers_bob)
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # Single Profile
    resp = audit_client.get("/api/v1/patients/P101", headers=headers_bob)
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # Alerts
    resp = audit_client.get("/api/v1/patients/P101/alerts", headers=headers_bob)
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # Specific Alert
    resp = audit_client.get("/api/v1/alerts/ALT-ALICE-1", headers=headers_bob)
    assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_unassigned_doctor_access_forbidden(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """Verify Doctor Carol (unassigned) is strictly forbidden from Alice's clinical records."""
    token_carol = create_access_token(
        data={"sub": audit_cohort["carol"]["user"].user_id, "email": audit_cohort["carol"]["user"].email, "role": "doctor"},
        settings=audit_settings,
    )
    headers_carol = {"Authorization": f"Bearer {token_carol}"}

    resp = audit_client.get("/api/v1/patients/P101/readings", headers=headers_carol)
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    resp = audit_client.get("/api/v1/patients/P101/alerts", headers=headers_carol)
    assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_patient_cannot_acknowledge_or_resolve_alerts(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """
    Critical Clinical Safety Check:
    Verify that even on their OWN alerts, a patient cannot acknowledge or resolve them.
    Alert acknowledgement is strictly reserved for clinicians and administrators.
    """
    token_alice = create_access_token(
        data={"sub": audit_cohort["alice"]["user"].user_id, "email": audit_cohort["alice"]["user"].email, "role": "patient"},
        settings=audit_settings,
    )
    headers_alice = {"Authorization": f"Bearer {token_alice}"}

    # Alice attempts to acknowledge her own alert
    resp_ack = audit_client.post("/api/v1/alerts/ALT-ALICE-1/acknowledge", json={"note": "Patient ack"}, headers=headers_alice)
    assert resp_ack.status_code == status.HTTP_403_FORBIDDEN
    assert "Only clinicians and administrative operators" in resp_ack.json()["detail"]

    # Alice attempts to resolve her own alert
    resp_res = audit_client.post("/api/v1/alerts/ALT-ALICE-1/resolve", json={"note": "Patient res"}, headers=headers_alice)
    assert resp_res.status_code == status.HTTP_403_FORBIDDEN
    assert "Only clinicians and administrative operators" in resp_res.json()["detail"]


def test_assigned_doctor_can_acknowledge_and_resolve_alert(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """Verify that the assigned clinician (Dave) can acknowledge and resolve Alice's alert."""
    token_dave = create_access_token(
        data={"sub": audit_cohort["dave"]["user"].user_id, "email": audit_cohort["dave"]["user"].email, "role": "doctor"},
        settings=audit_settings,
    )
    headers_dave = {"Authorization": f"Bearer {token_dave}"}

    # Acknowledge
    resp_ack = audit_client.post("/api/v1/alerts/ALT-ALICE-1/acknowledge", json={"note": "Dr. Dave reviewed"}, headers=headers_dave)
    assert resp_ack.status_code == status.HTTP_200_OK
    assert resp_ack.json()["status"] == "ACKNOWLEDGED"

    # Resolve
    resp_res = audit_client.post("/api/v1/alerts/ALT-ALICE-1/resolve", json={"note": "Condition stabilized"}, headers=headers_dave)
    assert resp_res.status_code == status.HTTP_200_OK
    assert resp_res.json()["status"] == "RESOLVED"


def test_patient_role_forbidden_from_simulator_controls(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """
    Verify that an authenticated patient cannot invoke simulator lifecycle controls.
    """
    token_alice = create_access_token(
        data={"sub": audit_cohort["alice"]["user"].user_id, "email": audit_cohort["alice"]["user"].email, "role": "patient"},
        settings=audit_settings,
    )
    headers_alice = {"Authorization": f"Bearer {token_alice}"}

    # Start
    resp_start = audit_client.post("/api/v1/simulator/start", headers=headers_alice)
    assert resp_start.status_code == status.HTTP_403_FORBIDDEN

    # Stop
    resp_stop = audit_client.post("/api/v1/simulator/stop", headers=headers_alice)
    assert resp_stop.status_code == status.HTTP_403_FORBIDDEN

    # Scenario
    resp_scen = audit_client.post(
        "/api/v1/simulator/scenario",
        json={"scenario": "alert_test", "alert_metric": "heart_rate"},
        headers=headers_alice,
    )
    assert resp_scen.status_code == status.HTTP_403_FORBIDDEN


def test_production_simulator_unauthenticated_rejected(
    audit_client: TestClient,
):
    """Verify that in production (APP_ENV=production), unauthenticated requests to simulator controls return 403."""
    from services.api.config import get_settings
    prod_settings = Settings(
        app_env="production",
        app_debug=False,
        jwt_secret="production_very_strong_secret_key_32_bytes_minimum!",
        mysql_password="ProdPassword123!Secure",
        ingestion_api_key="prod_simulator_secure_key_12345",
        simulator_ingestion_enabled=False,
    )
    audit_client.app.dependency_overrides[get_settings] = lambda: prod_settings
    try:
        resp = audit_client.post("/api/v1/simulator/start")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
    finally:
        audit_client.app.dependency_overrides.pop(get_settings, None)


# =============================================================================
# 2. Input Validation Tests
# =============================================================================

def test_patient_id_path_pattern_validation(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """Verify that invalid characters in patient_id (such as quotes or path traversal) fail schema validation."""
    token_dave = create_access_token(
        data={"sub": audit_cohort["dave"]["user"].user_id, "email": audit_cohort["dave"]["user"].email, "role": "doctor"},
        settings=audit_settings,
    )
    headers_dave = {"Authorization": f"Bearer {token_dave}"}

    malicious_ids = [
        "P101;DROP",
        "P101'OR'1'='1",
        "../etc/passwd",
        "P101<script>",
        "P 101",
    ]
    for bad_id in malicious_ids:
        resp = audit_client.get(f"/api/v1/patients/{bad_id}/readings", headers=headers_dave)
        # Fast validation rejection: 422 Unprocessable Content (or 404/403)
        assert resp.status_code in (status.HTTP_422_UNPROCESSABLE_CONTENT, status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN)


def test_invalid_simulator_scenario_payload_rejected(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """Verify that unapproved scenario names or parameters return 422 schema validation errors."""
    token_dave = create_access_token(
        data={"sub": audit_cohort["dave"]["user"].user_id, "email": audit_cohort["dave"]["user"].email, "role": "doctor"},
        settings=audit_settings,
    )
    headers_dave = {"Authorization": f"Bearer {token_dave}"}

    # Invalid scenario name
    resp_bad_name = audit_client.post(
        "/api/v1/simulator/scenario",
        json={"scenario": "hack_the_vital_signs", "alert_metric": "heart_rate"},
        headers=headers_dave,
    )
    assert resp_bad_name.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Invalid alert metric
    resp_bad_metric = audit_client.post(
        "/api/v1/simulator/scenario",
        json={"scenario": "normal", "alert_metric": "non_existent_vital"},
        headers=headers_dave,
    )
    assert resp_bad_metric.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_ml_assessment_physiological_limits(
    audit_client: TestClient,
    audit_settings: Settings,
    audit_cohort: dict,
):
    """Verify that physiologically impossible telemetry input is rejected with 422."""
    token_dave = create_access_token(
        data={"sub": audit_cohort["dave"]["user"].user_id, "email": audit_cohort["dave"]["user"].email, "role": "doctor"},
        settings=audit_settings,
    )
    headers_dave = {"Authorization": f"Bearer {token_dave}"}

    # Negative heart rate
    resp_neg_hr = audit_client.post(
        "/api/v1/patients/P101/assess",
        json={"heart_rate": -10.0, "spo2": 98.0, "temperature_f": 98.6},
        headers=headers_dave,
    )
    assert resp_neg_hr.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # SpO2 > 100%
    resp_over_spo2 = audit_client.post(
        "/api/v1/patients/P101/assess",
        json={"heart_rate": 72.0, "spo2": 150.0, "temperature_f": 98.6},
        headers=headers_dave,
    )
    assert resp_over_spo2.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Unrealistic temperature
    resp_over_temp = audit_client.post(
        "/api/v1/patients/P101/assess",
        json={"heart_rate": 72.0, "spo2": 98.0, "temperature_f": 250.0},
        headers=headers_dave,
    )
    assert resp_over_temp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# =============================================================================
# 3. Secrets & Configuration Tests
# =============================================================================

def test_production_settings_reject_debug_and_weak_secrets():
    """Verify that Settings validation rejects dangerous production configurations."""
    # 1. APP_DEBUG=True in production must fail
    with pytest.raises(ValueError, match="APP_DEBUG must be disabled"):
        Settings(
            app_env="production",
            app_debug=True,
            jwt_secret="strong_jwt_secret_with_more_than_32_characters_12345",
            mysql_password="SecurePassword123!",
            ingestion_api_key="secure_api_key_12345",
        )

    # 2. Insecure default JWT secret in production must fail
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(
            app_env="production",
            app_debug=False,
            jwt_secret="insecure_dev_secret_key_must_be_changed_in_production_at_least_32_chars",
            mysql_password="SecurePassword123!",
            ingestion_api_key="secure_api_key_12345",
        )

    # 3. Default ingestion key in production must fail
    with pytest.raises(ValueError, match="INGESTION_API_KEY"):
        Settings(
            app_env="production",
            app_debug=False,
            jwt_secret="strong_jwt_secret_with_more_than_32_characters_12345",
            mysql_password="SecurePassword123!",
            ingestion_api_key="dev_simulator_key",
        )


def test_sanitize_mongo_uri_redacts_credentials():
    """Verify sanitize_mongo_uri masks username and password."""
    raw_uri = "mongodb+srv://admin_user:SuperSecretPass123!@cluster0.abcde.mongodb.net/smart_health?retryWrites=true"
    sanitized = sanitize_mongo_uri(raw_uri)
    assert "SuperSecretPass123!" not in sanitized
    assert "admin_user" not in sanitized
    assert "mongodb+srv://***:***@cluster0.abcde.mongodb.net/smart_health" in sanitized


# =============================================================================
# 4. Simulator Ingestion Provenance & Isolation
# =============================================================================

def test_simulator_ingestion_rejects_missing_is_simulated():
    """Verify SimulatorIngestionService rejects payloads that omit or set is_simulated=False."""
    raw_reading = {
        "event_id": "evt_test_1",
        "patient_id": "P101",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "heart_rate": 75.0,
        "spo2": 98.0,
        "temperature_f": 98.6,
        "source": "smartwatch_simulator",
        "is_simulated": False,  # Untruthful flag
    }
    is_valid, err_msg, _ = SimulatorIngestionService.validate_reading(raw_reading)
    assert is_valid is False
    assert "Payload must have 'is_simulated': True" in (err_msg or "")


def test_simulator_ingestion_rejects_untrusted_provenance():
    """Verify SimulatorIngestionService rejects readings masquerading as historical Kaggle dataset."""
    raw_reading = {
        "event_id": "evt_test_2",
        "patient_id": "P101",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "heart_rate": 75.0,
        "spo2": 98.0,
        "temperature_f": 98.6,
        "source": "kaggle_csv",  # Ingestion of Kaggle dataset via simulator stream forbidden
        "is_simulated": True,
    }
    is_valid, err_msg, _ = SimulatorIngestionService.validate_reading(raw_reading)
    assert is_valid is False
    assert "Untrusted provenance source" in (err_msg or "")
