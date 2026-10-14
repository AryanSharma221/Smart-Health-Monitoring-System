"""
Pydantic Schemas for Machine Learning Telemetry Assessment and Anomaly Predictions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TelemetryAssessmentRequest(BaseModel):
    """Input payload for ML telemetry assessment."""

    model_config = ConfigDict(extra="forbid")

    heart_rate: float = Field(..., ge=20.0, le=300.0, description="Observed heart rate in beats per minute (bpm)")
    spo2: float = Field(..., ge=50.0, le=100.0, description="Blood oxygen saturation percentage (SpO2 %)")
    temperature_f: float = Field(..., ge=70.0, le=115.0, description="Body temperature in degrees Fahrenheit (°F)")
    timestamp: Optional[datetime] = Field(None, description="Observation timestamp in UTC (defaults to current time)")
    
    # Optional extensions from live simulator (captured in summary without model contamination)
    respiratory_rate: Optional[float] = Field(None, ge=4.0, le=80.0, description="Respiratory rate in breaths per minute")
    systolic_bp: Optional[float] = Field(None, ge=40.0, le=260.0, description="Systolic blood pressure in mmHg")
    diastolic_bp: Optional[float] = Field(None, ge=30.0, le=180.0, description="Diastolic blood pressure in mmHg")
    
    source_event_id: Optional[str] = Field(None, max_length=64, description="Optional ingestion event ID for traceability")
    is_simulated: bool = Field(True, description="Flag indicating simulated vs hardware source")
    persist: bool = Field(True, description="If True, persist assessment to MySQL model_assessments table")


class TelemetryAssessmentResponse(BaseModel):
    """Response payload for ML telemetry assessment."""

    model_config = ConfigDict(from_attributes=True)

    assessment_id: Optional[str] = Field(None, description="Unique model assessment identifier")
    patient_id: str = Field(..., description="Target patient identifier")
    model_version: str = Field(..., description="Version of the scoring model artifact")
    score: float = Field(..., ge=0.0, le=1.0, description="Calibrated anomaly score [0.0, 1.0]")
    result: str = Field(..., description="Canonical result status: 'normal', 'anomaly', or 'inconclusive'")
    is_anomaly: bool = Field(..., description="True if score >= 0.50 (anomalous threshold)")
    feature_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary of rolling vital signs and strain index")
    time_window_start: datetime = Field(..., description="Start of historical observation window")
    time_window_end: datetime = Field(..., description="End of historical observation window")
    explanation: List[str] = Field(default_factory=list, description="Top contributing feature evidence explanations")
    alert_triggered: bool = Field(False, description="True if a clinical alert was triggered and persisted")
    alert_id: Optional[str] = Field(None, description="ID of triggered clinical alert if applicable")
    latency_ms: float = Field(0.0, description="End-to-end inference and feature extraction latency in milliseconds")
    notice: str = Field("SIMULATED DATA — NOT FOR MEDICAL USE", description="Medical safety disclaimer")


class MLModelStatusResponse(BaseModel):
    """Operational health status of the ML inference subsystem."""

    status: str = Field(..., description="Service health: 'ready' or 'degraded'")
    is_available: bool = Field(..., description="True if model artifact is loaded and fitted")
    model_version: str = Field(..., description="Active model version identifier")
    algorithm: str = Field("IsolationForest", description="Underlying anomaly detection algorithm")
    feature_count: int = Field(38, description="Number of engineered physiological features evaluated")
    has_baseline_manager: bool = Field(..., description="True if frozen patient baselines are initialized")
    artifact_path: Optional[str] = Field(None, description="Filesystem directory where model artifact is loaded from")
    notice: str = Field("SIMULATED DATA — NOT FOR MEDICAL USE", description="Clinical safety boundary notice")


class PaginatedAssessmentsResponse(BaseModel):
    """Paginated collection of historical model assessments."""

    items: List[TelemetryAssessmentResponse] = Field(..., description="List of assessments on current page")
    total_count: int = Field(..., ge=0, description="Total matching assessments across all pages")
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, le=100, description="Page size limit applied")
    total_pages: int = Field(..., ge=0, description="Total number of pages available")
