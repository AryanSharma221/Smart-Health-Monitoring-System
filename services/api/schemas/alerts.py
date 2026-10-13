"""
Pydantic Schemas for Clinical Alerts, Lifecycles, and Acknowledgements.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AlertResponse(BaseModel):
    """Authoritative clinical alert representation."""

    model_config = ConfigDict(from_attributes=True)

    alert_id: str = Field(..., description="Unique alert identifier")
    patient_id: str = Field(..., description="Target patient identifier")
    event_id: Optional[str] = Field(None, description="Triggering ingestion event ID")
    assessment_id: Optional[str] = Field(None, description="Triggering ML assessment ID if applicable")
    rule_id: Optional[str] = Field(None, description="Triggering clinical rule ID if applicable")
    severity: str = Field(..., description="Alert severity: LOW, MEDIUM, HIGH, CRITICAL")
    category: str = Field(..., description="Alert category: vital_threshold, ml_anomaly, composite, stale_data")
    reason: str = Field(..., description="Clinical context and reason for alert generation")
    status: str = Field(..., description="Alert lifecycle status: NEW, ACKNOWLEDGED, RESOLVED")
    acknowledged_by: Optional[str] = Field(None, description="User ID of acknowledging clinician/user")
    acknowledged_at: Optional[datetime] = Field(None, description="Timestamp of acknowledgement in UTC")
    resolved_by: Optional[str] = Field(None, description="User ID of resolving clinician/user")
    resolved_at: Optional[datetime] = Field(None, description="Timestamp of resolution in UTC")
    created_at: datetime = Field(..., description="Creation timestamp in UTC")


class PaginatedAlertsResponse(BaseModel):
    """Paginated collection of clinical alerts with navigation metadata."""

    model_config = ConfigDict(from_attributes=True)

    items: List[AlertResponse] = Field(..., description="List of alerts on the current page")
    total_count: int = Field(..., ge=0, description="Total matching alerts count across all pages")
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, le=100, description="Page size limit applied to this request")
    total_pages: int = Field(..., ge=0, description="Total number of pages available")
    has_next: bool = Field(..., description="True if a subsequent page exists")
    has_previous: bool = Field(..., description="True if a previous page exists")


class AlertAcknowledgeRequest(BaseModel):
    """Optional payload for acknowledging an alert."""

    note: Optional[str] = Field(None, max_length=1000, description="Clinical note or commentary on acknowledgement")
