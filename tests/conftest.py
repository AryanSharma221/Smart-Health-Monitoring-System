"""
Global Pytest Configuration and Reusable Security Fixtures.

Provides standardized, isolated test doubles and security fixtures for:
1. Isolated in-memory SQLite database sessions (isolated_db).
2. Authenticated role personas:
   - patient_a (P101) & patient_b (P102)
   - assigned_clinician (DOC_ALICE -> assigned to P101)
   - unassigned_clinician (DOC_BOB -> assigned to P102 only)
   - admin_operator (U_ADMIN -> system-wide audit access)
3. Unauthenticated and invalid credential fixtures:
   - unauthenticated_client
   - invalid_credentials (expired, tampered, malformed, inactive)
4. Strict Read-Only MongoDB Atlas double (readonly_mongo_db).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Generator
import mongomock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mongodb.read_only_guard import StrictReadOnlyMongoDatabase
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


@pytest.fixture(scope="session")
def security_test_settings() -> Settings:
    """Standardized test settings with known test secret."""
    return Settings(
        app_env="testing",
        jwt_secret="security_test_secret_key_at_least_32_characters_long!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        ingestion_api_key="security_test_internal_key",
    )


@pytest.fixture(scope="function")
def isolated_db() -> Generator[Session, None, None]:
    """Isolated, ephemeral in-memory SQLite database session seeded with test cohort."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session: Session = TestingSessionLocal()

    # 1. Alert Rules
    for r in DEFAULT_ALERT_RULES:
        session.add(AlertRule(
            rule_id=r.rule_id,
            metric_code=r.metric_code,
            operator=r.operator,
            configured_value=r.configured_value,
            duration_seconds=getattr(r, "duration_seconds", 0),
            severity=r.severity,
            is_enabled=r.is_enabled,
            is_demo_only=r.is_demo_only,
            description=r.description,
        ))

    # 2. Doctor Alice (Assigned to P101)
    doc_alice_user = User(
        user_id="U_DOC_ALICE",
        email="alice.doctor@hospital.org",
        password_hash=hash_password("DoctorPass_123!"),
        role="doctor",
        is_active=True,
    )
    session.add(doc_alice_user)
    session.add(DoctorProfile(
        doctor_id="DOC_ALICE",
        user_id="U_DOC_ALICE",
        first_name="Alice",
        last_name="Smith",
        license_number="LIC-ALICE-123",
        specialization="Cardiology",
    ))

    # 3. Doctor Bob (Assigned to P102 only)
    doc_bob_user = User(
        user_id="U_DOC_BOB",
        email="bob.doctor@hospital.org",
        password_hash=hash_password("DoctorPass_456!"),
        role="doctor",
        is_active=True,
    )
    session.add(doc_bob_user)
    session.add(DoctorProfile(
        doctor_id="DOC_BOB",
        user_id="U_DOC_BOB",
        first_name="Bob",
        last_name="Jones",
        license_number="LIC-BOB-456",
        specialization="General Practice",
    ))

    # 4. Patient A (P101)
    p101_user = User(
        user_id="U_PAT_101",
        email="p101@patient.org",
        password_hash=hash_password("PatientPass_101!"),
        role="patient",
        is_active=True,
    )
    session.add(p101_user)
    session.add(PatientProfile(
        patient_id="P101",
        user_id="U_PAT_101",
        first_name="John",
        last_name="Doe",
        date_of_birth=date(1980, 5, 15),
        gender="male",
    ))

    # 5. Patient B (P102)
    p102_user = User(
        user_id="U_PAT_102",
        email="p102@patient.org",
        password_hash=hash_password("PatientPass_102!"),
        role="patient",
        is_active=True,
    )
    session.add(p102_user)
    session.add(PatientProfile(
        patient_id="P102",
        user_id="U_PAT_102",
        first_name="Jane",
        last_name="Roe",
        date_of_birth=date(1992, 8, 22),
        gender="female",
    ))

    # 6. Admin User
    admin_user = User(
        user_id="U_ADMIN",
        email="admin@hospital.org",
        password_hash=hash_password("AdminPass_999!"),
        role="admin_operator",
        is_active=True,
    )
    session.add(admin_user)

    # 7. Inactive User
    inactive_user = User(
        user_id="U_INACTIVE",
        email="inactive@hospital.org",
        password_hash=hash_password("InactivePass_123!"),
        role="patient",
        is_active=False,
    )
    session.add(inactive_user)

    # 8. Doctor-Patient Care Assignments:
    # Alice -> P101
    # Bob   -> P102
    session.add(DoctorPatientAssignment(doctor_id="DOC_ALICE", patient_id="P101"))
    session.add(DoctorPatientAssignment(doctor_id="DOC_BOB", patient_id="P102"))

    # 9. Seed Baseline Readings & Alerts
    now = datetime.now(timezone.utc)
    evt_p101 = IngestionEvent(
        event_id="EVT_P101_1",
        patient_id="P101",
        source="smartwatch_simulator",
        source_event_id="SRC_101_1",
        measured_at=now,
        is_simulated=True,
    )
    session.add(evt_p101)
    session.add(VitalsReading(
        event_id="EVT_P101_1",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("82.0"),
        unit="bpm",
        raw_value=Decimal("82.0"),
        raw_unit="bpm",
        measured_at=now,
    ))

    evt_p102 = IngestionEvent(
        event_id="EVT_P102_1",
        patient_id="P102",
        source="smartwatch_simulator",
        source_event_id="SRC_102_1",
        measured_at=now,
        is_simulated=True,
    )
    session.add(evt_p102)
    session.add(VitalsReading(
        event_id="EVT_P102_1",
        patient_id="P102",
        metric_code="heart_rate",
        value=Decimal("74.0"),
        unit="bpm",
        raw_value=Decimal("74.0"),
        raw_unit="bpm",
        measured_at=now,
    ))

    session.add(Alert(
        alert_id="ALT_P101_001",
        patient_id="P101",
        event_id="EVT_P101_1",
        rule_id="RULE_HR_CRITICAL_HIGH",
        severity="CRITICAL",
        category="vital_threshold",
        reason="Critical tachycardia detected",
        status="NEW",
        created_at=now,
    ))

    session.add(Conversation(
        conversation_id="CONV_ALICE_P101",
        patient_id="P101",
        doctor_id="DOC_ALICE",
        is_active=True,
    ))
    session.add(Message(
        message_id="MSG_001",
        conversation_id="CONV_ALICE_P101",
        sender_id="U_DOC_ALICE",
        receiver_id="U_PAT_101",
        content="Welcome to remote monitoring John.",
        is_read=False,
    ))

    session.commit()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def api_client(isolated_db: Session, security_test_settings: Settings) -> Generator[TestClient, None, None]:
    """TestClient wired to isolated in-memory DB and test configuration."""
    app = create_app(settings=security_test_settings)
    app.dependency_overrides[get_db] = lambda: isolated_db
    client = TestClient(app)
    yield client


