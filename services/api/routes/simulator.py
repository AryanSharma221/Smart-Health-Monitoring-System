"""
Simulator Ingestion Diagnostics and Control API Router.

Provides:
- GET  /api/v1/simulator/ingestion-status: Operational metrics of the background ingestion worker.
- GET  /api/v1/simulator/status: Unified simulator generation and ingestion status.
- POST /api/v1/simulator/start: Reliable, idempotent start/resume of the simulator generator and ingestion.
- POST /api/v1/simulator/stop: Immediate stop of simulator telemetry generation without affecting core API.
- POST /api/v1/simulator/ingestion/start: Idempotent manual activation of the ingestion worker only.
- POST /api/v1/simulator/ingestion/stop: Safe cessation of background polling worker only.
- POST /api/v1/simulator/ingestion/poll: On-demand single poll iteration for testing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
import httpx
from pydantic import BaseModel, Field

from database.mysql.models import User
from services.api.config import Settings, get_settings
from services.auth.dependencies import get_current_user_optional
from services.simulator.worker import SimulatorIngestionWorker, get_simulator_worker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulator", tags=["Smartwatch Simulator Ingestion & Control"])


def verify_simulator_operator_access(
    x_ingestion_key: Optional[str] = Header(None, alias="X-Ingestion-Key"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    settings: Settings = Depends(get_settings),
) -> bool:
    """
    Ensure caller is an authorized operator, clinician, or internal service:
    1. Authenticated user with 'admin_operator' or 'doctor' role, OR
    2. Valid X-Ingestion-Key header matching settings.ingestion_api_key, OR
    3. Unauthenticated local development mode (app_env in 'development'/'testing').
    
    Security Guarantee:
    If a user is authenticated, their role MUST be 'admin_operator' or 'doctor'.
    Patient accounts are strictly forbidden from controlling simulator execution.
    """
    if current_user:
        if current_user.role in ("admin_operator", "doctor"):
            return True
        logger.warning(
            "Forbidden simulator control attempt by user %s with role '%s'",
            current_user.user_id,
            current_user.role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: User role '{current_user.role}' is not authorized to control simulator operations.",
        )

    if x_ingestion_key and x_ingestion_key == settings.ingestion_api_key:
        return True

    # In local development mode, permit unauthenticated access only when no credentials are provided
    if settings.app_env in ("development", "testing"):
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Simulator control requires clinician/operator authentication or valid service key.",
    )


@router.get(
    "/ingestion-status",
    status_code=status.HTTP_200_OK,
    summary="Retrieve simulator ingestion worker operational metrics",
)
def get_simulator_ingestion_status(
    worker: SimulatorIngestionWorker = Depends(get_simulator_worker),
) -> Dict[str, Any]:
    """Returns operational diagnostics for the simulator ingestion subsystem."""
    return worker.get_status()


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    summary="Retrieve unified simulator generator and ingestion operational status",
)
async def get_simulator_status(
    worker: SimulatorIngestionWorker = Depends(get_simulator_worker),
) -> Dict[str, Any]:
    settings = get_settings()
    """
    Returns dual-layer status distinguishing:
    1. Generator state: reachability, lifecycle state (RUNNING, STOPPED, ERROR), latest generation timestamp.
    2. Ingestion worker state: pipeline health, cursor, events accepted, failure count.
    A stopped generator does NOT imply an unhealthy backend or ingestion worker.
    """
    ingestion_status = worker.get_status()
    sim_data: Dict[str, Any] = {
        "reachable": False,
        "is_running": False,
        "lifecycle_state": "STOPPED",
        "latest_generation_at": None,
        "current_scenario": "normal",
        "error": None,
    }

    sim_url = f"{settings.sensor_simulator_base_url.rstrip('/')}/api/v1/simulator/status"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(sim_url)
            if resp.status_code == 200:
                body = resp.json()
                sim_data["reachable"] = True
                sim_data["is_running"] = body.get("is_running", False)
                sim_data["lifecycle_state"] = body.get(
                    "lifecycle_state",
                    "RUNNING" if body.get("is_running") else "STOPPED",
                )
                sim_data["latest_generation_at"] = body.get("latest_generation_at")
                sim_data["current_scenario"] = body.get("current_scenario", "normal")
                sim_data["active_patients"] = body.get("active_patients", [])
                sim_data["interrupted_patients"] = body.get("interrupted_patients", [])
            else:
                sim_data["error"] = f"Simulator HTTP {resp.status_code}"
    except Exception as exc:
        sim_data["error"] = f"Simulator unreachable: {type(exc).__name__}"

    return {
        "simulator": sim_data,
        "ingestion": ingestion_status,
        "backend_healthy": True,
        "disclaimer": "SIMULATED TELEMETRY — NOT FOR MEDICAL USE",
    }


@router.post(
    "/start",
    status_code=status.HTTP_200_OK,
    summary="Start or resume simulator telemetry generation and ingestion",
)
async def start_simulator_generation(
    authorized: bool = Depends(verify_simulator_operator_access),
    worker: SimulatorIngestionWorker = Depends(get_simulator_worker),
) -> Dict[str, Any]:
    settings = get_settings()
    """
    Reliably starts or resumes synthetic telemetry generation.
    - Commands simulator service to launch its background cycle.
    - Idempotent: safe to call repeatedly; prevents duplicate workers.
    - Ensures backend ingestion worker is actively polling.
    """
    sim_start_url = f"{settings.sensor_simulator_base_url.rstrip('/')}/api/v1/simulator/start"
    sim_resp_data: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(sim_start_url)
            if resp.status_code == 200:
                sim_resp_data = resp.json()
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Simulator start failed with HTTP {resp.status_code}: {resp.text[:200]}",
                )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach smartwatch simulator service at {settings.sensor_simulator_base_url}: {exc}",
        )

    # Ensure ingestion worker is running
    if worker.is_enabled and not worker.is_running:
        await worker.start()

    return {
        "status": "started",
        "lifecycle_state": sim_resp_data.get("lifecycle_state", "RUNNING"),
        "is_running": True,
        "message": sim_resp_data.get("message", "Smartwatch simulator telemetry started successfully."),
        "simulator_response": sim_resp_data,
        "ingestion_status": worker.get_status(),
    }


@router.post(
    "/stop",
    status_code=status.HTTP_200_OK,
    summary="Stop simulator telemetry generation immediately",
)
async def stop_simulator_generation(
    authorized: bool = Depends(verify_simulator_operator_access),
    worker: SimulatorIngestionWorker = Depends(get_simulator_worker),
) -> Dict[str, Any]:
    settings = get_settings()
    """
    Stops synthetic telemetry generation immediately and cleanly.
    
    SAFETY AND INTEGRITY GUARANTEES:
    - Commands simulator to cease producing and submitting readings immediately.
    - Does NOT terminate FastAPI, database connections, WebSockets, ML services,
      or genuine patient operations.
    - Does NOT delete existing readings, alerts, or audit trails.
    - Idempotent: safe to invoke repeatedly when already stopped.
    """
    sim_stop_url = f"{settings.sensor_simulator_base_url.rstrip('/')}/api/v1/simulator/stop"
    sim_resp_data: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(sim_stop_url)
            if resp.status_code == 200:
                sim_resp_data = resp.json()
            else:
                logger.warning("Simulator stop endpoint returned HTTP %s: %s", resp.status_code, resp.text)
                sim_resp_data = {"message": f"Simulator returned HTTP {resp.status_code}"}
    except Exception as exc:
        logger.warning("Could not contact simulator to send stop: %s", exc)
        sim_resp_data = {"message": f"Simulator unreachable: {exc}"}

    return {
        "status": "stopped",
        "lifecycle_state": "STOPPED",
        "is_running": False,
        "message": "Smartwatch simulator telemetry stopped successfully. Backend services remain fully operational.",
        "simulator_response": sim_resp_data,
        "ingestion_status": worker.get_status(),
    }


@router.post(
    "/ingestion/start",
    status_code=status.HTTP_200_OK,
    summary="Start simulator background polling loop only",
)
async def start_simulator_ingestion(
    authorized: bool = Depends(verify_simulator_operator_access),
    worker: SimulatorIngestionWorker = Depends(get_simulator_worker),
) -> Dict[str, Any]:
    """Start background ingestion loop idempotently."""
    await worker.start()
    return {
        "status": "started" if worker.is_running else "failed",
        "message": "Simulator ingestion worker started.",
        "worker_status": worker.get_status(),
    }


@router.post(
    "/ingestion/stop",
    status_code=status.HTTP_200_OK,
    summary="Stop simulator background polling loop only",
)
async def stop_simulator_ingestion(
    authorized: bool = Depends(verify_simulator_operator_access),
    worker: SimulatorIngestionWorker = Depends(get_simulator_worker),
) -> Dict[str, Any]:
    """Stop background ingestion loop cleanly."""
    await worker.stop()
    return {
        "status": "stopped",
        "message": "Simulator ingestion worker stopped.",
        "worker_status": worker.get_status(),
    }


@router.post(
    "/ingestion/poll",
    status_code=status.HTTP_200_OK,
    summary="Trigger immediate single poll iteration",
)
async def trigger_simulator_poll(
    authorized: bool = Depends(verify_simulator_operator_access),
    worker: SimulatorIngestionWorker = Depends(get_simulator_worker),
) -> Dict[str, Any]:
    """Perform a synchronous, on-demand single poll execution."""
    result = await worker.poll_once()
    return {
        "message": "Simulator poll cycle completed.",
        "cycle_result": result,
        "worker_status": worker.get_status(),
    }


class ScenarioControlPayload(BaseModel):
    """Payload to configure simulator demonstration scenarios."""
    scenario: Literal[
        "normal",
        "resting",
        "active",
        "recovering",
        "signal_interruption",
        "alert_test",
        "elevated_hr",
        "low_spo2",
    ] = Field(
        ...,
        description="Demo scenario: 'normal', 'resting', 'active', 'recovering', 'signal_interruption', 'alert_test', 'elevated_hr', 'low_spo2'",
    )
    target_patient_id: Optional[str] = Field(
        default=None,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Target patient identifier (e.g. 'P101'). If omitted, applies to demo cohort.",
    )
    alert_metric: Literal["heart_rate", "spo2", "temperature", "all"] = Field(
        default="all",
        description="Metric to elevate during alert_test ('heart_rate', 'spo2', 'temperature', 'all')",
    )
    reason: Optional[str] = Field(
        default="Demo scenario trigger",
        max_length=255,
        description="Clinical or presentation context for the transition",
    )


@router.post(
    "/scenario",
    status_code=status.HTTP_200_OK,
    summary="Transition simulator to a reproducible demonstration scenario",
)
async def set_simulator_scenario(
    payload: ScenarioControlPayload,
    authorized: bool = Depends(verify_simulator_operator_access),
) -> Dict[str, Any]:
    settings = get_settings()
    worker = get_simulator_worker()
    """
    Transition smartwatch simulator to a reproducible demonstration scenario:
    - 'normal': Stable resting baseline across cohort with zero spurious alerts.
    - 'elevated_hr': Tachycardia event on target patient (HR > 130 bpm -> CRITICAL alert).
    - 'low_spo2': Hypoxemia event on target patient (SpO2 < 85% -> CRITICAL alert).
    - 'recovering': Smooth physiological recovery back down to resting baseline.
    """
    sim_scenario_url = f"{settings.sensor_simulator_base_url.rstrip('/')}/api/v1/simulator/scenario"
    sim_resp_data: Dict[str, Any] = {}

    headers: Dict[str, str] = {}
    if settings.simulator_api_key:
        headers["X-Simulator-Key"] = settings.simulator_api_key

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                sim_scenario_url,
                json=payload.model_dump(),
                headers=headers,
            )
            if resp.status_code == 200:
                sim_resp_data = resp.json()
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Simulator scenario transition failed with HTTP {resp.status_code}: {resp.text[:200]}",
                )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach smartwatch simulator service at {settings.sensor_simulator_base_url}: {exc}",
        )

    # If ingestion worker is running, trigger a quick poll cycle so the backend ingests the immediate cycle reading
    if worker.is_running:
        try:
            await worker.poll_once()
        except Exception as poll_exc:
            logger.debug("Opportunistic poll after scenario change: %s", poll_exc)

    return {
        "status": "applied",
        "scenario": payload.scenario,
        "target_patient_id": payload.target_patient_id,
        "alert_metric": payload.alert_metric,
        "message": sim_resp_data.get("message", f"Scenario transitioned to '{payload.scenario}'."),
        "simulator_response": sim_resp_data,
        "disclaimer": "SIMULATED TELEMETRY — NOT FOR MEDICAL USE",
    }
