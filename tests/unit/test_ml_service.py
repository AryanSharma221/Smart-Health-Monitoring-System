"""
Unit Test Suite for Machine Learning Telemetry Assessment Subsystem.

Tests:
1. MLService singleton initialization and status reporting.
2. Degraded mode graceful fallback behavior on missing model artifacts.
3. Model inference mapping ('normal_like' -> 'normal', 'anomalous' -> 'anomaly', 'insufficient_data' -> 'inconclusive').
4. Telemetry assessment persistence into MySQL model_assessments.
5. Automated clinical alert and transactional outbox event creation upon detected anomalies.
6. Assessment repository queries (pagination, filtering, latest assessments).
7. Thread-safe execution across concurrent worker threads.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Generator
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    Alert,
    AlertStatusHistory,
    AnalyticsOutbox,
    AuditLog,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    ModelAssessment,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.repositories.assessment_repository import AssessmentRepository
from services.api.config import Settings, get_settings
from services.ml_service import MLService, get_ml_service, reset_ml_service


@pytest.fixture(autouse=True)
def clean_ml_buffers():
    """Ensure in-memory patient streaming buffers are isolated between tests."""
    service = get_ml_service()
    service.clear_buffers()
    yield
    service.clear_buffers()


@pytest.fixture(scope="function")
def test_db_session() -> Generator[Session, None, None]:
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
def seed_patient(test_db_session: Session) -> PatientProfile:
    """Seeds a test patient profile."""
    user = User(
        user_id="U_PAT_101",
        email="patient101@example.com",
        password_hash="fake_hash",
        role="patient",
        is_active=True,
    )
    patient = PatientProfile(
        patient_id="P101",
        user_id="U_PAT_101",
        first_name="Patient",
        last_name="OneZeroOne",
        date_of_birth=datetime(1980, 1, 1).date(),
        gender="male",
    )
    test_db_session.add(user)
    test_db_session.add(patient)
    test_db_session.commit()
    return patient


def test_ml_service_singleton_and_status():
    """Verify MLService initializes as a valid singleton and reports correct metadata."""
    reset_ml_service()
    settings = get_settings()
    service = get_ml_service(settings)

    assert isinstance(service, MLService)
    assert service.is_available is True
    assert service.model_version == "1.0.0"

    status_data = service.get_status()
    assert status_data["status"] == "ready"
    assert status_data["is_available"] is True
    assert status_data["algorithm"] == "IsolationForest"
    assert status_data["model_version"] == "1.0.0"
    assert status_data["feature_count"] == 38
    assert status_data["has_baseline_manager"] is True


def test_ml_service_degraded_mode_on_invalid_artifact(tmp_path):
    """Verify MLService enters degraded mode without crashing and falls back safely on assessment."""
    empty_dir = tmp_path / "empty_models"
    empty_dir.mkdir()

    degraded_service = MLService(artifact_dir=str(empty_dir))
    assert degraded_service.is_available is False
    assert degraded_service.degraded_reason is not None

    status_data = degraded_service.get_status()
    assert status_data["status"] == "degraded"
    assert status_data["is_available"] is False
    assert "not found" in status_data["degraded_reason"].lower() or "missing" in status_data["degraded_reason"].lower()

    # Calling assess on degraded service falls back safely to insufficient_data
    result = degraded_service.assess(
        patient_id="P101",
        timestamp=datetime.now(timezone.utc),
        heart_rate=72.0,
        spo2=98.0,
        temperature_f=98.6,
    )
    assert result.result == "insufficient_data"
    assert result.score == 0.0


def test_ml_service_assess_normal_telemetry():
    """Verify inference on normal vitals produces 'normal_like' result with score < 0.60."""
    service = get_ml_service()
    res = service.assess(
        patient_id="P101",
        timestamp=datetime.now(timezone.utc),
        heart_rate=72.0,
        spo2=98.5,
        temperature_f=98.6,
    )

    assert res.result == "normal_like"
    assert float(res.score) < 0.60
    assert res.model_version == "1.0.0"
    assert res.feature_summary is not None


def test_ml_service_assess_anomalous_telemetry():
    """Verify inference on acute physiological anomalies produces 'anomalous' result with score >= 0.60."""
    service = get_ml_service()
    res = service.assess(
        patient_id="P101",
        timestamp=datetime.now(timezone.utc),
        heart_rate=145.0,
        spo2=83.5,
        temperature_f=103.5,
    )

    assert res.result == "anomalous"
    assert float(res.score) >= 0.60
    assert len(res.explanation) > 0


def test_ml_service_assess_unseen_patient_insufficient_buffer():
    """Verify unseen patient without historical baseline maps to 'insufficient_data' result."""
    service = get_ml_service()
    res = service.assess(
        patient_id="P999_TEST_NEW",
        timestamp=datetime.now(timezone.utc),
        heart_rate=75.0,
        spo2=98.0,
        temperature_f=98.4,
    )

    # With fewer than 5 buffer observations and no frozen baseline, it reports insufficient_data
    assert res.result == "insufficient_data"


def test_ml_service_assess_and_persist_normal(test_db_session: Session, seed_patient: PatientProfile):
    """Verify assess_and_persist saves ModelAssessment and creates NO alert for normal vitals."""
    service = get_ml_service()
    now = datetime.now(timezone.utc)
    assessment, alert, result_obj = service.assess_and_persist(
        db=test_db_session,
        patient_id="P101",
        timestamp=now,
        heart_rate=72.0,
        spo2=98.5,
        temperature_f=98.6,
        source_event_id=None,
    )

    assert assessment is not None
    assert assessment.patient_id == "P101"
    assert assessment.result == "normal"
    assert float(assessment.score) < 0.60
    assert assessment.model_version == "1.0.0"
    assert alert is None

    # Verify no alert was generated in database
    alerts = test_db_session.query(Alert).filter(Alert.patient_id == "P101").all()
    assert len(alerts) == 0

    # Verify outbox event for assessment was created
    outbox_events = (
        test_db_session.query(AnalyticsOutbox)
        .filter(AnalyticsOutbox.aggregate_id == assessment.assessment_id)
        .all()
    )
    assert len(outbox_events) == 1
    assert outbox_events[0].event_type == "telemetry_event"


def test_ml_service_assess_and_persist_anomaly_creates_alert(test_db_session: Session, seed_patient: PatientProfile):
    """Verify assess_and_persist saves ModelAssessment, creates Alert, AlertStatusHistory, and OutboxEvent for anomaly."""
    service = get_ml_service()
    now = datetime.now(timezone.utc)
    assessment, alert, result_obj = service.assess_and_persist(
        db=test_db_session,
        patient_id="P101",
        timestamp=now,
        heart_rate=150.0,
        spo2=82.0,
        temperature_f=103.8,
        source_event_id="EVT_ANOMALY_999",
    )

    assert assessment is not None
    assert assessment.result == "anomaly"
    assert float(assessment.score) >= 0.60
    assert alert is not None

    # Verify Alert was created and linked
    alerts = test_db_session.query(Alert).filter(Alert.patient_id == "P101").all()
    assert len(alerts) == 1
    db_alert = alerts[0]
    assert db_alert.category == "ml_anomaly"
    assert db_alert.assessment_id == assessment.assessment_id
    assert db_alert.status == "NEW"
    assert db_alert.severity in ("CRITICAL", "HIGH")

    # Verify AlertStatusHistory was recorded
    history = test_db_session.query(AlertStatusHistory).filter(AlertStatusHistory.alert_id == db_alert.alert_id).all()
    assert len(history) == 1
    assert history[0].new_status == "NEW"

    # Verify AnalyticsOutbox events staged (one for assessment, one for alert)
    outbox_events = test_db_session.query(AnalyticsOutbox).all()
    event_types = [e.event_type for e in outbox_events]
    assert "telemetry_event" in event_types
    assert "alert_event" in event_types


def test_assessment_repository_operations(test_db_session: Session, seed_patient: PatientProfile):
    """Verify AssessmentRepository CRUD, pagination, and latest queries."""
    repo = AssessmentRepository(test_db_session)

    # 1. Create assessments
    a1 = ModelAssessment(
        assessment_id="asmt_001",
        patient_id="P101",
        event_id=None,
        model_version="1.0.0",
        score=Decimal("0.2500"),
        result="normal",
        features_json=json.dumps({"heart_rate": 72.0}),
    )
    persisted_1, created_1 = repo.create_or_get_assessment(a1)
    assert created_1 is True
    assert persisted_1.assessment_id == "asmt_001"

    a2 = ModelAssessment(
        assessment_id="asmt_002",
        patient_id="P101",
        event_id="EVT_UNIQUE_001",
        model_version="1.0.0",
        score=Decimal("0.7800"),
        result="anomaly",
        features_json=json.dumps({"heart_rate": 150.0}),
    )
    persisted_2, created_2 = repo.create_or_get_assessment(a2)
    assert created_2 is True
    assert persisted_2.assessment_id == "asmt_002"

    # Idempotent re-fetch by event_id
    a2_duplicate = ModelAssessment(
        assessment_id="asmt_002_duplicate",
        patient_id="P101",
        event_id="EVT_UNIQUE_001",
        model_version="1.0.0",
        score=Decimal("0.7800"),
        result="anomaly",
    )
    existing_a2, created_dup = repo.create_or_get_assessment(a2_duplicate)
    assert created_dup is False
    assert existing_a2.assessment_id == "asmt_002"

    # 2. Get by ID
    fetched = repo.get_by_id("asmt_001")
    assert fetched is not None
    assert fetched.patient_id == "P101"

    # 3. List paginated
    items, total = repo.list_by_patient_paginated(patient_id="P101", page=1, page_size=10)
    assert total == 2
    assert len(items) == 2

    # 4. List latest
    latest = repo.list_latest_by_patient(patient_id="P101", limit=5)
    assert len(latest) == 2


def test_ml_service_thread_safety_concurrent_calls():
    """Verify concurrent evaluations across multiple threads do not corrupt internal state or raise exceptions."""
    service = get_ml_service()
    now = datetime.now(timezone.utc)

    def evaluate_task(heart_rate: float, spo2: float, temp: float):
        return service.assess(
            patient_id="P101",
            timestamp=now,
            heart_rate=heart_rate,
            spo2=spo2,
            temperature_f=temp,
        )

    tasks = [
        (70.0 + (i % 10), 98.0 - (i % 3), 98.6 + (i % 2) * 0.2)
        for i in range(20)
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(evaluate_task, hr, spo2, temp) for hr, spo2, temp in tasks]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 20
    for res in results:
        assert res.result in ("normal_like", "anomalous", "insufficient_data")
        assert isinstance(float(res.score), float)
