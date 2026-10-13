"""Authentication and access control package root."""

from services.auth.auth_service import AuthService
from services.auth.dependencies import (
    check_patient_access,
    get_current_doctor_profile,
    get_current_patient_profile,
    get_current_user,
    require_role,
    verify_patient_access,
)
from services.auth.exceptions import (
    AccountDisabledError,
    AuthError,
    InvalidCredentialsError,
    InvalidTokenError,
    PermissionDeniedError,
    PrivilegeEscalationError,
    TokenError,
    TokenExpiredError,
)
from services.auth.schemas import (
    DoctorProfileResponse,
    PatientProfileResponse,
    TokenResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
)
from services.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    validate_password_policy,
    verify_password,
)

__all__ = [
    "AuthService",
    "get_current_user",
    "require_role",
    "verify_patient_access",
    "check_patient_access",
    "get_current_patient_profile",
    "get_current_doctor_profile",
    "AuthError",
    "InvalidCredentialsError",
    "AccountDisabledError",
    "TokenError",
    "TokenExpiredError",
    "InvalidTokenError",
    "PermissionDeniedError",
    "PrivilegeEscalationError",
    "UserRegisterRequest",
    "UserLoginRequest",
    "TokenResponse",
    "PatientProfileResponse",
    "DoctorProfileResponse",
    "UserProfileResponse",
    "hash_password",
    "verify_password",
    "validate_password_policy",
    "create_access_token",
    "decode_access_token",
]
