"""
Database Engine, Connection Pooling, and Session Lifecycle Management.

Provides:
- Production connection pooling for MySQL 8 (InnoDB).
- Safe SQLite fallbacks for testing and local validation.
- Transactional context manager (transaction_scope) with automatic rollback on error.
- FastAPI dependency generator (get_db).
- Safe connection health checks without credential exposure.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from database.mysql.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    EntityConflictError,
)
from starlette.exceptions import HTTPException
from services.api.config import get_settings

logger = logging.getLogger(__name__)

# Global singletons for runtime reuse
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine(database_url: str | None = None) -> Engine:
    """
    Retrieve or initialize the SQLAlchemy database engine with production connection pooling.
    
    If no database_url is passed, the MySQL URL from Settings is used.
    For SQLite (unit testing), pooling parameters are adjusted accordingly.
    """
    global _engine
    if _engine is not None and database_url is None:
        return _engine

    settings = get_settings()
    url = database_url or settings.database_url or settings.get_mysql_url()

    # Determine if SQLite or MySQL
    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=settings.app_debug,
        )
    else:
        # MySQL production pooling
        engine = create_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={"connect_timeout": settings.mysql_connect_timeout},
            echo=settings.app_debug,
        )

    if database_url is None:
        _engine = engine
    return engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Retrieve or initialize the sessionmaker bound to the configured engine."""
    global _session_factory
    if _session_factory is not None and engine is None:
        return _session_factory

    target_engine = engine or get_engine()
    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=target_engine,
        expire_on_commit=False,
    )

    if engine is None:
        _session_factory = factory
    return factory


def dispose_engine() -> None:
    """Dispose the current engine and reset singleton references (used for teardown/testing)."""
    global _engine, _session_factory
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception as exc:
            logger.warning("Error disposing engine: %s", exc)
        _engine = None
    _session_factory = None


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session per request.
    Automatically closes the session upon request completion.
    """
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction_scope(session: Session | None = None) -> Generator[Session, None, None]:
    """
    Provide an explicit transactional boundary around a sequence of operations.
    
    If an external session is passed, executes within that session.
    If no session is passed, manages session creation and destruction cleanly.
    Commits on clean exit, rolls back on exception, and translates driver errors.
    """
    owns_session = session is None
    s = session if session is not None else get_session_factory()()

    try:
        yield s
        s.commit()
    except IntegrityError as exc:
        s.rollback()
        logger.warning("Database integrity constraint violation: %s", exc.orig if hasattr(exc, "orig") else exc)
        raise EntityConflictError("Database constraint violation", original_exception=exc) from exc
    except (OperationalError, DBAPIError) as exc:
        s.rollback()
        logger.error("Database operational or connection error during transaction: %s", exc)
        raise DatabaseConnectionError("Database operation failed due to a connection or server error", original_exception=exc) from exc
    except (DatabaseError, HTTPException):
        s.rollback()
        raise
    except Exception as exc:
        s.rollback()
        logger.error("Unexpected error in database transaction: %s", exc)
        raise DatabaseError(f"Database transaction failed: {exc}", original_exception=exc) from exc
    finally:
        if owns_session:
            s.close()


def check_db_connectivity(engine: Engine | None = None) -> bool:
    """
    Verify database connectivity using a lightweight SELECT 1 query.
    Returns True if healthy, False if unreachable or in error.
    Never exposes passwords or sensitive credentials in logs.
    """
    target_engine = engine or get_engine()
    try:
        with target_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", exc)
        return False
