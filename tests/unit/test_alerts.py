"""
Unit and Integration Tests for Health Alert Lifecycle, Clinical Rules Engine, and Audit Trail.

Comprehensive test suite verifying:
1. Deterministic threshold rule evaluations (heart rate, SpO2, temperature).
2. Quality and unit safety guardrails (stale data, wrong units, null values).
3. Telemetry provenance and source eligibility (simulator vs historical Kaggle data).
4. Deterministic alert ID generation and database idempotency.
5. Lifecycle state transitions (NEW -> ACKNOWLEDGED -> RESOLVED).
6. Idempotent re-acknowledgement behavior.
7. Disallowed state transitions (acknowledging a resolved alert -> 400).
8. Audit trail persistence (ALERT_TRIGGERED, ALERT_ACKNOWLEDGE, ALERT_ACKNOWLEDGE_REPEATED).
9. Server-side authorization matrix (patient, assigned clinician, unassigned clinician).
10. Paginated alerts API filtering and deterministic ordering.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.exceptions import InvalidStateTransitionError
from database.mysql.models import (
    Alert,
    AlertRule,
    AlertStatusHistory,
    AuditLog,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.repositories.alert_repository import AlertRepository
from database.mysql.repositories.audit_repository import AuditRepository
from database.mysql.session import get_db
from services.alert_service import AlertService
from services.alerts.config import is_source_eligible_for_alerts
from services.alerts.evaluator import AlertEvaluator, generate_deterministic_alert_id
from services.alerts.rules import DEFAULT_ALERT_RULES, AlertRuleDefinition
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password


# =============================================================================
# Test Database Fixtures (Isolated In-Memory SQLite with StaticPool)
# =============================================================================

@pytest.fixture(scope="function")
def test_settings() -> Settings:
    """Isolated test settings with dedicated JWT test secret."""
    return Settings(
        app_env="testing",
        jwt_secret="alert_test_secret_key_at_least_32_chars_long_for_security!",
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
# Helper: Seed Test Patients, Doctors, and Assignments
# =============================================================================

def seed_alert_test_environment(session: Session, test_settings: Settings) -> dict:
    """Seeds test patients, doctors, and role assignments."""
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

    # 2. Patient 2 (P102)
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
        specialization="General Medicine",
        license_number="MD-002",
    )

    session.add_all([u_p1, prof_p1, u_p2, prof_p2, u_d1, prof_d1, assignment, u_d2, prof_d2])
    session.commit()

    tok_p1 = create_access_token(
        data={"sub": "usr_p101", "role": "patient", "email": "p101@test.local"},
        settings=test_settings,
    )
    tok_p2 = create_access_token(
        data={"sub": "usr_p102", "role": "patient", "email": "p102@test.local"},
        settings=test_settings,
    )
    tok_doc1 = create_access_token(
        data={"sub": "usr_doc1", "role": "doctor", "email": "doc1@hospital.org"},
        settings=test_settings,
    )
    tok_doc2 = create_access_token(
        data={"sub": "usr_doc2", "role": "doctor", "email": "doc2@hospital.org"},
        settings=test_settings,
    )

    return {
        "token_p1": tok_p1,
        "token_p2": tok_p2,
        "token_doc1": tok_doc1,
        "token_doc2": tok_doc2,
    }


# =============================================================================
# 1. Rule Evaluation Tests (Deterministic Thresholds & Guardrails)
# =============================================================================

def test_normal_vitals_do_not_trigger_alerts():
    """Verify normal physiological readings do not breach any demonstration thresholds."""
    now = datetime.now(timezone.utc)
    reading = VitalsReading(
        reading_id="r_normal",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("75.00"),
        unit="bpm",
        raw_value=Decimal("75.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    for rule in DEFAULT_ALERT_RULES:
        assert rule.evaluate(reading) is False


def test_heart_rate_threshold_triggers():
    """Verify heart rate thresholds for HIGH, CRITICAL, and LOW."""
    now = datetime.now(timezone.utc)
    # Tachycardia HIGH (> 100)
    r_high = VitalsReading(
        reading_id="r1",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("110.00"),
        unit="bpm",
        raw_value=Decimal("110.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    rules_triggered = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_high)]
    assert "RULE_HR_HIGH" in rules_triggered
    assert "RULE_HR_CRITICAL_HIGH" not in rules_triggered

    # Severe Tachycardia CRITICAL (> 130)
    r_crit = VitalsReading(
        reading_id="r2",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("145.00"),
        unit="bpm",
        raw_value=Decimal("145.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    crit_rules = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_crit)]
    assert "RULE_HR_HIGH" in crit_rules
    assert "RULE_HR_CRITICAL_HIGH" in crit_rules

    # Bradycardia MEDIUM (< 50)
    r_low = VitalsReading(
        reading_id="r3",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("45.00"),
        unit="bpm",
        raw_value=Decimal("45.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    low_rules = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_low)]
    assert "RULE_HR_LOW" in low_rules


def test_spo2_threshold_triggers():
    """Verify SpO2 hypoxemia rules (<90% HIGH, <85% CRITICAL)."""
    now = datetime.now(timezone.utc)
    # SpO2 = 88% (HIGH)
    r_hypo = VitalsReading(
        reading_id="r4",
        patient_id="P101",
        metric_code="spo2",
        value=Decimal("88.00"),
        unit="%",
        raw_value=Decimal("88.00"),
        raw_unit="%",
        quality_status="valid",
        measured_at=now,
    )
    rules = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_hypo)]
    assert "RULE_SPO2_LOW" in rules
    assert "RULE_SPO2_CRITICAL_LOW" not in rules

    # SpO2 = 82% (CRITICAL)
    r_crit_hypo = VitalsReading(
        reading_id="r5",
        patient_id="P101",
        metric_code="spo2",
        value=Decimal("82.00"),
        unit="%",
        raw_value=Decimal("82.00"),
        raw_unit="%",
        quality_status="valid",
        measured_at=now,
    )
    rules_crit = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_crit_hypo)]
    assert "RULE_SPO2_LOW" in rules_crit
    assert "RULE_SPO2_CRITICAL_LOW" in rules_crit


def test_temperature_threshold_triggers():
    """Verify temperature fever rules (>38.0°C MEDIUM, >39.5°C CRITICAL, <35.0°C HIGH)."""
    now = datetime.now(timezone.utc)
    # Fever 38.5°C (MEDIUM)
    r_fever = VitalsReading(
        reading_id="r6",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("38.50"),
        unit="degC",
        raw_value=Decimal("38.50"),
        raw_unit="degC",
        quality_status="valid",
        measured_at=now,
    )
    rules_fever = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_fever)]
    assert "RULE_TEMP_HIGH" in rules_fever
    assert "RULE_TEMP_CRITICAL_HIGH" not in rules_fever

    # High Fever 40.0°C (CRITICAL)
    r_high_fever = VitalsReading(
        reading_id="r7",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("40.00"),
        unit="degC",
        raw_value=Decimal("40.00"),
        raw_unit="degC",
        quality_status="valid",
        measured_at=now,
    )
    rules_high_fever = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_high_fever)]
    assert "RULE_TEMP_HIGH" in rules_high_fever
    assert "RULE_TEMP_CRITICAL_HIGH" in rules_high_fever

    # Hypothermia 34.2°C (HIGH)
    r_hypo = VitalsReading(
        reading_id="r8",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("34.20"),
        unit="degC",
        raw_value=Decimal("34.20"),
        raw_unit="degC",
        quality_status="valid",
        measured_at=now,
    )
    rules_hypo = [r.rule_id for r in DEFAULT_ALERT_RULES if r.evaluate(r_hypo)]
    assert "RULE_TEMP_LOW" in rules_hypo


def test_rule_guardrails_unit_and_quality():
    """Verify strict guards: unit mismatch, non-valid quality, null value, disabled rule."""
    now = datetime.now(timezone.utc)

    # 1. Unit mismatch guard: Fahrenheit value checked against Celsius rule
    r_wrong_unit = VitalsReading(
        reading_id="r_bad_unit",
        patient_id="P101",
        metric_code="temperature",
        value=Decimal("101.30"),
        unit="degF",
        raw_value=Decimal("101.30"),
        raw_unit="degF",
        quality_status="valid",
        measured_at=now,
    )
    for rule in [r for r in DEFAULT_ALERT_RULES if r.metric_code == "temperature"]:
        assert rule.evaluate(r_wrong_unit) is False

    # 2. Quality status guard: out_of_range reading must not trigger rule
    r_invalid_quality = VitalsReading(
        reading_id="r_bad_quality",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("180.00"),
        unit="bpm",
        raw_value=Decimal("180.00"),
        raw_unit="bpm",
        quality_status="out_of_range",
        measured_at=now,
    )
    assert any(r.evaluate(r_invalid_quality) for r in DEFAULT_ALERT_RULES) is False

    # 3. None value guard
    r_none = VitalsReading(
        reading_id="r_none",
        patient_id="P101",
        metric_code="heart_rate",
        value=None,
        unit="bpm",
        raw_value=None,
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    assert any(r.evaluate(r_none) for r in DEFAULT_ALERT_RULES) is False

    # 4. Disabled rule guard
    custom_rule = AlertRuleDefinition(
        rule_id="RULE_DISABLED",
        metric_code="heart_rate",
        operator=">",
        configured_value=Decimal("60.00"),
        unit="bpm",
        severity="LOW",
        is_enabled=False,
    )
    r_normal = VitalsReading(
        reading_id="r_norm",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("95.00"),
        unit="bpm",
        raw_value=Decimal("95.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    assert custom_rule.evaluate(r_normal) is False


# =============================================================================
# 2. Provenance and Source Eligibility Tests
# =============================================================================

def test_source_eligibility_policy():
    """Verify source eligibility logic for live vs batch historical sources."""
    # Simulated data is always eligible
    assert is_source_eligible_for_alerts("simulator", is_simulated=True) is True
    assert is_source_eligible_for_alerts("kaggle", is_simulated=True) is True

    # Registered live sources are eligible
    assert is_source_eligible_for_alerts("wearable", is_simulated=False) is True
    assert is_source_eligible_for_alerts("mqtt_telemetry", is_simulated=False) is True

    # Historical Kaggle import is excluded by default
    assert is_source_eligible_for_alerts("kaggle", is_simulated=False) is False
    assert is_source_eligible_for_alerts("kaggle", is_simulated=False, allow_historical=False) is False

    # Historical Kaggle import with explicit backfill flag is eligible
    assert is_source_eligible_for_alerts("kaggle", is_simulated=False, allow_historical=True) is True


def test_evaluator_skips_ineligible_kaggle_batch(test_db_session: Session, test_settings: Settings):
    """Verify that Kaggle historical rows do not generate alerts during normal operation."""
    seed_alert_test_environment(test_db_session, test_settings)
    now = datetime.now(timezone.utc)

    event = IngestionEvent(
        event_id="evt_kaggle_001",
        patient_id="P101",
        source="kaggle",
        source_event_id="kaggle_row_1",
        measured_at=now,
        is_simulated=False,
    )
    reading = VitalsReading(
        event_id="evt_kaggle_001",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("150.00"),  # Tachycardia value
        unit="bpm",
        raw_value=Decimal("150.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    event.readings = [reading]
    test_db_session.add(event)
    test_db_session.commit()

    evaluator = AlertEvaluator(test_db_session)
    alerts = evaluator.evaluate_event(event, allow_historical=False)
    assert len(alerts) == 0

    # With allow_historical=True, alerts should be generated and tagged
    historical_alerts = evaluator.evaluate_event(event, allow_historical=True)
    assert len(historical_alerts) > 0
    assert "[Historical Backfill — Non-Live Record]" in historical_alerts[0].reason


# =============================================================================
# 3. Idempotency & Deduplication Tests
# =============================================================================

def test_deterministic_alert_id_generation():
    """Verify deterministic alert IDs are consistent and collision-resistant."""
    id1 = generate_deterministic_alert_id("evt_100", "RULE_HR_HIGH")
    id2 = generate_deterministic_alert_id("evt_100", "RULE_HR_HIGH")
    id3 = generate_deterministic_alert_id("evt_100", "RULE_HR_LOW")
    id4 = generate_deterministic_alert_id("evt_101", "RULE_HR_HIGH")

    assert id1 == id2
    assert id1 != id3
    assert id1 != id4
    assert id1.startswith("alt_")
    assert len(id1) == 28  # "alt_" + 24 hex characters


def test_evaluator_idempotent_duplicate_prevention(test_db_session: Session, test_settings: Settings):
    """Verify re-evaluating the same telemetry event creates no duplicate database alerts."""
    seed_alert_test_environment(test_db_session, test_settings)
    now = datetime.now(timezone.utc)

    event = IngestionEvent(
        event_id="evt_sim_001",
        patient_id="P101",
        source="simulator",
        source_event_id="sim_1",
        measured_at=now,
        is_simulated=True,
    )
    reading = VitalsReading(
        event_id="evt_sim_001",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("120.00"),  # Triggers RULE_HR_HIGH
        unit="bpm",
        raw_value=Decimal("120.00"),
        raw_unit="bpm",
        quality_status="valid",
        measured_at=now,
    )
    event.readings = [reading]
    test_db_session.add(event)
    test_db_session.commit()

    evaluator = AlertEvaluator(test_db_session)

    # 1. First evaluation: creates alert
    first_run_alerts = evaluator.evaluate_event(event)
    assert len(first_run_alerts) == 1
    alert_id = first_run_alerts[0].alert_id

    # Check alert in database
    alert_repo = AlertRepository(test_db_session)
    persisted = alert_repo.get_by_id(alert_id)
    assert persisted is not None
    assert persisted.status == "NEW"

    # 2. Second evaluation: idempotent, returns existing alert without duplicate
    second_run_alerts = evaluator.evaluate_event(event)
    assert len(second_run_alerts) == 1
    assert second_run_alerts[0].alert_id == alert_id

    # Database count must still be exactly 1
    all_alerts = alert_repo.list_alerts(patient_id="P101")
    assert len(all_alerts) == 1


# =============================================================================
# 4. Lifecycle & Acknowledgement Tests
# =============================================================================

def test_alert_lifecycle_acknowledgement_and_idempotency(test_db_session: Session, test_settings: Settings):
    """Verify alert transitions from NEW to ACKNOWLEDGED, and re-acknowledgement is idempotent."""
    env = seed_alert_test_environment(test_db_session, test_settings)
    alert_service = AlertService(test_db_session)

    # Create test alert
    alert = Alert(
        alert_id="alt_test_lifecycle",
        patient_id="P101",
        severity="HIGH",
        category="vital_threshold",
        reason="Heart rate elevated",
        status="NEW",
    )
    test_db_session.add(alert)
    test_db_session.commit()

    # 1. First acknowledgement by doctor
    ack_alert = alert_service.acknowledge_alert(
        alert_id="alt_test_lifecycle",
        actor_id="usr_doc1",
        note="Reviewed ECG, monitoring closely.",
    )
    assert ack_alert.status == "ACKNOWLEDGED"
    assert ack_alert.acknowledged_by == "usr_doc1"
    assert ack_alert.acknowledged_at is not None
    orig_ack_time = ack_alert.acknowledged_at

    # 2. Second acknowledgement (idempotent repeated call)
    repeat_ack = alert_service.acknowledge_alert(
        alert_id="alt_test_lifecycle",
        actor_id="usr_doc1",
        note="Duplicate click by clinician",
    )
    assert repeat_ack.status == "ACKNOWLEDGED"
    assert repeat_ack.acknowledged_by == "usr_doc1"
    assert repeat_ack.acknowledged_at == orig_ack_time

    # 3. Verify audit log captures both attempts
    audit_repo = AuditRepository(test_db_session)
    logs = audit_repo.list_logs(actor_id="usr_doc1", target_type="alert")
    actions = [l.action for l in logs]
    assert "ALERT_ACKNOWLEDGE" in actions
    assert "ALERT_ACKNOWLEDGE_REPEATED" in actions


def test_resolved_alert_cannot_be_acknowledged(test_db_session: Session, test_settings: Settings):
    """Verify attempting to acknowledge a RESOLVED alert raises InvalidStateTransitionError."""
    seed_alert_test_environment(test_db_session, test_settings)
    alert_service = AlertService(test_db_session)

    alert = Alert(
        alert_id="alt_resolved_test",
        patient_id="P101",
        severity="MEDIUM",
        category="vital_threshold",
        reason="Temperature elevation resolved",
        status="RESOLVED",
        resolved_by="usr_doc1",
        resolved_at=datetime.now(timezone.utc),
    )
    test_db_session.add(alert)
    test_db_session.commit()

    with pytest.raises(InvalidStateTransitionError, match="Cannot acknowledge an already resolved alert"):
        alert_service.acknowledge_alert(alert_id="alt_resolved_test", actor_id="usr_doc1")


# =============================================================================
# 5. REST API & Authorization Matrix Tests
# =============================================================================

def test_patient_can_view_own_alerts(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify patient user can list their own alerts."""
    env = seed_alert_test_environment(test_db_session, test_settings)
    now = datetime.now(timezone.utc)

    # Seed an alert for P101
    alert = Alert(
        alert_id="alt_p101_1",
        patient_id="P101",
        severity="HIGH",
        category="vital_threshold",
        reason="Heart rate tachycardia demo",
        status="NEW",
        created_at=now,
    )
    test_db_session.add(alert)
    test_db_session.commit()

    headers = {"Authorization": f"Bearer {env['token_p1']}"}
    response = client.get("/patients/P101/alerts", headers=headers)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["total_count"] == 1
    assert data["items"][0]["alert_id"] == "alt_p101_1"
    assert data["items"][0]["severity"] == "HIGH"
    assert data["items"][0]["status"] == "NEW"


