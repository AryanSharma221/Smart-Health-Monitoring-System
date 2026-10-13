"""
Patient Health Readings and Telemetry API Router.

Provides endpoints for historical vitals retrieval, pagination, time-range filtering,
and latest-reading queries with strict server-side authorization enforcement.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from database.mysql.models import User
from database.mysql.session import get_db
from services.api.schemas.readings import (
    PaginatedReadingsResponse,
    PatientReadingResponse,
)
from services.auth.dependencies import get_current_user, verify_patient_access
from services.vitals_service import VitalsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patients", tags=["Patient Health Readings"])


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
