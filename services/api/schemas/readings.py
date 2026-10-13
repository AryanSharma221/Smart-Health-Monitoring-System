"""
Pydantic Schemas for Patient Health Readings and Telemetry Queries.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PatientReadingResponse(BaseModel):
    """
    Normalized patient telemetry observation representation.
    Preserves original Kaggle units (Fahrenheit, bpm, %) and provenance.
    """

    model_config = ConfigDict(from_attributes=True)

    event_id: str = Field(..., description="Unique telemetry event identifier")
    patient_id: str = Field(..., description="Domain patient identifier (e.g., P101 or PAT-XXXX)")
    measured_at: datetime = Field(..., description="Observation timestamp in UTC")
    source: str = Field(..., description="Provenance source identifier (e.g., 'kaggle', 'simulator')")
    is_simulated: bool = Field(..., description="False for historical Kaggle records, True for simulated data")
    heart_rate: Optional[float] = Field(None, description="Heart rate in beats per minute (bpm)")
    spo2: Optional[float] = Field(None, description="Blood oxygen saturation percentage (SpO2 %)")
    temperature_f: Optional[float] = Field(None, description="Body temperature in degrees Fahrenheit (°F)")
    temperature_c: Optional[float] = Field(None, description="Canonical converted body temperature in degrees Celsius (°C)")


class PaginatedReadingsResponse(BaseModel):
    """Paginated collection of patient health readings with navigation metadata."""

    model_config = ConfigDict(from_attributes=True)

    items: List[PatientReadingResponse] = Field(..., description="List of readings on the current page")
    total_count: int = Field(..., ge=0, description="Total matching readings count across all pages")
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, le=100, description="Page size limit applied to this request")
    total_pages: int = Field(..., ge=0, description="Total number of pages available")
    has_next: bool = Field(..., description="True if a subsequent page exists")
    has_previous: bool = Field(..., description="True if a previous page exists")
