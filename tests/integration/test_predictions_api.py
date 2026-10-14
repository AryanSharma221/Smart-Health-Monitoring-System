"""
Integration Test Suite for Machine Learning Predictions and Assessments API.

Verifies end-to-end API gateway behavior:
1. Operational model status probe: /predictions/status (unauthenticated).
2. Telemetry ingestion and assessment: /patients/{patient_id}/assess.
3. Role-based access control (Doctor-patient assignment, self-access, cross-patient rejection).
4. Automated clinical alert generation for acute ML anomalies.
5. Paginated historical assessment listing: /patients/{patient_id}/assessments.
6. Input validation contracts and error handling.
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
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    ModelAssessment,
    PatientProfile,
    User,
)
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from services.ml_service import get_ml_service


@pytest.fixture(autouse=True)
def clean_ml_buffers():
    """Ensure in-memory streaming buffers are isolated between integration tests."""
    service = get_ml_service()
    service.clear_buffers()
    yield
    service.clear_buffers()


@pytest.fixture(scope="function")
def api_settings() -> Settings:
    return Settings(
        app_env="testing",
        jwt_secret="testing_predictions_api_secret_key_at_least_32_chars!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
    )


@pytest.fixture(scope="function")
def api_db_session() -> Generator[Session, None, None]:
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
def api_client(api_db_session: Session, api_settings: Settings) -> Generator[TestClient, None, None]:
    app = create_app(settings=api_settings)

    def override_get_db():
        try:
            yield api_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seed_clinical_entities(api_db_session: Session):
    """
    Seeds clinical test environment:
    - Doctor 1 (assigned to Patient P101)
    - Doctor 2 (unassigned)
    - Patient P101
    - Patient P102
    """
    # 1. Doctor 1 (Assigned)
    user_doc1 = User(
        user_id="U_DOC_1",
        email="doc1@hospital.org",
        password_hash=hash_password("DoctorPass123!"),
        role="doctor",
        is_active=True,
    )
    doc1 = DoctorProfile(
        doctor_id="DOC_1",
        user_id="U_DOC_1",
        first_name="Leonard",
        last_name="McCoy",
        specialization="Cardiology",
        license_number="LIC-DOC-001",
    )

    # 2. Doctor 2 (Unassigned)
    user_doc2 = User(
        user_id="U_DOC_2",
        email="doc2@hospital.org",
        password_hash=hash_password("DoctorPass123!"),
        role="doctor",
        is_active=True,
    )
    doc2 = DoctorProfile(
        doctor_id="DOC_2",
        user_id="U_DOC_2",
        first_name="Beverly",
        last_name="Crusher",
        specialization="General Practice",
        license_number="LIC-DOC-002",
    )

    # 3. Patient P101
    user_pat1 = User(
        user_id="U_PAT_101",
        email="p101@patient.org",
        password_hash=hash_password("PatientPass123!"),
        role="patient",
        is_active=True,
    )
    pat1 = PatientProfile(
        patient_id="P101",
        user_id="U_PAT_101",
        first_name="Arthur",
        last_name="Dent",
        date_of_birth=date(1978, 3, 11),
        gender="male",
    )

    # 4. Patient P102
    user_pat2 = User(
        user_id="U_PAT_102",
        email="p102@patient.org",
        password_hash=hash_password("PatientPass123!"),
        role="patient",
        is_active=True,
    )
    pat2 = PatientProfile(
        patient_id="P102",
        user_id="U_PAT_102",
        first_name="Ford",
        last_name="Prefect",
        date_of_birth=date(1982, 8, 24),
        gender="male",
    )

    # Assignment: Doc 1 -> Patient P101
    assignment = DoctorPatientAssignment(
        doctor_id="DOC_1",
        patient_id="P101",
        is_active=True,
    )

    api_db_session.add_all([user_doc1, doc1, user_doc2, doc2, user_pat1, pat1, user_pat2, pat2, assignment])
    api_db_session.commit()

    return {
        "doc1_user": user_doc1,
        "doc2_user": user_doc2,
        "pat1_user": user_pat1,
        "pat2_user": user_pat2,
    }


def _make_auth_header(user: User, settings: Settings) -> dict:
    token = create_access_token(
        data={"sub": str(user.user_id), "email": user.email, "role": user.role},
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 1. Operational Model Health Probe
# =============================================================================

def test_predictions_status_endpoint(api_client: TestClient):
    """Verify /predictions/status is unauthenticated and returns operational readiness."""
    for endpoint in ("/predictions/status", "/api/v1/predictions/status"):
        resp = api_client.get(endpoint)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] in ("ready", "degraded")
        assert "is_available" in data
        assert "model_version" in data
        assert data["algorithm"] == "IsolationForest"
        assert data["feature_count"] == 38
        assert "has_baseline_manager" in data
        assert "SIMULATED DATA" in data["notice"]


# =============================================================================
# 2. Telemetry Assessment and RBAC Tests
# =============================================================================

def test_patient_telemetry_assessment_by_assigned_doctor_normal(
    api_client: TestClient,
    api_db_session: Session,
    api_settings: Settings,
    seed_clinical_entities: dict,
):
    """Verify assigned doctor can assess patient telemetry and normal vitals persist without alerts."""
    doc_user = seed_clinical_entities["doc1_user"]
    headers = _make_auth_header(doc_user, api_settings)

    payload = {
        "heart_rate": 72.0,
        "spo2": 98.5,
        "temperature_f": 98.6,
        "is_simulated": True,
    }

    resp = api_client.post("/api/v1/patients/P101/assess", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["patient_id"] == "P101"
    assert data["result"] == "normal"
    assert data["is_anomaly"] is False
    assert data["score"] < 0.60
    assert data["model_version"] == "1.0.0"
    assert "assessment_id" in data

    # Verify relational persistence in model_assessments
    db_assessment = api_db_session.get(ModelAssessment, data["assessment_id"])
    assert db_assessment is not None
    assert db_assessment.result == "normal"
    assert float(db_assessment.score) < 0.60

    # Verify NO alert created
    alerts = api_db_session.query(Alert).filter(Alert.patient_id == "P101").all()
    assert len(alerts) == 0


def test_patient_telemetry_assessment_acute_anomaly_creates_alert(
    api_client: TestClient,
    api_db_session: Session,
    api_settings: Settings,
    seed_clinical_entities: dict,
):
    """Verify acute physiological anomaly triggers alert creation and links to assessment."""
    doc_user = seed_clinical_entities["doc1_user"]
    headers = _make_auth_header(doc_user, api_settings)

    payload = {
        "heart_rate": 148.0,
        "spo2": 82.5,
        "temperature_f": 103.6,
        "is_simulated": True,
    }

    resp = api_client.post("/api/v1/patients/P101/assess", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["patient_id"] == "P101"
    assert data["result"] == "anomaly"
    assert data["is_anomaly"] is True
    assert data["score"] >= 0.50
    assert len(data["explanation"]) > 0
    assert data["alert_triggered"] is True
    assert data["alert_id"] is not None

    # Verify relational persistence
    db_assessment = api_db_session.get(ModelAssessment, data["assessment_id"])
    assert db_assessment is not None
    assert db_assessment.result == "anomaly"

    # Verify Alert was created and linked to assessment
    alerts = api_db_session.query(Alert).filter(Alert.patient_id == "P101").all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.category == "ml_anomaly"
    assert alert.assessment_id == data["assessment_id"]
    assert alert.status == "NEW"
    assert alert.severity in ("CRITICAL", "HIGH")


def test_patient_self_assessment_allowed(
    api_client: TestClient,
    api_settings: Settings,
    seed_clinical_entities: dict,
):
    """Verify patients can evaluate their own telemetry (patient self-monitoring)."""
    pat_user = seed_clinical_entities["pat1_user"]
    headers = _make_auth_header(pat_user, api_settings)

    payload = {
        "heart_rate": 74.0,
        "spo2": 99.0,
        "temperature_f": 98.4,
    }

    resp = api_client.post("/api/v1/patients/P101/assess", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["patient_id"] == "P101"


def test_cross_patient_assessment_forbidden(
    api_client: TestClient,
    api_settings: Settings,
    seed_clinical_entities: dict,
):
    """Verify Patient P102 cannot post telemetry assessments for Patient P101 (RBAC)."""
    pat2_user = seed_clinical_entities["pat2_user"]
    headers = _make_auth_header(pat2_user, api_settings)

    payload = {
        "heart_rate": 70.0,
        "spo2": 98.0,
        "temperature_f": 98.6,
    }

    resp = api_client.post("/api/v1/patients/P101/assess", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "Forbidden" in resp.json()["detail"]


def test_unassigned_doctor_assessment_forbidden(
    api_client: TestClient,
    api_settings: Settings,
    seed_clinical_entities: dict,
):
    """Verify unassigned clinician (DOC_2) is forbidden from assessing Patient P101."""
    doc2_user = seed_clinical_entities["doc2_user"]
    headers = _make_auth_header(doc2_user, api_settings)

    payload = {
        "heart_rate": 75.0,
        "spo2": 98.0,
        "temperature_f": 98.6,
    }

    resp = api_client.post("/api/v1/patients/P101/assess", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "Clinician is not assigned" in resp.json()["detail"]


def test_unauthenticated_request_rejected(api_client: TestClient):
    """Verify missing Bearer credentials returns 401 Unauthorized."""
    resp = api_client.post(
        "/api/v1/patients/P101/assess",
        json={"heart_rate": 72.0, "spo2": 98.0, "temperature_f": 98.6},
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_input_validation_errors(
    api_client: TestClient,
    api_settings: Settings,
    seed_clinical_entities: dict,
):
    """Verify physiologically implausible telemetry inputs fail validation with 422."""
    doc_user = seed_clinical_entities["doc1_user"]
    headers = _make_auth_header(doc_user, api_settings)

    # Negative heart rate (< 20 bpm)
    resp_hr = api_client.post(
        "/api/v1/patients/P101/assess",
        json={"heart_rate": -10.0, "spo2": 98.0, "temperature_f": 98.6},
        headers=headers,
    )
    assert resp_hr.status_code in (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_400_BAD_REQUEST,
    )

    # SpO2 > 100%
    resp_spo2 = api_client.post(
        "/api/v1/patients/P101/assess",
        json={"heart_rate": 72.0, "spo2": 150.0, "temperature_f": 98.6},
        headers=headers,
    )
    assert resp_spo2.status_code in (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_400_BAD_REQUEST,
    )

    # Temperature outside valid clinical range (< 70 or > 115)
    resp_temp = api_client.post(
        "/api/v1/patients/P101/assess",
        json={"heart_rate": 72.0, "spo2": 98.0, "temperature_f": 150.0},
        headers=headers,
    )
    assert resp_temp.status_code in (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_400_BAD_REQUEST,
    )


# =============================================================================
# 3. Paginated Historical Assessments Tests
# =============================================================================

def test_list_patient_assessments_pagination_and_filtering(
    api_client: TestClient,
    api_db_session: Session,
    api_settings: Settings,
    seed_clinical_entities: dict,
):
    """Verify paginated retrieval of historical assessments with page and page_size."""
    doc_user = seed_clinical_entities["doc1_user"]
    headers = _make_auth_header(doc_user, api_settings)

    # Seed 3 assessments directly into db
    now = datetime.now(timezone.utc)
    a1 = ModelAssessment(
        assessment_id="asmt_001",
        patient_id="P101",
        model_version="1.0.0",
        score=Decimal("0.2500"),
        result="normal",
        features_json='{"heart_rate": 72.0}',
        time_window_start=now,
        time_window_end=now,
        created_at=now,
    )
    a2 = ModelAssessment(
        assessment_id="asmt_002",
        patient_id="P101",
        model_version="1.0.0",
        score=Decimal("0.8500"),
        result="anomaly",
        features_json='{"heart_rate": 155.0}',
        time_window_start=now,
        time_window_end=now,
        created_at=now,
    )
    a3 = ModelAssessment(
        assessment_id="asmt_003",
        patient_id="P101",
        model_version="1.0.0",
        score=Decimal("0.2200"),
        result="normal",
        features_json='{"heart_rate": 70.0}',
        time_window_start=now,
        time_window_end=now,
        created_at=now,
    )
    api_db_session.add_all([a1, a2, a3])
    api_db_session.commit()

    # 1. Fetch page 1 with page_size=2
    resp = api_client.get(
        "/api/v1/patients/P101/assessments?page=1&page_size=2",
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total_count"] == 3
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total_pages"] == 2

    # 2. Fetch page 2 with page_size=2
    resp2 = api_client.get(
        "/api/v1/patients/P101/assessments?page=2&page_size=2",
        headers=headers,
    )
    assert resp2.status_code == status.HTTP_200_OK
    data2 = resp2.json()
    assert len(data2["items"]) == 1

    # 3. Verify unassigned clinician cannot access assessments list
    doc2_user = seed_clinical_entities["doc2_user"]
    doc2_headers = _make_auth_header(doc2_user, api_settings)
    resp_forbidden = api_client.get(
        "/api/v1/patients/P101/assessments",
        headers=doc2_headers,
    )
    assert resp_forbidden.status_code == status.HTTP_403_FORBIDDEN
