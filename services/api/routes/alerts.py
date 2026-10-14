"""
Clinical Alerts and Alert Lifecycle Management API Router.

Provides endpoints for patient alert listing, individual alert retrieval,
and idempotent alert acknowledgement with server-side authorization enforcement.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from database.mysql.exceptions import EntityNotFoundError, InvalidStateTransitionError
from database.mysql.models import User
from database.mysql.session import get_db
from services.alert_service import AlertService
from services.api.schemas.alerts import (
    AlertAcknowledgeRequest,
    AlertResponse,
    PaginatedAlertsResponse,
)
from services.auth.dependencies import get_current_user, verify_patient_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Clinical Alerts"])

VALID_STATUSES = {"NEW", "ACKNOWLEDGED", "RESOLVED"}
VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@router.get(
    "/alerts",
    response_model=List[AlertResponse],
    status_code=status.HTTP_200_OK,
    summary="List clinical alerts across scope",
)
def list_alerts(
    patient_id: Optional[str] = Query(None, description="Optional patient filter"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (NEW, ACKNOWLEDGED, RESOLVED)"),
    limit: int = Query(50, ge=1, le=100, description="Max alerts to retrieve"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[AlertResponse]:
    """
    List clinical alerts based on role and care relationship:
    - Patients: restricted to their own alerts.
    - Doctors: alerts for assigned patients (or specific assigned patient).
    - Admins: global visibility.
    """
    alert_service = AlertService(db)
    norm_status = status_filter.upper() if status_filter else None
    if norm_status and norm_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status filter '{status_filter}'. Allowed values: {sorted(VALID_STATUSES)}.",
        )

    if current_user.role == "patient":
        if patient_id and patient_id != current_user.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
        return alert_service.list_alerts(patient_id=current_user.user_id, status=norm_status, limit=limit)
    elif current_user.role == "doctor":
        if patient_id:
            verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)
            return alert_service.list_alerts(patient_id=patient_id, status=norm_status, limit=limit)
        from database.mysql.repositories.patient_repository import PatientRepository
        patient_repo = PatientRepository(db)
        assigned_patients = {p.patient_id for p in patient_repo.get_assigned_patients_for_doctor(current_user.user_id)}
        all_alerts = alert_service.list_alerts(status=norm_status, limit=limit * 2)
        return [a for a in all_alerts if a.patient_id in assigned_patients][:limit]
    elif current_user.role == "admin_operator":
        return alert_service.list_alerts(patient_id=patient_id, status=norm_status, limit=limit)
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get(
    "/patients/{patient_id}/alerts",
    response_model=PaginatedAlertsResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve paginated clinical alerts for an authorized patient",
)
def get_patient_alerts(
    patient_id: str = Path(..., min_length=1, max_length=32, description="Target patient identifier (e.g., P101)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (NEW, ACKNOWLEDGED, RESOLVED)"),
    severity: Optional[str] = Query(None, description="Filter by severity (LOW, MEDIUM, HIGH, CRITICAL)"),
    start_time: Optional[datetime] = Query(None, description="Inclusive start timestamp filter (ISO 8601 UTC)"),
    end_time: Optional[datetime] = Query(None, description="Inclusive end timestamp filter (ISO 8601 UTC)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed, default: 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100, default: 20)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedAlertsResponse:
    """
    Retrieve clinical alerts for an authorized patient.
    
    Authorization:
    - Patients can view only their own alerts.
    - Assigned clinicians can view alerts for assigned patients.
    - Administrators have system-wide operational visibility.
    """
    # 1. Enforce Server-Side Authorization
    verify_patient_access(patient_id=patient_id, current_user=current_user, db=db)

    # 2. Validate Filters
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid time range: start_time cannot be later than end_time.",
        )

    norm_status = status_filter.upper() if status_filter else None
    if norm_status and norm_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status filter '{status_filter}'. Allowed values: {sorted(VALID_STATUSES)}.",
        )

    norm_severity = severity.upper() if severity else None
    if norm_severity and norm_severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid severity filter '{severity}'. Allowed values: {sorted(VALID_SEVERITIES)}.",
        )

    # 3. Query Service
    alert_service = AlertService(db)
    items, total_count = alert_service.list_patient_alerts_paginated(
        patient_id=patient_id,
        status=norm_status,
        severity=norm_severity,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )

    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
    has_next = page < total_pages
    has_previous = page > 1 and (total_pages == 0 or page <= total_pages + 1)

    return PaginatedAlertsResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous,
    )


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve single clinical alert by ID",
)
def get_alert_by_id(
    alert_id: str = Path(..., min_length=1, max_length=64, description="Unique alert identifier"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    """
    Retrieve details of a single clinical alert.
    Verifies that the authenticated user has access to the target patient.
    """
    alert_service = AlertService(db)
    try:
        alert = alert_service.get_alert(alert_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert '{alert_id}' not found.",
        )

    # Enforce patient-level authorization
    verify_patient_access(patient_id=alert.patient_id, current_user=current_user, db=db)
    return alert


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge an open clinical alert",
)
def acknowledge_alert(
    alert_id: str = Path(..., min_length=1, max_length=64, description="Unique alert identifier"),
    payload: Optional[AlertAcknowledgeRequest] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    """
    Acknowledge an open clinical alert.
    
    Idempotent behavior:
    - If alert is in NEW status, updates to ACKNOWLEDGED, stamps acknowledged_at and acknowledged_by,
      and appends audit log record.
    - If alert is already ACKNOWLEDGED, returns existing alert safely without error.
    - If alert is in RESOLVED status, returns 400 Bad Request (cannot acknowledge a resolved alert).
    """
    alert_service = AlertService(db)
    try:
        alert = alert_service.get_alert(alert_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert '{alert_id}' not found.",
        )

    # Enforce patient-level authorization
    verify_patient_access(patient_id=alert.patient_id, current_user=current_user, db=db)

    note = payload.note if payload else None
    try:
        updated_alert = alert_service.acknowledge_alert(
            alert_id=alert_id,
            actor_id=current_user.user_id,
            note=note,
        )
    except InvalidStateTransitionError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    return updated_alert


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=AlertResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve a clinical alert",
)
def resolve_alert(
    alert_id: str = Path(..., min_length=1, max_length=64, description="Unique alert identifier"),
    payload: Optional[AlertAcknowledgeRequest] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    """
    Resolve an active or acknowledged clinical alert.
    
    Idempotent behavior:
    - If alert is in NEW or ACKNOWLEDGED status, updates to RESOLVED, stamps resolved_at and notes,
      and appends audit log and status history records.
    - If alert is already RESOLVED, returns existing alert safely without error.
    """
    alert_service = AlertService(db)
    try:
        alert = alert_service.get_alert(alert_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert '{alert_id}' not found.",
        )

    # Enforce patient-level authorization
    verify_patient_access(patient_id=alert.patient_id, current_user=current_user, db=db)

    note = payload.note if payload else None
    try:
        updated_alert = alert_service.resolve_alert(
            alert_id=alert_id,
            actor_id=current_user.user_id,
            note=note,
        )
    except InvalidStateTransitionError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    return updated_alert

