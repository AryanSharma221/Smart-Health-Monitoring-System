"""
Database Engine and Session Lifecycle Management.

Provides connection pooling, session lifecycle scopes, and FastAPI dependency helpers
for MySQL 8 (InnoDB) with fail-safe fallbacks for testing.
"""

from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

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
    url = database_url or settings.get_mysql_url()

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


def check_db_connectivity(engine: Engine | None = None) -> bool:
    """
    Verify database connectivity using a lightweight SELECT 1 query.
    Returns True if healthy, False if unreachable or in error.
    """
    target_engine = engine or get_engine()
    try:
        with target_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", exc)
        return False
