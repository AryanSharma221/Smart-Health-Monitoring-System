"""
FastAPI Authentication and Authorization Dependencies.

Enforces server-side security checks:
1. Token validation and user resolution.
2. Inactive account blocking.
3. Role-based access control guards.
4. Patient ownership and clinician care-assignment verifications.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database.mysql.models import DoctorProfile, PatientProfile, User
from database.mysql.repositories.patient_repository import PatientRepository
from database.mysql.repositories.user_repository import UserRepository
from database.mysql.session import get_db
from services.api.config import Settings, get_settings
from services.auth.exceptions import TokenError
from services.auth.security import decode_access_token

logger = logging.getLogger(__name__)

# Security scheme for FastAPI OpenAPI docs and Bearer extraction
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """
    Validate incoming Bearer JWT and resolve authenticated active User entity.
    Never trusts client-supplied headers or claim overrides without signature verification.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials, settings=settings)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials: token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(db)
    user = user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User identity associated with token no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or disabled.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Optional[User]:
    """
    Attempt to resolve User if valid Bearer credentials are provided, but return None
    rather than raising 401 when unauthenticated.
    """
    if not credentials or not credentials.credentials:
        return None

    try:
        payload = decode_access_token(credentials.credentials, settings=settings)
        user_id = payload.get("sub")
        if not user_id:
            return None
        user_repo = UserRepository(db)
        user = user_repo.get_by_id(user_id)
        if user and user.is_active:
            return user
        return None
    except Exception:
        return None


def require_role(*allowed_roles: str) -> Callable[[User], User]:
    """
    Factory creating a dependency that enforces server-side role check.
    Rejects unauthorized roles with 403 Forbidden.
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                "Access forbidden: user %s has role '%s', required: %s",
                current_user.user_id,
                current_user.role,
                allowed_roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Operation requires one of the following roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


def verify_patient_access(
    patient_id: str,
    current_user: User,
    db: Session,
) -> bool:
    """
    Enforce patient record authorization rules:
    1. Patient: Can access only their own record (matched via patient_profile.patient_id).
    2. Clinician: Can access only patients with an active DoctorPatientAssignment.
    3. Admin (admin_operator): Full compliance and operational audit access.
    """
    if current_user.role == "patient":
        profile = current_user.patient_profile
        if not profile or profile.patient_id != patient_id:
            logger.warning(
                "Patient %s attempted unauthorized access to patient record %s",
                current_user.user_id,
                patient_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You can only access your own patient records.",
            )
        return True

    if current_user.role == "doctor":
        doc_profile = current_user.doctor_profile
        if not doc_profile:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Clinician profile is not established.",
            )

        patient_repo = PatientRepository(db)
        is_assigned = patient_repo.is_doctor_assigned_to_patient(
            doctor_id=doc_profile.doctor_id,
            patient_id=patient_id,
        )
        if not is_assigned:
            logger.warning(
                "Doctor %s (%s) attempted access to unassigned patient %s",
                current_user.user_id,
                doc_profile.doctor_id,
                patient_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Clinician is not assigned to this patient.",
            )
        return True

    if current_user.role == "admin_operator":
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: Unauthorized role for patient data access.",
    )


def check_patient_access(
    patient_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> str:
    """FastAPI path dependency checking patient access and returning verified patient_id."""
    verify_patient_access(patient_id, current_user, db)
    return patient_id


def get_current_patient_profile(
    current_user: User = Depends(get_current_user),
) -> PatientProfile:
    """Ensure authenticated user is a patient and return their PatientProfile."""
    if current_user.role != "patient" or not current_user.patient_profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Authenticated user is not a registered patient.",
        )
    return current_user.patient_profile


def get_current_doctor_profile(
    current_user: User = Depends(get_current_user),
) -> DoctorProfile:
    """Ensure authenticated user is a clinician and return their DoctorProfile."""
    if current_user.role != "doctor" or not current_user.doctor_profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Authenticated user is not a registered clinician.",
        )
    return current_user.doctor_profile
