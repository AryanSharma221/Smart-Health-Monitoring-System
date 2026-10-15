"""
FastAPI Routes and Controller Endpoints for the Smartwatch Sensor Simulator.

Provides:
- GET  /health: Simulator service health, uptime, and clinical disclaimer.
- GET  /api/v1/patients: Configured demo patient identifiers (P101–P105) and baseline traits.
- GET  /api/v1/readings/latest: Most recent reading for each patient.
- GET  /api/v1/readings: Bounded list of recent observations with optional patient filtering.
- GET  /api/v1/readings/stream: Polling-friendly cursor endpoint for lossless downstream ingestion.
- POST /api/v1/simulator/start: Idempotent launch of the background generator task.
- POST /api/v1/simulator/stop: Safe, clean cessation of the background generation worker.
- GET  /api/v1/simulator/status: Operational telemetry status, buffer capacity, and timestamps.
- POST /api/v1/simulator/scenario: Controls for 'normal' vs 'alert_test' demonstration modes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from simulator.config import SimulatorSettings, get_simulator_settings
from simulator.generator import PATIENT_BASELINES, TelemetryGenerator
from simulator.models import (
    BoundedReadingsResponse,
    ControlActionResponse,
    InterruptionRequest,
    LatestReadingsResponse,
    PatientsListResponse,
    PollingStreamResponse,
    ScenarioUpdateRequest,
    SimulatorHealthResponse,
    SimulatorStatusResponse,
)

router = APIRouter(tags=["Smartwatch Sensor Simulator"])

# Global singleton generator instance
_GENERATOR_INSTANCE: Optional[TelemetryGenerator] = None


def get_generator() -> TelemetryGenerator:
    """Retrieve or initialize generator instance."""
    global _GENERATOR_INSTANCE
    if _GENERATOR_INSTANCE is None:
        _GENERATOR_INSTANCE = TelemetryGenerator()
    return _GENERATOR_INSTANCE


def set_generator_instance(generator: TelemetryGenerator) -> None:
    """Allow injecting a generator instance for testing."""
    global _GENERATOR_INSTANCE
    _GENERATOR_INSTANCE = generator


def verify_control_access(
    request: Request,
    x_simulator_key: Optional[str] = Header(None, alias="X-Simulator-Key"),
    settings: SimulatorSettings = Depends(get_simulator_settings),
) -> None:
    """
    Security guard protecting simulator-control endpoints from unauthorized access
    outside the intended demonstration environment.
    """
    if settings.control_secret:
        if not x_simulator_key or x_simulator_key != settings.control_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Valid X-Simulator-Key header required to control simulator execution.",
            )


# =============================================================================
# Health & Status Endpoints
# =============================================================================

@router.get("/health", response_model=SimulatorHealthResponse, tags=["Health"])
def get_health(
    generator: TelemetryGenerator = Depends(get_generator),
    settings: SimulatorSettings = Depends(get_simulator_settings),
) -> SimulatorHealthResponse:
    """
    Return simulator service status, version, uptime, and simulated telemetry notice.
    """
    uptime = round(time.time() - generator.start_time, 2)
    return SimulatorHealthResponse(
        status="healthy",
        service=settings.service_name,
        version=settings.version,
        uptime_seconds=uptime,
        generator_running=generator.is_running,
    )


# =============================================================================
# Patient Roster Endpoints
# =============================================================================

@router.get("/api/v1/patients", response_model=PatientsListResponse, tags=["Patients"])
def list_demo_patients(
    settings: SimulatorSettings = Depends(get_simulator_settings),
) -> PatientsListResponse:
    """
    Return configured demo patient identifiers (P101–P105) and their baseline characteristics.
    """
    details = [
        PATIENT_BASELINES.get(pid)
        for pid in settings.demo_patients
        if pid in PATIENT_BASELINES
    ]
    return PatientsListResponse(
        patients=settings.demo_patients,
        details=[d for d in details if d is not None],
        count=len(settings.demo_patients),
    )


# =============================================================================
# Telemetry Readings Endpoints
# =============================================================================

@router.get("/api/v1/readings/latest", response_model=LatestReadingsResponse, tags=["Readings"])
def get_latest_readings(
    generator: TelemetryGenerator = Depends(get_generator),
) -> LatestReadingsResponse:
    """
    Return the most recent generated reading for each patient in the demo cohort.
    If no readings have been generated yet, immediately produces an initial cycle.
    """
    latest = generator.get_latest_readings()
    if not latest:
        # Auto-seed first cycle if empty so caller receives valid initial data
        generator.generate_cycle()
        latest = generator.get_latest_readings()

    return LatestReadingsResponse(
        readings=latest,
        count=len(latest),
        timestamp_utc=datetime.now(timezone.utc),
    )


@router.get("/api/v1/readings", response_model=BoundedReadingsResponse, tags=["Readings"])
def list_readings(
    patient_id: Optional[str] = Query(None, description="Filter readings by patient ID (e.g., 'P101')"),
    limit: int = Query(50, ge=1, le=500, description="Max observations to return (1-500)"),
    generator: TelemetryGenerator = Depends(get_generator),
    settings: SimulatorSettings = Depends(get_simulator_settings),
) -> BoundedReadingsResponse:
    """
    Return a bounded list of recent telemetry observations, sorted newest-first.
    """
    if patient_id and patient_id not in settings.demo_patients:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient '{patient_id}' is not in configured simulator cohort {settings.demo_patients}.",
        )

    items = generator.get_bounded_readings(patient_id=patient_id, limit=limit)
    return BoundedReadingsResponse(
        items=items,
        count=len(items),
        total_buffer_count=generator.buffer_count,
        limit=limit,
        filter_patient_id=patient_id,
    )


@router.get("/api/v1/readings/stream", response_model=PollingStreamResponse, tags=["Readings"])
def stream_readings(
    cursor: Optional[str] = Query(
        None,
        description="Event ID or sequential cursor from previous poll. Returns items generated after this cursor.",
    ),
    limit: int = Query(50, ge=1, le=200, description="Max items to receive in this batch (1-200)"),
    generator: TelemetryGenerator = Depends(get_generator),
) -> PollingStreamResponse:
    """
    Documented polling-friendly endpoint that returns newly generated readings after
    a supplied cursor or event ID, with bounded result sizes.
    Ensures backend ingestion pipelines never duplicate or skip readings.
    """
    return generator.poll_stream(cursor=cursor, limit=limit)


# =============================================================================
# Simulator Lifecycle & Scenario Control Endpoints
# =============================================================================

@router.post(
    "/api/v1/simulator/start",
    response_model=ControlActionResponse,
    dependencies=[Depends(verify_control_access)],
    tags=["Control"],
)
async def start_simulator(
    generator: TelemetryGenerator = Depends(get_generator),
) -> ControlActionResponse:
    """
    Start the background generator if it is not already running.
    Prevents duplicate background tasks when called multiple times.
    """
    started = await generator.start()
    msg = (
        "Smartwatch telemetry background generation started successfully."
        if started
        else "Simulator is already actively running (no action taken)."
    )
    return ControlActionResponse(
        message=msg,
        is_running=generator.is_running,
        lifecycle_state=generator.lifecycle_state,
        timestamp_utc=datetime.now(timezone.utc),
    )


@router.post(
    "/api/v1/simulator/stop",
    response_model=ControlActionResponse,
    dependencies=[Depends(verify_control_access)],
    tags=["Control"],
)
async def stop_simulator(
    generator: TelemetryGenerator = Depends(get_generator),
) -> ControlActionResponse:
    """
    Stop continuous generation safely and await worker task termination immediately.
    """
    stopped = await generator.stop()
    msg = (
        "Smartwatch telemetry generator stopped gracefully."
        if stopped
        else "Simulator was not running (no action taken)."
    )
    return ControlActionResponse(
        message=msg,
        is_running=generator.is_running,
        lifecycle_state=generator.lifecycle_state,
        timestamp_utc=datetime.now(timezone.utc),
    )


@router.get("/api/v1/simulator/status", response_model=SimulatorStatusResponse, tags=["Control"])
def get_simulator_status(
    generator: TelemetryGenerator = Depends(get_generator),
    settings: SimulatorSettings = Depends(get_simulator_settings),
) -> SimulatorStatusResponse:
    """
    Return whether generation is running, the configured interval, patient states, and timestamps.
    """
    return SimulatorStatusResponse(
        is_running=generator.is_running,
        lifecycle_state=generator.lifecycle_state,
        interval_seconds=settings.interval_seconds,
        current_scenario=generator.current_scenario,
        configured_patients=settings.demo_patients,
        total_readings_generated=generator.total_readings_generated,
        buffer_capacity=settings.max_history_records,
        buffer_used=generator.buffer_count,
        latest_generation_at=generator.latest_generation_timestamp,
        patient_states=generator.get_patient_states(),
        interrupted_patients=generator.get_interrupted_patients(),
        active_patients=generator.get_active_patients(),
    )


@router.post(
    "/api/v1/simulator/interruption",
    response_model=ControlActionResponse,
    dependencies=[Depends(verify_control_access)],
    tags=["Control"],
)
def set_simulator_interruption(
    payload: InterruptionRequest,
    generator: TelemetryGenerator = Depends(get_generator),
    settings: SimulatorSettings = Depends(get_simulator_settings),
) -> ControlActionResponse:
    """
    Simulate wearable signal loss or recovery for demo testing.
    When interrupted, the device ceases producing readings while preserving past data.
    """
    if payload.patient_id and payload.patient_id not in settings.demo_patients:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient '{payload.patient_id}' not found in cohort {settings.demo_patients}.",
        )

    interrupted_list = generator.set_interruption(payload.patient_id, payload.interrupted)
    target_str = payload.patient_id or "cohort"
    status_str = "interrupted (offline)" if payload.interrupted else "resumed (online)"
    return ControlActionResponse(
        message=f"Signal transmission {status_str} for {target_str}. Reason: {payload.reason}.",
        is_running=generator.is_running,
        timestamp_utc=datetime.now(timezone.utc),
        interrupted_patients=interrupted_list,
    )


@router.post(
    "/api/v1/simulator/scenario",
    response_model=ControlActionResponse,
    dependencies=[Depends(verify_control_access)],
    tags=["Control"],
)
def set_simulator_scenario(
    payload: ScenarioUpdateRequest,
    generator: TelemetryGenerator = Depends(get_generator),
    settings: SimulatorSettings = Depends(get_simulator_settings),
) -> ControlActionResponse:
    """
    Configure demonstration scenario:
    - 'normal'/'resting': gradual, ordinary synthetic physiological drift across all patients.
    - 'active': elevated physical activity exertion with gradual heart rate climb.
    - 'recovering': exponential recovery toward baseline resting levels.
    - 'signal_interruption': pauses transmission for target patient or cohort.
    - 'alert_test': predefined synthetic anomaly designed to verify the existing alert pipeline.
    """
    if payload.target_patient_id and payload.target_patient_id not in settings.demo_patients:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient '{payload.target_patient_id}' not found in cohort {settings.demo_patients}.",
        )

    generator.set_scenario(payload)
    # Generate an immediate cycle so the new scenario state takes effect immediately in latest readings
    generator.generate_cycle()
    target_str = payload.target_patient_id or "cohort"
    return ControlActionResponse(
        message=f"Simulation scenario transitioned to '{payload.scenario}' for {target_str} (metric: {payload.alert_metric}).",
        is_running=generator.is_running,
        timestamp_utc=datetime.now(timezone.utc),
        interrupted_patients=generator.get_interrupted_patients(),
    )
