"""
Authentication and Identity Domain Service.

Coordinates user registration, credential verification, JWT issuance,
role enforcement, and audit trail recording.
"""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from database.mysql.exceptions import EntityConflictError, EntityNotFoundError
from database.mysql.models import PatientProfile, User
from database.mysql.repositories.audit_repository import AuditRepository
from database.mysql.repositories.patient_repository import PatientRepository
from database.mysql.repositories.user_repository import UserRepository
from services.api.config import Settings, get_settings
from services.auth.exceptions import (
    AccountDisabledError,
    InvalidCredentialsError,
    PrivilegeEscalationError,
)
from services.auth.schemas import UserRegisterRequest
from services.auth.security import (
    create_access_token,
    hash_password,
    validate_password_policy,
    verify_password,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Domain service managing user authentication and access lifecycle."""

    def __init__(self, session: Session, settings: Optional[Settings] = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.user_repo = UserRepository(session)
        self.patient_repo = PatientRepository(session)
        self.audit_repo = AuditRepository(session)

    def register_patient(
        self,
        payload: UserRegisterRequest,
        ip_address: Optional[str] = None,
    ) -> Tuple[User, PatientProfile]:
        """
        Register a new patient account with associated PatientProfile.
        Enforces restricted public registration policy (only patient role permitted).
        """
        # 1. Enforce strict role boundary: public registration can NEVER create doctor or admin accounts
        requested_role = payload.role.strip().lower()
        if requested_role != "patient":
            raise PrivilegeEscalationError(
                "Self-registration is restricted to patient accounts. "
                "Clinician and Administrator accounts must be provisioned by an administrator."
            )

        # 2. Validate password complexity
        valid, msg = validate_password_policy(payload.password)
        if not valid:
            raise ValueError(msg)

        # 3. Check for existing email conflict
        existing_user = self.user_repo.get_by_email(payload.email)
        if existing_user:
            raise EntityConflictError(
                f"A user with email '{payload.email}' already exists.",
                conflict_key="email",
            )

        # 4. Generate stable internal identifiers
        user_id = f"usr_{uuid.uuid4().hex[:16]}"
        patient_id = f"PAT-{uuid.uuid4().hex[:8].upper()}"

        # 5. Hash password safely via bcrypt (rounds=4 in testing for rapid test runs, 12 in production)
        rounds = 4 if self.settings.app_env == "testing" else 12
        pwd_hash = hash_password(payload.password, rounds=rounds)

        # 6. Instantiate models
        user = User(
            user_id=user_id,
            email=payload.email,
            password_hash=pwd_hash,
            role="patient",
            is_active=True,
        )

        height_dec = Decimal(str(payload.height_cm)) if payload.height_cm is not None else None
        weight_dec = Decimal(str(payload.weight_kg)) if payload.weight_kg is not None else None

        profile = PatientProfile(
            patient_id=patient_id,
            user_id=user_id,
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            date_of_birth=payload.date_of_birth,
            gender=payload.gender,
            height_cm=height_dec,
            weight_kg=weight_dec,
            contact_phone=payload.contact_phone.strip() if payload.contact_phone else None,
            emergency_contact=payload.emergency_contact.strip() if payload.emergency_contact else None,
        )

        # 7. Persist atomically
        self.user_repo.create_patient_user(user, profile)

        # 8. Log audit record (NEVER storing passwords or hashes)
        self.audit_repo.record(
            action="USER_REGISTRATION",
            target_type="users",
            target_id=user.user_id,
            actor_id=user.user_id,
            ip_address=ip_address,
            metadata_json=json.dumps({"role": "patient", "patient_id": patient_id}),
        )

        return user, profile

    def authenticate_user(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
    ) -> Tuple[User, str, int]:
        """
        Authenticate credentials and issue a signed JWT access token.
        Non-revealing error messages protect against account enumeration.
        """
        normalized_email = email.strip().lower()
        user = self.user_repo.get_by_email(normalized_email)

        # Verify password or fail safely with generic message
        if not user or not verify_password(password, user.password_hash):
            self.audit_repo.record(
                action="AUTH_LOGIN_FAILED",
                target_type="users",
                target_id=user.user_id if user else "UNKNOWN",
                actor_id=user.user_id if user else None,
                ip_address=ip_address,
                metadata_json=json.dumps({"reason": "invalid_credentials"}),
            )
            raise InvalidCredentialsError("Invalid email or password.")

        # Reject inactive/disabled accounts
        if not user.is_active:
            self.audit_repo.record(
                action="AUTH_LOGIN_BLOCKED",
                target_type="users",
                target_id=user.user_id,
                actor_id=user.user_id,
                ip_address=ip_address,
                metadata_json=json.dumps({"reason": "account_inactive"}),
            )
            raise AccountDisabledError("User account is inactive or disabled.")

        # Issue JWT with minimal claims
        claims = {
            "sub": user.user_id,
            "email": user.email,
            "role": user.role,
        }
        token = create_access_token(data=claims, settings=self.settings)
        expires_in = self.settings.access_token_expire_minutes * 60

        # Record successful authentication
        self.audit_repo.record(
            action="AUTH_LOGIN_SUCCESS",
            target_type="users",
            target_id=user.user_id,
            actor_id=user.user_id,
            ip_address=ip_address,
            metadata_json=json.dumps({"role": user.role}),
        )

        return user, token, expires_in

    def get_user_profile(self, user_id: str) -> User:
        """Fetch user by id or raise EntityNotFoundError."""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise EntityNotFoundError("User", user_id)
        return user
