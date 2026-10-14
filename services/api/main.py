"""
Smart Health Monitoring System — Central FastAPI Gateway.

Provides the primary API gateway for both React and Flutter clients.
Preserves non-destructive development: does not connect to databases at import time.
Provides session dependencies and connection lifecycle cleanup via lifespan.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database.mongodb.client import (
    check_mongo_connectivity,
    close_mongo_client,
    sanitize_mongo_uri,
)
from database.mysql.models import User
from database.mysql.repositories.outbox_repository import OutboxRepository
from database.mysql.session import check_db_connectivity, dispose_engine, get_db
from services.api.config import Settings, get_settings
from services.auth.dependencies import get_current_user
from services.auth.schemas import UserProfileResponse
from services.api.routes.alerts import router as alerts_router
from services.api.routes.auth import router as auth_router
from services.api.routes.conversations import router as conversations_router
from services.api.routes.predictions import router as predictions_router
from services.api.routes.readings import router as readings_router
from services.api.routes.websocket import router as ws_router
from services.ml_service import get_ml_service
from services.websocket.manager import connection_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Application lifespan context manager managing startup and resource disposal."""
    logger.info("Initializing Smart Health Monitoring System API Gateway")
    
    # Initialize ML service once during startup (loads IsolationForest and frozen baselines)
    try:
        settings = getattr(app.state, "settings", None) or get_settings()
        ml_service = get_ml_service(settings)
        if ml_service.is_available:
            logger.info("ML Anomaly Detection service ready (IsolationForest v%s)", ml_service.model_version)
        else:
            logger.warning("ML Anomaly Detection service degraded: %s", ml_service.degraded_reason)
    except Exception as exc:
        logger.warning("ML service initialization encountered non-fatal error: %s", exc)

    yield
    logger.info("Shutting down API Gateway: releasing resources")
    await connection_manager.close_all()
    dispose_engine()
    close_mongo_client()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory for FastAPI instance."""
    app_settings = settings or get_settings()

    app = FastAPI(
        title=app_settings.app_name,
        description=(
            "Central API gateway for the AI-Powered Smart Health Monitoring System. "
            "Simulated health telemetry demonstration — NOT FOR MEDICAL USE."
        ),
        version="3.0.0",
        debug=app_settings.app_debug,
        lifespan=app_lifespan,
    )

    app.state.settings = app_settings
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: app_settings

    # Configure Cross-Origin Resource Sharing
    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health", tags=["System"])
    async def health_check(
        current_settings: Settings = Depends(get_settings),
    ) -> Dict[str, Any]:
        """
        Lightweight health check endpoint.
        Returns application status, version, environment, and simulated data notice.
        """
        return {
            "status": "healthy",
            "service": current_settings.app_name,
            "version": "3.0.0",
            "environment": current_settings.app_env,
            "is_simulated": True,
            "notice": "SIMULATED DATA — NOT FOR MEDICAL USE",
        }

    @app.get("/health/live", tags=["System"])
    async def liveness_check(
        current_settings: Settings = Depends(get_settings),
    ) -> Dict[str, Any]:
        """
        Process liveness probe for container orchestrators and supervisors.
        Verifies that the ASGI event loop and application process are running.
        Does not query external network dependencies.
        """
        return {
            "status": "alive",
            "service": current_settings.app_name,
            "version": "3.0.0",
        }

    @app.get("/health/ready", tags=["System"])
    def readiness_check(
        response: Response,
        current_settings: Settings = Depends(get_settings),
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        """
        Operational readiness probe for container orchestrators and load balancers.
        - Requires authoritative MySQL connectivity to accept traffic.
        - Reports optional MongoDB analytics mirror status without gating readiness.
        - Returns 200 OK when ready to serve; returns 503 Service Unavailable when MySQL is down.
        """
        db_connected = check_db_connectivity(db.get_bind())
        if not db_connected:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "unready",
                "database": "unreachable",
                "message": "Authoritative relational database is unavailable.",
            }

        is_mongo_connected, mongo_desc = check_mongo_connectivity(current_settings)
        mongo_status = "connected" if is_mongo_connected else ("unconfigured" if not current_settings.mongodb_uri else "degraded")

        return {
            "status": "ready",
            "database": "connected",
            "mongodb_mirror": mongo_status,
            "message": "Authoritative database operational. Ready to serve traffic.",
        }

    @app.get("/health/db", tags=["System"])
    def db_health_check(
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        """
        Database connectivity health probe.
        Exercises the FastAPI get_db dependency and verifies live connectivity.
        """
        connected = check_db_connectivity(db.get_bind())
        return {
            "status": "connected" if connected else "unreachable",
            "database": "mysql_innodb",
        }

    @app.get("/health/mongodb", tags=["System"])
    def mongodb_health_check(
        current_settings: Settings = Depends(get_settings),
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        """
        MongoDB Atlas connectivity and analytics outbox health probe.
        Redacts credentials; never leaks sensitive data.
        """
        is_connected, desc = check_mongo_connectivity(current_settings)
        outbox_repo = OutboxRepository(db)
        stats = outbox_repo.get_outbox_stats()
        return {
            "status": "connected" if is_connected else desc,
            "database": current_settings.mongodb_database,
            "endpoint": sanitize_mongo_uri(current_settings.mongodb_uri),
            "outbox_queue": stats,
        }

    @app.get("/me", response_model=UserProfileResponse, tags=["Authentication & Identity"])
    @app.get(f"{app_settings.api_v1_prefix}/me", response_model=UserProfileResponse, tags=["Authentication & Identity"])
    def get_me_direct(current_user: User = Depends(get_current_user)) -> User:
        """Alias for /auth/me to support direct root and versioned identity profile queries."""
        return current_user

    # Mount Authentication and Identity Routers (both /api/v1/auth and /auth)
    app.include_router(auth_router, prefix=app_settings.api_v1_prefix)
    app.include_router(auth_router)

    # Mount Patient Health Readings Routers (both /api/v1/patients and /patients)
    app.include_router(readings_router, prefix=app_settings.api_v1_prefix)
    app.include_router(readings_router)

    # Mount Clinical Alerts Routers (both /api/v1 and root)
    app.include_router(alerts_router, prefix=app_settings.api_v1_prefix)
    app.include_router(alerts_router)

    # Mount Clinical Conversations and Messaging Routers (both /api/v1 and root)
    app.include_router(conversations_router, prefix=app_settings.api_v1_prefix)
    app.include_router(conversations_router)

    # Mount Real-Time WebSockets Router (both /api/v1 and root)
    app.include_router(ws_router, prefix=app_settings.api_v1_prefix)
    app.include_router(ws_router)

    # Mount Machine Learning Predictions and Assessments Router (both /api/v1 and root)
    app.include_router(predictions_router, prefix=app_settings.api_v1_prefix)
    app.include_router(predictions_router)

    return app


# Default ASGI application instance for Uvicorn
app = create_app()
