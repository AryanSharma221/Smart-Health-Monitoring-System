"""
Smartwatch Sensor Simulator — Application Entry Point.

Standalone FastAPI microservice generating realistic, correlated synthetic wearable telemetry
for the Smart Health Monitoring System demonstration cohort (P101–P105).

CLINICAL SAFETY DISCLAIMER:
This service is a synthetic demonstration tool. It does NOT interface with real sensors
and MUST NOT be used for medical diagnosis, clinical decisions, or genuine triage.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import Any, Dict

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from simulator.config import SimulatorSettings, get_simulator_settings
from simulator.routes import get_generator, router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smartwatch_simulator")


@asynccontextmanager
async def simulator_lifespan(app: FastAPI):
    """
    Application lifespan context manager:
    - Automatically launches continuous generator on startup if configured.
    - Gracefully stops background generator and cleans up on shutdown.
    """
    settings: SimulatorSettings = app.state.settings
    generator = get_generator()
    logger.info("Initializing %s v%s", settings.service_name, settings.version)

    if settings.auto_start:
        logger.info("Auto-starting telemetry generator background worker...")
        await generator.start()

    yield

    logger.info("Shutting down %s: stopping generator worker...", settings.service_name)
    await generator.stop()
    logger.info("Simulator shutdown complete.")


def create_simulator_app(settings: SimulatorSettings | None = None) -> FastAPI:
    """Application factory for the simulator FastAPI instance."""
    app_settings = settings or get_simulator_settings()

    app = FastAPI(
        title=app_settings.service_name,
        description=(
            "Standalone synthetic wearable device sensor telemetry generator for the "
            "Smart Health Monitoring System demonstration cohort (P101–P105). "
            "SIMULATED DATA — NOT FOR MEDICAL USE."
        ),
        version=app_settings.version,
        lifespan=simulator_lifespan,
    )

    app.state.settings = app_settings
    if settings is not None:
        app.dependency_overrides[get_simulator_settings] = lambda: app_settings

    # Enable CORS for local dashboards and test runners
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root discovery endpoint
    @app.get("/", tags=["System"])
    def root_discovery(current_settings: SimulatorSettings = Depends(get_simulator_settings)) -> Dict[str, Any]:
        """Root discovery index identifying simulator status and endpoints."""
        return {
            "service": current_settings.service_name,
            "version": current_settings.version,
            "status": "online",
            "documentation": "/docs",
            "endpoints": {
                "health": "/health",
                "patients": "/api/v1/patients",
                "latest_readings": "/api/v1/readings/latest",
                "bounded_readings": "/api/v1/readings",
                "streaming_poll": "/api/v1/readings/stream",
                "simulator_status": "/api/v1/simulator/status",
                "simulator_start": "/api/v1/simulator/start",
                "simulator_stop": "/api/v1/simulator/stop",
                "simulator_scenario": "/api/v1/simulator/scenario",
            },
            "disclaimer": "SIMULATED TELEMETRY — NOT FOR MEDICAL USE OR CLINICAL DIAGNOSIS",
        }

    # Mount API routes
    app.include_router(router)

    return app


# Default ASGI application instance
app = create_simulator_app()


def run():
    """CLI runner executing Uvicorn with simulator settings."""
    settings = get_simulator_settings()
    uvicorn.run(
        "simulator.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
