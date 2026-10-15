"""
Machine Learning Telemetry Assessment and Anomaly Prediction API Router.

Endpoints:
- GET  /predictions/status: Model operational health, version, and feature configuration.
- POST /patients/{patient_id}/assess: Ingest and evaluate telemetry through Isolation Forest.
- GET  /patients/{patient_id}/assessments: Retrieve paginated historical assessment results.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from database.mysql.models import User
from database.mysql.repositories.assessment_repository import AssessmentRepository
from database.mysql.session import get_db
from services.api.config import Settings, get_settings
from services.api.schemas.predictions import (
    MLModelStatusResponse,
    PaginatedAssessmentsResponse,
    TelemetryAssessmentRequest,
    TelemetryAssessmentResponse,
)
from services.auth.dependencies import get_current_user, verify_patient_access
from services.ml_service import MLService, get_ml_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ML Anomaly Predictions"])


@router.get(
    "/predictions/status",
    response_model=MLModelStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve operational status of the ML inference subsystem",
)
def get_model_status(
    settings: Settings = Depends(get_settings),
) -> MLModelStatusResponse:
    """
    Operational probe for ML anomaly detection availability, version, and architecture.
    Does not require authentication (operational health probe).
    """
    service = get_ml_service(settings)
    raw_status = service.get_status()
    return MLModelStatusResponse(
        status=raw_status["status"],
        is_available=raw_status["is_available"],
        model_version=raw_status["model_version"],
        algorithm=raw_status["algorithm"],
        feature_count=raw_status["feature_count"],
        has_baseline_manager=raw_status["has_baseline_manager"],
        artifact_path=raw_status["artifact_path"],
    )


@router.post(
    "/patients/{patient_id}/assess",
    response_model=TelemetryAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate patient telemetry through Isolation Forest anomaly detector",
)
async def assess_patient_telemetry(
    payload: TelemetryAssessmentRequest,
    patient_id: str = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$", description="Target patient identifier (e.g., P101)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TelemetryAssessmentResponse:
    """
    Ingest and score a single patient telemetry reading using the trained Isolation Forest.
    
    Authorization:
    - Patient users can evaluate only their own readings.
    - Clinicians can evaluate only assigned patients.
    - Administrators have system-wide evaluation privileges.
    
    Guarantees:
    - Non-blocking: CPU inference runs in a thread pool via asyncio.to_thread.
    - If persist=True, atomically persists ModelAssessment and generates Alert if anomalous.
    - Returns standardized JSON contract with anomaly score, result status, and feature evidence.
    """
    # 1. Enforce Server-Side Authorization
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)

    # 2. Resolve Timestamp
    ts = payload.timestamp or datetime.now(timezone.utc)

    # 3. Execute inference safely off the async event loop
    service = get_ml_service(settings)

    if payload.persist:
        # Synchronous database transaction and persistence executed in threadpool
        def _execute_persist():
            return service.assess_and_persist(
                db=db,
                patient_id=patient_id,
                timestamp=ts,
                heart_rate=payload.heart_rate,
                spo2=payload.spo2,
                temperature_f=payload.temperature_f,
                respiratory_rate=payload.respiratory_rate,
                systolic_bp=payload.systolic_bp,
                diastolic_bp=payload.diastolic_bp,
                source_event_id=payload.source_event_id,
                is_simulated=payload.is_simulated,
                trigger_alert=True,
            )

        persisted_assessment, persisted_alert, res = await asyncio.to_thread(_execute_persist)
        
        is_anomaly = res.score >= 0.50
        alert_triggered = persisted_alert is not None
        alert_id = persisted_alert.alert_id if persisted_alert else None
        assessment_id = persisted_assessment.assessment_id

    else:
        # Read-only inference execution without persisting
        def _execute_assess():
            return service.assess(
                patient_id=patient_id,
                timestamp=ts,
                heart_rate=payload.heart_rate,
                spo2=payload.spo2,
                temperature_f=payload.temperature_f,
                respiratory_rate=payload.respiratory_rate,
                systolic_bp=payload.systolic_bp,
                diastolic_bp=payload.diastolic_bp,
                source_event_id=payload.source_event_id,
                is_simulated=payload.is_simulated,
            )

        res = await asyncio.to_thread(_execute_assess)
        is_anomaly = res.score >= 0.50
        alert_triggered = False
        alert_id = None
        assessment_id = res.assessment_id

    # Canonical result string
    db_result_map = {
        "normal_like": "normal",
        "anomalous": "anomaly",
        "insufficient_data": "inconclusive",
    }
    canonical_result = db_result_map.get(res.result, "inconclusive")

    return TelemetryAssessmentResponse(
        assessment_id=assessment_id,
        patient_id=patient_id,
        model_version=res.model_version,
        score=round(float(res.score), 4),
        result=canonical_result,
        is_anomaly=is_anomaly,
        feature_summary=res.feature_summary,
        time_window_start=res.time_window_start,
        time_window_end=res.time_window_end,
        explanation=res.explanation,
        alert_triggered=alert_triggered,
        alert_id=alert_id,
        latency_ms=round(float(res.latency_ms), 2),
    )


@router.get(
    "/patients/{patient_id}/assessments",
    response_model=PaginatedAssessmentsResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve paginated historical ML assessments for a patient",
)
def list_patient_assessments(
    patient_id: str = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$", description="Target patient identifier (e.g., P101)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedAssessmentsResponse:
    """Retrieve historical model assessment evaluations for an authorized patient."""
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)

    repo = AssessmentRepository(db)
    items, total_count = repo.list_by_patient_paginated(
        patient_id=patient_id,
        page=page,
        page_size=page_size,
    )

    response_items = []
    for asmt in items:
        summary = {}
        if asmt.features_json:
            try:
                summary = json.loads(asmt.features_json)
            except Exception:
                summary = {}

        score_f = float(asmt.score)
        response_items.append(
            TelemetryAssessmentResponse(
                assessment_id=asmt.assessment_id,
                patient_id=asmt.patient_id,
                model_version=asmt.model_version,
                score=round(score_f, 4),
                result=asmt.result,
                is_anomaly=asmt.result == "anomaly" or score_f >= 0.50,
                feature_summary=summary,
                time_window_start=asmt.time_window_start or asmt.created_at,
                time_window_end=asmt.time_window_end or asmt.created_at,
                explanation=["Historical recorded assessment."],
                alert_triggered=bool(asmt.alerts),
                alert_id=asmt.alerts[0].alert_id if asmt.alerts else None,
                latency_ms=0.0,
            )
        )

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 0

    return PaginatedAssessmentsResponse(
        items=response_items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
