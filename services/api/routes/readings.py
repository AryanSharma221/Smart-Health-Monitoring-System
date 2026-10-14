"""
Patient Health Readings and Telemetry API Router.

Provides endpoints for historical vitals retrieval, pagination, time-range filtering,
and latest-reading queries with strict server-side authorization enforcement.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from database.mysql.models import User
from database.mysql.repositories.patient_repository import PatientRepository
from database.mysql.session import get_db
from services.api.schemas.readings import (
    PaginatedReadingsResponse,
    PatientReadingResponse,
)
from services.auth.dependencies import get_current_user, verify_patient_access
from services.auth.schemas import PatientProfileResponse
from services.vitals_service import VitalsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patients", tags=["Patient Health Readings"])


@router.get(
    "",
    response_model=List[PatientProfileResponse],
    status_code=status.HTTP_200_OK,
    summary="List authorized patients for the authenticated user",
)
def list_patients(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[PatientProfileResponse]:
    """
    List patient profiles according to clinician care relationship:
    - Clinicians (doctors): returns all patients assigned to this doctor.
    - Patients: returns self patient profile.
    - Admins: returns system-wide patients list.
    """
    patient_repo = PatientRepository(db)
    if current_user.role == "doctor":
        if not current_user.doctor_profile:
            return []
        patients = patient_repo.get_assigned_patients_for_doctor(current_user.doctor_profile.doctor_id)
        return [PatientProfileResponse.model_validate(p) for p in patients]
    elif current_user.role == "patient":
        if current_user.patient_profile:
            return [PatientProfileResponse.model_validate(current_user.patient_profile)]
        return []
    elif current_user.role == "admin_operator":
        patients = patient_repo.list_patients(limit=100)
        return [PatientProfileResponse.model_validate(p) for p in patients]
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get(
    "/{patient_id}/readings",
    response_model=PaginatedReadingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve paginated historical health readings for a patient",
)
def get_patient_readings(
    patient_id: str = Path(..., min_length=1, max_length=32, description="Target patient identifier (e.g., P101)"),
    start_time: Optional[datetime] = Query(None, description="Inclusive start timestamp filter (ISO 8601 UTC)"),
    end_time: Optional[datetime] = Query(None, description="Inclusive end timestamp filter (ISO 8601 UTC)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed, default: 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100, default: 20)"),
    source: Optional[str] = Query(None, max_length=32, description="Filter by data provenance (e.g., 'kaggle', 'simulator')"),
    is_simulated: Optional[bool] = Query(None, description="Filter by simulation status (false for historical Kaggle records)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedReadingsResponse:
    """
    Retrieve historical health readings for an authorized patient.
    
    Authorization:
    - Patient users can access only their own records.
    - Clinicians can access records only for patients assigned to them.
    - Administrators (admin_operator) have operational oversight.
    
    Pagination & Ordering:
    - Bounded page size (1 to 100).
    - Deterministic ordering: measured_at DESC with event_id DESC tie-breaker.
    - Inclusive time boundary filtering.
    """
    # 1. Enforce Server-Side Authorization First
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)

    # 2. Validate Time Range
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid time range: start_time cannot be later than end_time.",
        )

    # 3. Query Service
    vitals_service = VitalsService(db)
    items, total_count = vitals_service.get_paginated_readings(
        patient_id=patient_id,
        start_time=start_time,
        end_time=end_time,
        source=source,
        is_simulated=is_simulated,
        page=page,
        page_size=page_size,
    )

    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
    has_next = page < total_pages
    has_previous = page > 1 and (total_pages == 0 or page <= total_pages + 1)

    return PaginatedReadingsResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous,
    )


@router.get(
    "/{patient_id}/readings/latest",
    response_model=PatientReadingResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the most recent health reading for a patient",
)
def get_latest_patient_reading(
    patient_id: str = Path(..., min_length=1, max_length=32, description="Target patient identifier (e.g., P101)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientReadingResponse:
    """
    Retrieve the single most recent stored health reading for a patient.
    
    Authorization:
    - Same access control rules as historical readings.
    
    Not-Found Semantics:
    - Returns 404 Not Found if the patient has no telemetry readings.
    - Never fabricates readings for empty records.
    """
    # 1. Enforce Server-Side Authorization First
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)

    # 2. Query Service
    vitals_service = VitalsService(db)
    latest = vitals_service.get_latest_reading(patient_id)

    if not latest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No readings found for patient '{patient_id}'.",
        )

    return PatientReadingResponse(**latest)


@router.get(
    "/{patient_id}/vitals/latest",
    status_code=status.HTTP_200_OK,
    summary="Retrieve latest vitals in metric format",
)
def get_latest_patient_vitals_eav(
    patient_id: str = Path(..., min_length=1, max_length=32, description="Target patient identifier"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve the latest health reading formatted as discrete metric channels."""
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)
    vitals_service = VitalsService(db)
    latest = vitals_service.get_latest_reading(patient_id)
    if not latest:
        return {"patient_id": patient_id, "metrics": []}

    ts = latest["measured_at"].isoformat() if latest.get("measured_at") else None
    sim = latest.get("is_simulated", True)
    metrics = [
        {"metric_code": "heart_rate", "value": latest.get("heart_rate"), "unit": "bpm", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"},
        {"metric_code": "spo2", "value": latest.get("spo2"), "unit": "%", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"},
        {"metric_code": "temperature_f", "value": latest.get("temperature_f"), "unit": "°F", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"},
    ]
    if latest.get("respiratory_rate") is not None:
        metrics.append({"metric_code": "respiratory_rate", "value": latest.get("respiratory_rate"), "unit": "breaths/min", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"})
    if latest.get("systolic_bp") is not None:
        metrics.append({"metric_code": "systolic_bp", "value": latest.get("systolic_bp"), "unit": "mmHg", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"})
    if latest.get("diastolic_bp") is not None:
        metrics.append({"metric_code": "diastolic_bp", "value": latest.get("diastolic_bp"), "unit": "mmHg", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"})

    return {"patient_id": patient_id, "metrics": metrics}


@router.get(
    "/{patient_id}/vitals",
    status_code=status.HTTP_200_OK,
    summary="Retrieve historical vitals in metric time-series format",
)
def get_patient_vitals_eav(
    patient_id: str = Path(..., min_length=1, max_length=32, description="Target patient identifier"),
    metric_code: Optional[str] = Query(None, description="Filter by metric (e.g. heart_rate, spo2, temperature_f)"),
    from_time: Optional[str] = Query(None, alias="from", description="ISO start timestamp"),
    to_time: Optional[str] = Query(None, alias="to", description="ISO end timestamp"),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve historical health vitals adapted into metric channels for time-series charts."""
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)
    
    s_time = start_time
    e_time = end_time
    if from_time and not s_time:
        try:
            s_time = datetime.fromisoformat(from_time.replace("Z", "+00:00"))
        except Exception:
            pass
    if to_time and not e_time:
        try:
            e_time = datetime.fromisoformat(to_time.replace("Z", "+00:00"))
        except Exception:
            pass

    vitals_service = VitalsService(db)
    items, total_count = vitals_service.get_paginated_readings(
        patient_id=patient_id,
        start_time=s_time,
        end_time=e_time,
        page=1,
        page_size=100,
    )

    metrics = []
    for r in items:
        ts = r["measured_at"].isoformat() if r.get("measured_at") else None
        sim = r.get("is_simulated", True)

        if not metric_code or metric_code == "heart_rate":
            if r.get("heart_rate") is not None:
                metrics.append({"metric_code": "heart_rate", "value": r["heart_rate"], "unit": "bpm", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"})
        if not metric_code or metric_code == "spo2":
            if r.get("spo2") is not None:
                metrics.append({"metric_code": "spo2", "value": r["spo2"], "unit": "%", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"})
        if not metric_code or metric_code in ("temperature_f", "temperature"):
            if r.get("temperature_f") is not None:
                metrics.append({"metric_code": "temperature_f", "value": r["temperature_f"], "unit": "°F", "measured_at": ts, "is_simulated": sim, "quality_status": "valid"})

    return {"patient_id": patient_id, "metrics": metrics}


@router.get(
    "/{patient_id}",
    response_model=PatientProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve single patient demographic profile",
)
def get_patient_profile(
    patient_id: str = Path(..., min_length=1, max_length=32, description="Target patient identifier"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientProfileResponse:
    """Retrieve demographic profile for an authorized patient."""
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)
    patient_repo = PatientRepository(db)
    patient = patient_repo.get_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Patient '{patient_id}' not found.")
    return PatientProfileResponse.model_validate(patient)