@pytest.fixture(scope="function")
def security_personas(isolated_db: Session, security_test_settings: Settings) -> Dict[str, Any]:
    """Tokens and persona credentials for all test actors."""
    def gen_token(user_id: str, email: str, role: str, exp_mins: int = 60, secret: str | None = None) -> str:
        s = Settings(
            jwt_secret=secret or security_test_settings.jwt_secret,
            app_env="testing",
        )
        return create_access_token(
            data={"sub": user_id, "email": email, "role": role},
            settings=s,
            expires_delta=timedelta(minutes=exp_mins),
        )

    return {
        "patient_a_token": gen_token("U_PAT_101", "p101@patient.org", "patient"),
        "patient_b_token": gen_token("U_PAT_102", "p102@patient.org", "patient"),
        "assigned_clinician_token": gen_token("U_DOC_ALICE", "alice.doctor@hospital.org", "doctor"),
        "unassigned_clinician_token": gen_token("U_DOC_BOB", "bob.doctor@hospital.org", "doctor"),
        "admin_token": gen_token("U_ADMIN", "admin@hospital.org", "admin_operator"),
        "inactive_user_token": gen_token("U_INACTIVE", "inactive@hospital.org", "patient"),
        "expired_token": gen_token("U_PAT_101", "p101@patient.org", "patient", exp_mins=-10),
        "tampered_token": gen_token("U_PAT_101", "p101@patient.org", "patient", secret="invalid_tampered_secret_32chars!"),
    }


@pytest.fixture(scope="function")
def readonly_mongo_db() -> StrictReadOnlyMongoDatabase:
    """Strict Read-Only MongoDB mock database double."""
    client = mongomock.MongoClient()
    raw_db = client["smart_health_analytics"]
    raw_coll = raw_db["telemetry_events"]
    raw_coll.insert_many([
        {"event_id": f"EVT_MOCK_{i}", "patient_id": "P101", "heart_rate": 70 + i}
        for i in range(10)
    ])
    return StrictReadOnlyMongoDatabase(raw_db)
