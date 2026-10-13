"""
Smart Health Monitoring System — Central FastAPI Gateway.

Provides the primary API gateway for both React and Flutter clients.
Preserves non-destructive development: does not connect to databases at import time.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.config import Settings, get_settings

logger = logging.getLogger(__name__)


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

    return app


# Default ASGI application instance for Uvicorn
app = create_app()
