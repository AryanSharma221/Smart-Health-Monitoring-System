"""
Application-Specific Database and Persistence Exceptions.

Provides clean error classification decoupled from raw driver/SQLAlchemy exceptions,
preventing raw database details or credentials from bubbling up to API responses.
"""

from __future__ import annotations


class DatabaseError(Exception):
    """Base exception for all database and persistence operations."""
    def __init__(self, message: str, original_exception: Exception | None = None) -> None:
        super().__init__(message)
        self.original_exception = original_exception


class DatabaseConnectionError(DatabaseError):
    """Raised when the database host or service is unreachable or refused connection."""
    pass


class EntityNotFoundError(DatabaseError):
    """Raised when an expected domain record cannot be found."""
    def __init__(
        self,
        entity_name: str,
        identifier: object,
        original_exception: Exception | None = None,
    ) -> None:
        super().__init__(f"{entity_name} with identifier '{identifier}' was not found.", original_exception=original_exception)
        self.entity_name = entity_name
        self.identifier = identifier


class EntityConflictError(DatabaseError):
    """Raised when a unique constraint, composite key, or duplicate conflict occurs."""
    def __init__(
        self,
        message: str,
        conflict_key: str | None = None,
        original_exception: Exception | None = None,
    ) -> None:
        super().__init__(message, original_exception=original_exception)
        self.conflict_key = conflict_key


class InvalidStateTransitionError(DatabaseError):
    """Raised when an entity lifecycle change violates business rules (e.g. resolving a resolved alert)."""
    def __init__(self, message: str, original_exception: Exception | None = None) -> None:
        super().__init__(message, original_exception=original_exception)
