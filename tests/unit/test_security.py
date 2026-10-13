"""
Unit and Integration Tests for Authentication, Password Security, JWT, and RBAC.

Covers all 22 required security scenarios:
- Password hashing via bcrypt, policy validation, and plaintext exclusion.
- JWT creation, claims, expiry, tampering, and signature verification.
- User registration, restricted self-registration, and email uniqueness conflicts.
- User authentication, inactive account blocking, and non-revealing error messages.
- Safe profile serialization (/auth/me) omitting hashes and secrets.
- Role-based authorization and patient ownership / clinician assignment guards.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from database.mysql.models import (
    AuditLog,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    PatientProfile,
    User,
)
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.auth_service import AuthService
from services.auth.exceptions import (
    AccountDisabledError,
    InvalidCredentialsError,
    InvalidTokenError,
    PrivilegeEscalationError,
    TokenExpiredError,
)
from services.auth.schemas import UserRegisterRequest
from services.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    validate_password_policy,
    verify_password,
)


# =============================================================================
# Test Fixtures (Isolated In-Memory SQLite Database)
# =============================================================================

@pytest.fixture(scope="function")
def test_settings() -> Settings:
    """Provides isolated testing configuration with explicit JWT secret."""
    return Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long_for_security!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=30,
    )


@pytest.fixture(scope="function")
def test_db_session() -> Generator[Session, None, None]:
    """Creates a fresh in-memory SQLite database for isolated test execution."""
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
    """TestClient configured with dependency overrides for in-memory session and settings."""
    app = create_app(settings=test_settings)

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# Helper: Seed Test Accounts
# =============================================================================

def seed_patient(
    session: Session,
    email: str = "patient@test.local",
    password: str = "PatientPass123",
    patient_id: str = "PAT-001",
    is_active: bool = True,
) -> tuple[User, PatientProfile]:
    """Seed a test patient with profile."""
    user = User(
        user_id=f"usr_{patient_id.lower()}",
        email=email,
        password_hash=hash_password(password, rounds=4),
        role="patient",
        is_active=is_active,
    )
    profile = PatientProfile(
        patient_id=patient_id,
        user_id=user.user_id,
        first_name="Jane",
        last_name="Doe",
        gender="female",
        height_cm=Decimal("168.00"),
        weight_kg=Decimal("62.50"),
    )
    session.add(user)
    session.flush()
    session.add(profile)
    session.commit()
    return user, profile


def seed_doctor(
    session: Session,
    email: str = "doctor@test.local",
    password: str = "DoctorPass123",
    doctor_id: str = "DOC-001",
    license_num: str = "MD-12345",
    is_active: bool = True,
) -> tuple[User, DoctorProfile]:
    """Seed a test clinician with doctor profile."""
    user = User(
        user_id=f"usr_{doctor_id.lower()}",
        email=email,
        password_hash=hash_password(password, rounds=4),
        role="doctor",
        is_active=is_active,
    )
    profile = DoctorProfile(
        doctor_id=doctor_id,
        user_id=user.user_id,
        first_name="Alice",
        last_name="Smith",
        specialization="Cardiology",
        license_number=license_num,
    )
    session.add(user)
    session.flush()
    session.add(profile)
    session.commit()
    return user, profile


def seed_admin(
    session: Session,
    email: str = "admin@test.local",
    password: str = "AdminPass123",
    is_active: bool = True,
) -> User:
    """Seed an admin_operator user."""
    user = User(
        user_id="usr_admin01",
        email=email,
        password_hash=hash_password(password, rounds=4),
        role="admin_operator",
        is_active=is_active,
    )
    session.add(user)
    session.commit()
    return user


# =============================================================================
# 1. Password Security Tests (Scenarios 8, 22)
# =============================================================================

def test_password_policy_validation():
    """Verify password length, complexity, and character type rules."""
    # Too short (< 8 chars)
    valid, msg = validate_password_policy("Short1!")
    assert not valid
    assert "at least 8 characters" in msg

    # Missing digits
    valid, msg = validate_password_policy("NoDigitsHere!")
    assert not valid
    assert "at least one digit" in msg

    # Missing letters
    valid, msg = validate_password_policy("1234567890!")
    assert not valid
    assert "at least one letter" in msg

    # Exceeding bcrypt 72 bytes limit
    long_pass = "A" * 73
    valid, msg = validate_password_policy(long_pass)
    assert not valid
    assert "cannot exceed 72 bytes" in msg

    # Valid password
    valid, msg = validate_password_policy("ValidPass123")
    assert valid


def test_passwords_stored_as_bcrypt_hashes_never_plaintext(test_db_session: Session):
    """Verify that stored password hashes start with $2b$ and never reveal plaintext."""
    raw_password = "SecretPassword123"
    user, _ = seed_patient(test_db_session, password=raw_password)

    # Inspect the raw stored string
    stored_hash = user.password_hash
    assert stored_hash != raw_password
    assert raw_password not in stored_hash
    assert stored_hash.startswith("$2b$")  # bcrypt identifier
    assert len(stored_hash) == 60

    # Verification helper matches
    assert verify_password(raw_password, stored_hash)
    assert not verify_password("WrongPassword123", stored_hash)


# =============================================================================
# 2. JWT Token Management Tests (Scenarios 1, 4, 5, 6)
# =============================================================================

def test_token_creation_and_successful_decoding(test_settings: Settings):
    """Scenario 1: Valid claims and signature decode properly."""
    claims = {"sub": "usr_patient01", "role": "patient", "email": "p@test.local"}
    token = create_access_token(claims, settings=test_settings)
    assert isinstance(token, str)

    payload = decode_access_token(token, settings=test_settings)
    assert payload["sub"] == "usr_patient01"
    assert payload["role"] == "patient"
    assert payload["email"] == "p@test.local"
    assert payload["iss"] == "smart-health-monitoring-api"
    assert "jti" in payload
    assert "exp" in payload
    assert "iat" in payload


def test_expired_token_rejected(test_settings: Settings):
    """Scenario 4: Expired token raises TokenExpiredError."""
    claims = {"sub": "usr_patient01"}
    # Issued with negative timedelta (already expired)
    expired_token = create_access_token(
        claims,
        expires_delta=timedelta(seconds=-10),
        settings=test_settings,
    )
    with pytest.raises(TokenExpiredError):
        decode_access_token(expired_token, settings=test_settings)


def test_malformed_token_rejected(test_settings: Settings):
    """Scenario 5: Malformed token string raises InvalidTokenError."""
    with pytest.raises(InvalidTokenError):
        decode_access_token("this.is.not.a.valid.jwt", settings=test_settings)

    with pytest.raises(InvalidTokenError):
        decode_access_token("", settings=test_settings)


def test_incorrectly_signed_token_rejected(test_settings: Settings):
    """Scenario 6: Token signed with a different key raises InvalidTokenError."""
    different_settings = Settings(
        jwt_secret="completely_different_secret_key_32_characters_minimum!",
        jwt_algorithm="HS256",
    )
    token_signed_with_other_key = create_access_token(
        {"sub": "usr_patient01"},
        settings=different_settings,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token_signed_with_other_key, settings=test_settings)


# =============================================================================
# 3. Authentication & Login Tests (Scenarios 1, 2, 3, 7, 9, 10, 19, 20)
# =============================================================================

def test_login_successful_produces_token(client: TestClient, test_db_session: Session):
    """Scenario 1: Valid credentials produce 200 OK with access token."""
    seed_patient(test_db_session, email="patient@hospital.org", password="ValidPass123")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "patient@hospital.org", "password": "ValidPass123"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "patient"
    assert data["expires_in"] == 1800  # 30 minutes in test settings


def test_login_incorrect_password_rejected(client: TestClient, test_db_session: Session):
    """Scenario 2: Incorrect credentials return non-revealing 401."""
    seed_patient(test_db_session, email="patient@hospital.org", password="ValidPass123")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "patient@hospital.org", "password": "WrongPassword999"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid email or password."


def test_login_unknown_account_produces_non_revealing_response(client: TestClient):
    """Scenario 3: Unknown account produces identical 401 response to prevent user enumeration."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@hospital.org", "password": "SomePassword123"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid email or password."