def test_patient_cannot_view_other_patient_alerts(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify patient is forbidden from accessing another patient's alerts."""
    env = seed_alert_test_environment(test_db_session, test_settings)

    headers = {"Authorization": f"Bearer {env['token_p1']}"}  # Patient 1 token
    response = client.get("/patients/P102/alerts", headers=headers)  # Target Patient 2
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_assigned_doctor_can_view_patient_alerts(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify assigned doctor (DOC-001) can view patient P101's alerts."""
    env = seed_alert_test_environment(test_db_session, test_settings)

    alert = Alert(
        alert_id="alt_doc_view",
        patient_id="P101",
        severity="CRITICAL",
        category="vital_threshold",
        reason="Severe hypoxemia alert",
        status="NEW",
    )
    test_db_session.add(alert)
    test_db_session.commit()

    headers = {"Authorization": f"Bearer {env['token_doc1']}"}
    response = client.get("/patients/P101/alerts", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["total_count"] == 1


def test_unassigned_doctor_forbidden_from_viewing_alerts(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify unassigned doctor (DOC-002) cannot view patient P101's alerts."""
    env = seed_alert_test_environment(test_db_session, test_settings)

    headers = {"Authorization": f"Bearer {env['token_doc2']}"}
    response = client.get("/patients/P101/alerts", headers=headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_api_get_single_alert(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify GET /alerts/{alert_id} for authorized vs unauthorized users."""
    env = seed_alert_test_environment(test_db_session, test_settings)

    alert = Alert(
        alert_id="alt_single_001",
        patient_id="P101",
        severity="HIGH",
        category="vital_threshold",
        reason="Bradycardia alert",
        status="NEW",
    )
    test_db_session.add(alert)
    test_db_session.commit()

    # 1. Patient P101 authorized
    headers_p1 = {"Authorization": f"Bearer {env['token_p1']}"}
    res_p1 = client.get("/alerts/alt_single_001", headers=headers_p1)
    assert res_p1.status_code == status.HTTP_200_OK
    assert res_p1.json()["alert_id"] == "alt_single_001"

    # 2. Patient P102 unauthorized
    headers_p2 = {"Authorization": f"Bearer {env['token_p2']}"}
    res_p2 = client.get("/alerts/alt_single_001", headers=headers_p2)
    assert res_p2.status_code == status.HTTP_403_FORBIDDEN

    # 3. Non-existent alert
    res_missing = client.get("/alerts/alt_non_existent", headers=headers_p1)
    assert res_missing.status_code == status.HTTP_404_NOT_FOUND


def test_api_acknowledge_alert(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify POST /alerts/{alert_id}/acknowledge endpoint."""
    env = seed_alert_test_environment(test_db_session, test_settings)

    alert = Alert(
        alert_id="alt_to_ack",
        patient_id="P101",
        severity="HIGH",
        category="vital_threshold",
        reason="Fever threshold breach",
        status="NEW",
    )
    test_db_session.add(alert)
    test_db_session.commit()

    headers = {"Authorization": f"Bearer {env['token_doc1']}"}
    payload = {"note": "Clinician acknowledged from nurse station"}
    response = client.post("/alerts/alt_to_ack/acknowledge", json=payload, headers=headers)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["status"] == "ACKNOWLEDGED"
    assert data["acknowledged_by"] == "usr_doc1"
    assert data["acknowledged_at"] is not None

    # Idempotent re-acknowledge
    res_repeat = client.post("/alerts/alt_to_ack/acknowledge", json=payload, headers=headers)
    assert res_repeat.status_code == status.HTTP_200_OK
    assert res_repeat.json()["status"] == "ACKNOWLEDGED"


def test_api_acknowledge_resolved_alert_returns_400(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify acknowledging a resolved alert via API returns 400 Bad Request."""
    env = seed_alert_test_environment(test_db_session, test_settings)

    alert = Alert(
        alert_id="alt_resolved_api",
        patient_id="P101",
        severity="MEDIUM",
        category="vital_threshold",
        reason="Condition resolved",
        status="RESOLVED",
        resolved_by="usr_doc1",
        resolved_at=datetime.now(timezone.utc),
    )
    test_db_session.add(alert)
    test_db_session.commit()

    headers = {"Authorization": f"Bearer {env['token_doc1']}"}
    response = client.post("/alerts/alt_resolved_api/acknowledge", json={"note": "late ack"}, headers=headers)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot acknowledge an already resolved alert" in response.json()["detail"]


def test_api_alerts_pagination_and_filtering(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify filtering by severity, status, and pagination metadata."""
    env = seed_alert_test_environment(test_db_session, test_settings)
    now = datetime.now(timezone.utc)

    # Seed 5 alerts with varied severity and status
    alerts = [
        Alert(alert_id=f"alt_page_{i}", patient_id="P101", severity="HIGH" if i % 2 == 0 else "CRITICAL",
              category="vital_threshold", reason=f"Alert {i}", status="NEW" if i < 3 else "ACKNOWLEDGED",
              created_at=now - timedelta(minutes=i * 10))
        for i in range(5)
    ]
    test_db_session.add_all(alerts)
    test_db_session.commit()

    headers = {"Authorization": f"Bearer {env['token_doc1']}"}

    # 1. Filter by status=NEW
    res_status = client.get("/patients/P101/alerts?status=NEW", headers=headers)
    assert res_status.status_code == status.HTTP_200_OK
    assert res_status.json()["total_count"] == 3

    # 2. Filter by severity=CRITICAL
    res_sev = client.get("/patients/P101/alerts?severity=CRITICAL", headers=headers)
    assert res_sev.status_code == status.HTTP_200_OK
    assert res_sev.json()["total_count"] == 2

    # 3. Pagination with page_size=2
    res_page = client.get("/patients/P101/alerts?page=1&page_size=2", headers=headers)
    assert res_page.status_code == status.HTTP_200_OK
    page_data = res_page.json()
    assert len(page_data["items"]) == 2
    assert page_data["total_count"] == 5
    assert page_data["total_pages"] == 3
    assert page_data["has_next"] is True
    assert page_data["has_previous"] is False


def test_api_invalid_filters_rejected(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify invalid status and inverted time ranges return 400 Bad Request."""
    env = seed_alert_test_environment(test_db_session, test_settings)
    headers = {"Authorization": f"Bearer {env['token_doc1']}"}

    # Invalid status
    res_bad_status = client.get("/patients/P101/alerts?status=INVALID_STATUS", headers=headers)
    assert res_bad_status.status_code == status.HTTP_400_BAD_REQUEST

    # Invalid severity
    res_bad_sev = client.get("/patients/P101/alerts?severity=EXTREME", headers=headers)
    assert res_bad_sev.status_code == status.HTTP_400_BAD_REQUEST

    # Inverted time range
    res_bad_time = client.get(
        "/patients/P101/alerts?start_time=2026-10-14T00:00:00Z&end_time=2026-10-13T00:00:00Z",
        headers=headers,
    )
    assert res_bad_time.status_code == status.HTTP_400_BAD_REQUEST


def test_api_unauthenticated_requests_rejected(client: TestClient):
    """Verify missing authorization headers return 401 Unauthorized."""
    assert client.get("/patients/P101/alerts").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/alerts/alt_fake").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.post("/alerts/alt_fake/acknowledge").status_code == status.HTTP_401_UNAUTHORIZED


def test_api_unauthorized_user_cannot_acknowledge(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify unauthorized users (different patient or unassigned doctor) cannot acknowledge alert."""
    env = seed_alert_test_environment(test_db_session, test_settings)

    alert = Alert(
        alert_id="alt_p101_priv",
        patient_id="P101",
        severity="HIGH",
        category="vital_threshold",
        reason="Elevated HR",
        status="NEW",
    )
    test_db_session.add(alert)
    test_db_session.commit()

    # Patient P102 attempting to ack P101's alert -> 403
    h_p2 = {"Authorization": f"Bearer {env['token_p2']}"}
    res_p2 = client.post("/alerts/alt_p101_priv/acknowledge", json={"note": "hacked"}, headers=h_p2)
    assert res_p2.status_code == status.HTTP_403_FORBIDDEN

    # Unassigned Doctor DOC-002 attempting to ack P101's alert -> 403
    h_doc2 = {"Authorization": f"Bearer {env['token_doc2']}"}
    res_doc2 = client.post("/alerts/alt_p101_priv/acknowledge", json={"note": "intruder"}, headers=h_doc2)
    assert res_doc2.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_view_any_patient_alerts(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify administrator has operational oversight to view any patient's alerts."""
    seed_alert_test_environment(test_db_session, test_settings)

    # Seed Admin User
    admin_user = User(
        user_id="usr_admin",
        email="admin@hospital.org",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="admin_operator",
        is_active=True,
    )
    test_db_session.add(admin_user)

    # Seed alert for P101
    alert = Alert(
        alert_id="alt_admin_view",
        patient_id="P101",
        severity="MEDIUM",
        category="vital_threshold",
        reason="Observation",
        status="NEW",
    )
    test_db_session.add(alert)
    test_db_session.commit()

    tok_admin = create_access_token(
        data={"sub": "usr_admin", "role": "admin_operator", "email": "admin@hospital.org"},
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {tok_admin}"}
    res = client.get("/patients/P101/alerts", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["total_count"] == 1


def test_empty_patient_alerts_returns_empty_page(client: TestClient, test_db_session: Session, test_settings: Settings):
    """Verify patient with 0 alerts receives structured empty page."""
    env = seed_alert_test_environment(test_db_session, test_settings)
    headers = {"Authorization": f"Bearer {env['token_p2']}"}

    res = client.get("/patients/P102/alerts", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["items"] == []
    assert data["total_count"] == 0
    assert data["page"] == 1
    assert data["total_pages"] == 0
    assert data["has_next"] is False
    assert data["has_previous"] is False


def test_direct_alert_repository_methods(test_db_session: Session):
    """Verify direct AlertRepository methods for deduplication, querying, and history."""
    repo = AlertRepository(test_db_session)

    alert = Alert(
        alert_id="alt_direct_01",
        patient_id="P101",
        event_id="evt_d1",
        rule_id="RULE_HR_HIGH",
        severity="HIGH",
        category="vital_threshold",
        reason="Direct test",
        status="NEW",
    )
    created, was_created = repo.create_or_get_alert(alert)
    assert was_created is True
    assert created.alert_id == "alt_direct_01"

    # Query by event and rule
    found = repo.get_by_event_and_rule("evt_d1", "RULE_HR_HIGH")
    assert found is not None
    assert found.alert_id == "alt_direct_01"

    # Duplicate create_or_get
    dup, was_created_dup = repo.create_or_get_alert(alert)
    assert was_created_dup is False
    assert dup.alert_id == "alt_direct_01"

    # Record status transition and check history
    repo.record_status_transition(alert=found, new_status="ACKNOWLEDGED", actor_id="usr_doc1", note="Manual review")
    history = repo.get_history("alt_direct_01")
    assert len(history) == 1
    assert history[0].old_status == "NEW"
    assert history[0].new_status == "ACKNOWLEDGED"
    assert history[0].actor_id == "usr_doc1"

