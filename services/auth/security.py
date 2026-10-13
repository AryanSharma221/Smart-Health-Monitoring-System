"""
Cryptographic and Security Utilities.

Provides password hashing via bcrypt (rounds=12) and JWT token generation/verification
via PyJWT using timezone-aware UTC timestamps and explicit algorithm verification.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import bcrypt
import jwt

from services.api.config import Settings, get_settings
from services.auth.exceptions import (
    InvalidTokenError,
    TokenExpiredError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Password Security (bcrypt)
# =============================================================================

def validate_password_policy(password: str) -> Tuple[bool, str]:
    """
    Validate password against security policy rules.
    - Max 72 bytes (safe upper bound for bcrypt)
    - Min 8 characters
    - At least 1 alphabetic character
    - At least 1 numeric character
    """
    if not password:
        return False, "Password cannot be empty."

    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        return False, "Password cannot exceed 72 bytes in length."

    if len(password) < 8:
        return False, "Password must be at least 8 characters in length."

    has_alpha = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)

    if not has_alpha:
        return False, "Password must contain at least one letter."
    if not has_digit:
        return False, "Password must contain at least one digit."

    return True, "Password meets complexity requirements."


def hash_password(plain_password: str, rounds: int = 12) -> str:
    """
    Hash a plaintext password using bcrypt with recommended 12 rounds of salt.
    Never stores or logs plaintext passwords.
    """
    valid, msg = validate_password_policy(plain_password)
    if not valid:
        raise ValueError(msg)

    salt = bcrypt.gensalt(rounds=max(4, min(31, rounds)))
    hashed_bytes = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored bcrypt hash.
    Safe against timing attacks and handles malformed hashes cleanly.
    """
    if not plain_password or not hashed_password:
        return False

    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


# =============================================================================
# Token Management (PyJWT)
# =============================================================================

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
    settings: Optional[Settings] = None,
) -> str:
    """
    Generate a signed JWT access token with standard claims.
    Uses UTC timestamps for iat, nbf, and exp.
    """
    cfg = settings or get_settings()
    now_utc = datetime.now(timezone.utc)

    if expires_delta:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + timedelta(minutes=cfg.access_token_expire_minutes)

    to_encode = data.copy()
    to_encode.update({
        "iat": int(now_utc.timestamp()),
        "nbf": int(now_utc.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": "smart-health-monitoring-api",
        "jti": str(uuid.uuid4()),
    })

    encoded_jwt = jwt.encode(
        to_encode,
        cfg.jwt_secret,
        algorithm=cfg.jwt_algorithm,
    )
    return encoded_jwt


def decode_access_token(
    token: str,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """
    Decode and validate a JWT access token.
    Validates expiration, required claims, and signature algorithm explicitly.
    """
    cfg = settings or get_settings()

    try:
        payload = jwt.decode(
            token,
            cfg.jwt_secret,
            algorithms=[cfg.jwt_algorithm],
            options={
                "require": ["exp", "sub"],
                "verify_exp": True,
                "verify_iat": True,
            },
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("Token has expired.") from e
    except jwt.PyJWTError as e:
        raise InvalidTokenError("Invalid token or signature.") from e

    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise InvalidTokenError("Token missing valid subject claim.")

    return payload