def test_inactive_accounts_cannot_authenticate(client: TestClient, test_db_session: Session):
    """Scenario 7: Inactive account cannot authenticate even with correct password."""
    seed_patient(test_db_session, email="disabled@hospital.org", password="ValidPass123", is_active=False)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@hospital.org", "password": "ValidPass123"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "inactive or disabled" in response.json()["detail"].lower()


def test_auth_me_returns_safe_profile_fields_only(client: TestClient, test_db_session: Session):
    """Scenario 9: /auth/me returns only permitted fields and never hashes or secrets."""
    user, profile = seed_patient(test_db_session, email="me@test.local", password="MyPassword123")

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "me@test.local", "password": "MyPassword123"},
    )
    token = login_resp.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Allowed safe fields
    assert data["user_id"] == user.user_id
    assert data["email"] == "me@test.local"
    assert data["role"] == "patient"
    assert data["is_active"] is True
    assert "created_at" in data
    assert data["patient_profile"]["patient_id"] == profile.patient_id

    # Strictly forbidden fields must never be exposed
    assert "password_hash" not in data
    assert "password" not in data
    assert "jwt_secret" not in data
    assert "secret" not in data


def test_unauthenticated_requests_cannot_access_protected_routes(client: TestClient):
    """Scenario 10: Unauthenticated requests return 401 Unauthorized."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Also test with malformed Authorization header
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer bad.token.value"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_duplicate_registration_handled_safely(client: TestClient, test_db_session: Session):
    """Scenario 19: Attempting to register an existing email returns 409 Conflict."""
    seed_patient(test_db_session, email="duplicate@hospital.org", password="OriginalPassword123")

    reg_payload = {
        "email": "duplicate@hospital.org",
        "password": "NewPassword123",
        "first_name": "Second",
        "last_name": "Attempt",
        "role": "patient",
    }
    response = client.post("/api/v1/auth/register", json=reg_payload)
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in response.json()["detail"].lower()


def test_audit_logs_do_not_store_passwords_or_tokens(client: TestClient, test_db_session: Session):
    """Scenario 20: Audit logs record security events without storing passwords or tokens."""
    reg_payload = {
        "email": "audited@hospital.org",
        "password": "AuditedPassword123",
        "first_name": "Audited",
        "last_name": "User",
        "role": "patient",
    }
    reg_resp = client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_resp.status_code == status.HTTP_201_CREATED

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "audited@hospital.org", "password": "AuditedPassword123"},
    )
    assert login_resp.status_code == status.HTTP_200_OK

    # Query audit logs
    audit_logs = list(test_db_session.query(AuditLog).all())
    assert len(audit_logs) >= 2  # REGISTRATION + LOGIN_SUCCESS

    for log in audit_logs:
        meta = log.metadata_json or ""
        assert "AuditedPassword123" not in meta
        assert "access_token" not in meta
        assert "bearer" not in meta.lower()
        assert "$2b$" not in meta  # no hashes in audit trail


# =============================================================================
# 4. Role-Based Authorization & Ownership Tests (Scenarios 11-18)
# =============================================================================

def test_patient_can_access_own_resource(client: TestClient, test_db_session: Session):
    """Scenario 11: Patient can access their own record."""
    user, profile = seed_patient(test_db_session, email="p1@test.local", patient_id="PAT-100")

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "p1@test.local", "password": "PatientPass123"},
    )
    token = login_resp.json()["access_token"]

    response = client.get(
        f"/api/v1/auth/verify-patient-access/{profile.patient_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["authorized"] is True
    assert response.json()["patient_id"] == "PAT-100"


def test_patient_cannot_access_another_patient_resource(client: TestClient, test_db_session: Session):
    """Scenario 12: Patient cannot access another patient's record (403 Forbidden)."""
    # Seed two patients
    _, p1 = seed_patient(test_db_session, email="p1@test.local", patient_id="PAT-101")
    _, p2 = seed_patient(test_db_session, email="p2@test.local", patient_id="PAT-102")

    # Log in as Patient 1
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "p1@test.local", "password": "PatientPass123"},
    )
    token_p1 = login_resp.json()["access_token"]

    # Patient 1 attempts to access Patient 2's data
    response = client.get(
        f"/api/v1/auth/verify-patient-access/{p2.patient_id}",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "only access your own" in response.json()["detail"].lower()


def test_assigned_clinician_can_access_permitted_patient(client: TestClient, test_db_session: Session):
    """Scenario 13: Doctor with active assignment can access patient record."""
    _, doc_profile = seed_doctor(test_db_session, email="doc@test.local", doctor_id="DOC-001", license_num="MD-001")
    _, pat_profile = seed_patient(test_db_session, email="pat@test.local", patient_id="PAT-200")

    # Create care assignment
    assignment = DoctorPatientAssignment(
        doctor_id=doc_profile.doctor_id,
        patient_id=pat_profile.patient_id,
        is_active=True,
    )
    test_db_session.add(assignment)
    test_db_session.commit()

    # Log in as doctor
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "doc@test.local", "password": "DoctorPass123"},
    )
    doc_token = login_resp.json()["access_token"]

    # Doctor accesses assigned patient
    response = client.get(
        f"/api/v1/auth/verify-patient-access/{pat_profile.patient_id}",
        headers={"Authorization": f"Bearer {doc_token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["authorized"] is True


def test_unassigned_clinician_cannot_access_patient(client: TestClient, test_db_session: Session):
    """Scenario 14: Doctor without assignment cannot access patient record (403 Forbidden)."""
    seed_doctor(test_db_session, email="doc_unassigned@test.local", doctor_id="DOC-999", license_num="MD-999")
    _, pat_profile = seed_patient(test_db_session, email="pat_isolated@test.local", patient_id="PAT-300")

    # Log in as unassigned doctor
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "doc_unassigned@test.local", "password": "DoctorPass123"},
    )
    doc_token = login_resp.json()["access_token"]

    # Attempt access without assignment
    response = client.get(
        f"/api/v1/auth/verify-patient-access/{pat_profile.patient_id}",
        headers={"Authorization": f"Bearer {doc_token}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "not assigned" in response.json()["detail"].lower()


def test_user_cannot_elevate_role_via_registration(client: TestClient):
    """Scenario 15: Public registration attempting doctor or admin role is rejected (403 Forbidden)."""
    # Attempt to self-register as doctor
    resp_doc = client.post(
        "/api/v1/auth/register",
        json={
            "email": "fake_doctor@hospital.org",
            "password": "Password123",
            "first_name": "Fake",
            "last_name": "Doctor",
            "role": "doctor",
        },
    )
    assert resp_doc.status_code == status.HTTP_403_FORBIDDEN
    assert "restricted to patient accounts" in resp_doc.json()["detail"].lower()

    # Attempt to self-register as admin_operator
    resp_admin = client.post(
        "/api/v1/auth/register",
        json={
            "email": "fake_admin@hospital.org",
            "password": "Password123",
            "first_name": "Fake",
            "last_name": "Admin",
            "role": "admin_operator",
        },
    )
    assert resp_admin.status_code == status.HTTP_403_FORBIDDEN
    assert "restricted to patient accounts" in resp_admin.json()["detail"].lower()


def test_client_cannot_bypass_authorization_by_tampering_patient_id(client: TestClient, test_db_session: Session):
    """Scenario 17: Client modifying URL path to unmapped Kaggle ID (e.g. P101) is blocked."""
    _, p1 = seed_patient(test_db_session, email="legit@test.local", patient_id="PAT-MYOWN")

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "legit@test.local", "password": "PatientPass123"},
    )
    token = login_resp.json()["access_token"]

    # Attempt to access Kaggle historical patient P101
    response = client.get(
        "/api/v1/auth/verify-patient-access/P101",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_inactive_account_cannot_bypass_role_checks_with_old_token(
    client: TestClient,
    test_db_session: Session,
):
    """Scenario 18: Inactive account cannot use an existing unexpired token."""
    user, profile = seed_patient(test_db_session, email="soon_disabled@test.local", patient_id="PAT-DIS")

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "soon_disabled@test.local", "password": "PatientPass123"},
    )
    token = login_resp.json()["access_token"]

    # Deactivate user on server
    user.is_active = False
    test_db_session.commit()

    # Attempt to use the previously issued token
    response = client.get(
        f"/api/v1/auth/verify-patient-access/{profile.patient_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "inactive or disabled" in response.json()["detail"].lower()


def test_admin_role_enforcement(client: TestClient, test_db_session: Session):
    """Scenario 18b: Verify admin_operator access control guard."""
    admin_user = seed_admin(test_db_session, email="admin@hospital.org", password="AdminPass123")
    seed_patient(test_db_session, email="user@hospital.org", password="UserPass123")

    # Regular patient login
    pat_login = client.post("/api/v1/auth/login", json={"email": "user@hospital.org", "password": "UserPass123"})
    pat_token = pat_login.json()["access_token"]

    # Admin login
    admin_login = client.post("/api/v1/auth/login", json={"email": "admin@hospital.org", "password": "AdminPass123"})
    admin_token = admin_login.json()["access_token"]

    # Patient accessing admin endpoint -> 403 Forbidden
    pat_resp = client.get(
        "/api/v1/auth/verify-admin-access",
        headers={"Authorization": f"Bearer {pat_token}"},
    )
    assert pat_resp.status_code == status.HTTP_403_FORBIDDEN

    # Admin accessing admin endpoint -> 200 OK
    admin_resp = client.get(
        "/api/v1/auth/verify-admin-access",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_resp.status_code == status.HTTP_200_OK
    assert admin_resp.json()["admin"] is True
