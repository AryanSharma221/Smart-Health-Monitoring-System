"""
Authentication and Identity API Router.

Provides endpoints for patient registration, secure credential login,
safe profile inspection, and role/assignment verification.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database.mysql.exceptions import EntityConflictError
from database.mysql.models import User
from database.mysql.session import get_db, transaction_scope
from services.api.config import Settings, get_settings
from services.auth.auth_service import AuthService
from services.auth.dependencies import (
    get_current_user,
    require_role,
    verify_patient_access,
)
from services.auth.exceptions import (
    AccountDisabledError,
    InvalidCredentialsError,
    PrivilegeEscalationError,
)
from services.auth.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication & Identity"])


@router.post(
    "/register",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient account",
)
def register(
    payload: UserRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """
    Public self-registration endpoint restricted strictly to patient accounts.
    Privileged accounts (doctor, admin_operator) must be provisioned through administration.
    """
    client_ip = request.client.host if request.client else None

    try:
        with transaction_scope(db) as session:
            auth_service = AuthService(session, settings=settings)
            user, _ = auth_service.register_patient(payload, ip_address=client_ip)
            return user
    except PrivilegeEscalationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except EntityConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive JWT access token",
)
def login(
    payload: UserLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """
    Authenticate email and password credentials.
    Returns a signed JWT bearer token with expiry details.
    """
    client_ip = request.client.host if request.client else None

    try:
        with transaction_scope(db) as session:
            auth_service = AuthService(session, settings=settings)
            user, token, expires_in = auth_service.authenticate_user(
                email=payload.email,
                password=payload.password,
                ip_address=client_ip,
            )
            return TokenResponse(
                access_token=token,
                token_type="bearer",
                expires_in=expires_in,
                user_id=user.user_id,
                role=user.role,
            )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AccountDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or disabled.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.get(
    "/me",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve current user's safe identity profile",
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Return the authenticated user's safe profile, effective role, and active status.
    Omits passwords, hashes, and internal secrets.
    """
    return current_user


@router.get(
    "/verify-patient-access/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Verify patient ownership or clinician assignment",
)
def verify_patient_access_endpoint(
    patient_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Test endpoint verifying authorization against a patient ID.
    Enforces that patients access only their own records and doctors only assigned patients.
    """
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)
    return {
        "patient_id": patient_id,
        "authorized": True,
        "user_id": current_user.user_id,
        "role": current_user.role,
    }


@router.get(
    "/verify-admin-access",
    status_code=status.HTTP_200_OK,
    summary="Verify administrative role enforcement",
)
def verify_admin_access_endpoint(
    current_user: User = Depends(require_role("admin_operator")),
) -> Dict[str, Any]:
    """Test endpoint verifying admin_operator access control."""
    return {
        "admin": True,
        "user_id": current_user.user_id,
        "role": current_user.role,
    }


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Log out and record audit event",
)
def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Log out the current authenticated user and record audit log.
    Client should discard its stored access token.
    """
    from database.mysql.repositories.audit_repository import AuditRepository

    with transaction_scope(db) as session:
        audit_repo = AuditRepository(session)
        audit_repo.record(
            action="AUTH_LOGOUT",
            target_type="users",
            target_id=current_user.user_id,
            actor_id=current_user.user_id,
            metadata_json=f'{{"role": "{current_user.role}"}}',
        )
    return {
        "status": "success",
        "message": "User logged out successfully.",
        "user_id": current_user.user_id,
    }

