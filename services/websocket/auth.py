"""
WebSocket Authentication and Subscription Authorization Guards.

Reuses the central JWT authentication and patient-clinician RBAC rules:
1. Validates token signature, expiration, and user active status.
2. Enforces patient ownership: patients can only subscribe to their own patient ID.
3. Enforces clinician assignments: clinicians can only subscribe to assigned patients.
4. Admin operators have system-wide operational visibility.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from database.mysql.models import User
from database.mysql.repositories.patient_repository import PatientRepository
from database.mysql.repositories.user_repository import UserRepository
from services.api.config import Settings
from services.auth.exceptions import TokenError
from services.auth.security import decode_access_token

logger = logging.getLogger(__name__)


def authenticate_websocket_token(
    token: str,
    db: Session,
    settings: Settings,
) -> Optional[User]:
    """
    Validate JWT token string and resolve the active User entity.
    Returns None if token is invalid, expired, or user is inactive.
    """
    if not token:
        return None

    try:
        payload = decode_access_token(token, settings=settings)
    except TokenError as exc:
        logger.debug("WebSocket token decoding failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error during WebSocket token decode: %s", exc)
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    user_repo = UserRepository(db)
    user = user_repo.get_by_id(user_id)
    if not user or not user.is_active:
        return None

    return user


def check_subscription_permission(
    user: User,
    patient_id: str,
    db: Session,
) -> Tuple[bool, str]:
    """
    Check whether an authenticated user is authorized to subscribe to patient_id events.
    Returns (is_authorized, reason).
    """
    if not user.is_active:
        return False, "User account is inactive or disabled."

    if user.role == "admin_operator":
        return True, "Authorized as administrative operator."

    if user.role == "patient":
        profile = getattr(user, "patient_profile", None)
        if profile and profile.patient_id == patient_id:
            return True, "Authorized: Patient accessing own telemetry stream."
        return False, f"Access denied: You may only subscribe to your own records (assigned patient: {getattr(profile, 'patient_id', 'none')})."

    if user.role == "doctor":
        doc_profile = getattr(user, "doctor_profile", None)
        if not doc_profile:
            return False, "Access denied: Clinician profile is not configured."

        patient_repo = PatientRepository(db)
        is_assigned = patient_repo.is_doctor_assigned_to_patient(
            doctor_id=doc_profile.doctor_id,
            patient_id=patient_id,
        )
        if is_assigned:
            return True, f"Authorized: Active care assignment for patient {patient_id}."
        return False, f"Access denied: Doctor {doc_profile.doctor_id} is not assigned to patient {patient_id}."

    return False, f"Access denied: Role '{user.role}' has no subscription privileges."
