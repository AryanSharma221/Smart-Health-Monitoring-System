"""
Authentication and Authorization Domain Exceptions.

Inherits from DatabaseError to cleanly propagate through transaction_scope
and ensure session rollbacks without masking domain violations.
"""

from __future__ import annotations

from typing import Optional

from database.mysql.exceptions import DatabaseError


class AuthError(DatabaseError):
    """Base exception for authentication and authorization errors."""

    def __init__(self, message: str, original_exception: Optional[Exception] = None) -> None:
        super().__init__(message, original_exception=original_exception)
        self.message = message


class InvalidCredentialsError(AuthError):
    """Raised when authentication credentials (email/password) are incorrect or account inactive."""
    pass


class AccountDisabledError(AuthError):
    """Raised when an account is disabled or suspended."""
    pass


class TokenError(AuthError):
    """Base exception for JWT processing failures."""
    pass


class TokenExpiredError(TokenError):
    """Raised when an authentication token has expired."""
    pass


class InvalidTokenError(TokenError):
    """Raised when a token signature is invalid, malformed, or missing required claims."""
    pass


class PermissionDeniedError(AuthError):
    """Raised when a user attempts an action not permitted by their role or assignment."""
    pass


class PrivilegeEscalationError(AuthError):
    """Raised when an unauthorized role assignment or elevation is attempted."""
    pass
