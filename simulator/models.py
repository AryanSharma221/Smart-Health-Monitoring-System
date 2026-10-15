"""
Pydantic Schemas and Domain Models for the Smartwatch Sensor Simulator.

Provides full field-level compatibility with the Smart Health Monitoring System:
- Field names: patient_id, heart_rate (bpm), spo2 (%), temperature_f (F), timestamp / measured_at (UTC).
- Provenance: source='smartwatch_simulator', is_simulated=True.
- Monotonic sequence numbering for lossless cursor-based polling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TelemetryReading(BaseModel):
    """
    Standardized simulated wearable health observation.
    Maintains exact naming and unit alignment with domain backend contracts.
    """

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    event_id: str = Field(..., description="Globally unique simulated event identifier (e.g. evt_sim_1_abc)")
    patient_id: str = Field(..., description="Target patient identifier (e.g. P101, P102)")
    timestamp: datetime = Field(..., description="Observation timestamp in UTC (ISO 8601)")
    measured_at: datetime = Field(..., description="Alias for timestamp matching backend ingestion contract")
    source: str = Field(default="smartwatch_simulator", description="Provenance device / stream identifier")
    is_simulated: bool = Field(default=True, description="Strictly True for synthetic telemetry")
    heart_rate: float = Field(..., ge=20.0, le=260.0, description="Heart rate in beats per minute (bpm)")
    spo2: float = Field(..., ge=40.0, le=100.0, description="Blood oxygen saturation percentage (% SpO2)")
    temperature_f: float = Field(..., ge=80.0, le=115.0, description="Body temperature in degrees Fahrenheit (F)")
    temperature_c: float = Field(..., description="Canonical converted body temperature in degrees Celsius (C)")
    scenario: str = Field(default="normal", description="Simulation mode active during sample generation")
    state: str = Field(default="resting", description="Sensor physiological state ('resting', 'active', 'recovering', 'alert_test')")
    sequence_number: int = Field(..., ge=1, description="Strictly monotonic generation sequence identifier for reliable polling")


class SimulatorHealthResponse(BaseModel):
    """Response model for /health endpoint."""

    status: str = Field(default="healthy", description="Simulator process health status")
    service: str = Field(..., description="Service identifier")
    version: str = Field(..., description="Service version")
    uptime_seconds: float = Field(..., description="Uptime elapsed since application initialization")
    generator_running: bool = Field(..., description="Whether the background generator task is actively executing")
    disclaimer: str = Field(
        default="SIMULATED TELEMETRY  NOT FOR MEDICAL USE OR CLINICAL DIAGNOSIS",
        description="Mandatory clinical safety limitation statement",
    )


class PatientBaselineDetail(BaseModel):
    """Configured demo patient profile with individual physiologic baseline."""

    patient_id: str = Field(..., description="Patient identifier (e.g., P101)")
    baseline_heart_rate: float = Field(..., description="Resting baseline HR (bpm)")
    baseline_spo2: float = Field(..., description="Resting baseline SpO2 (%)")
    baseline_temperature_f: float = Field(..., description="Resting baseline temperature (F)")
    description: str = Field(..., description="Clinical demonstration notes")


class PatientsListResponse(BaseModel):
    """Response model for GET /api/v1/patients."""

    patients: List[str] = Field(..., description="List of configured patient identifiers")
    details: List[PatientBaselineDetail] = Field(..., description="Patient baseline physiologic characteristics")
    count: int = Field(..., description="Number of active demo patients")


class LatestReadingsResponse(BaseModel):
    """Response model for GET /api/v1/readings/latest."""

    readings: Dict[str, TelemetryReading] = Field(
        ...,
        description="Map of latest observation keyed by patient_id",
    )
    count: int = Field(..., description="Number of patients with available readings")
    timestamp_utc: datetime = Field(..., description="Time of latest query execution")


class BoundedReadingsResponse(BaseModel):
    """Response model for GET /api/v1/readings."""

    items: List[TelemetryReading] = Field(..., description="Recent observations sorted newest-first")
    count: int = Field(..., description="Number of items returned in this response")
    total_buffer_count: int = Field(..., description="Current count of events in circular memory buffer")
    limit: int = Field(..., description="Limit parameter applied to request")
    filter_patient_id: Optional[str] = Field(None, description="Optional patient filter applied")


class PollingStreamResponse(BaseModel):
    """
    Response model for GET /api/v1/readings/stream.
    Enables reliable cursor-based polling without repeat ingestion or skipped events.
    """

    items: List[TelemetryReading] = Field(..., description="Chronological observations generated after requested cursor")
    count: int = Field(..., description="Number of new items in this batch")
    cursor: Optional[str] = Field(None, description="The cursor provided in the incoming request")
    next_cursor: str = Field(..., description="Cursor to pass into the subsequent poll request")
    has_more: bool = Field(..., description="True if additional unseen items exist beyond this batch")
    newest_sequence_number: Optional[int] = Field(None, description="Sequence number of the most recent item in batch")


class SimulatorStatusResponse(BaseModel):
    """Response model for GET /api/v1/simulator/status."""

    is_running: bool = Field(..., description="Whether continuous background generation is running")
    interval_seconds: float = Field(..., description="Configured generation interval in seconds")
    current_scenario: str = Field(..., description="Active simulation scenario ('normal', 'resting', 'active', 'recovering', 'alert_test')")
    configured_patients: List[str] = Field(..., description="List of patients being monitored")
    total_readings_generated: int = Field(..., description="Total readings generated since process startup")
    buffer_capacity: int = Field(..., description="Max capacity of in-memory circular buffer")
    buffer_used: int = Field(..., description="Current count of readings in memory")
    latest_generation_at: Optional[datetime] = Field(None, description="Timestamp of most recent generation cycle")
    patient_states: Dict[str, str] = Field(default_factory=dict, description="Behavioral sensor state per patient")
    interrupted_patients: List[str] = Field(default_factory=list, description="Patients with simulated connectivity interruption")
    active_patients: List[str] = Field(default_factory=list, description="Patients actively transmitting telemetry")
    lifecycle_state: str = Field(
        default="STOPPED",
        description="Explicit lifecycle state: 'RUNNING', 'STOPPING', 'STOPPED', 'ERROR'",
    )
    disclaimer: str = Field(
        default="SIMULATED TELEMETRY  NOT FOR MEDICAL USE OR CLINICAL DIAGNOSIS",
        description="Mandatory clinical safety limitation statement",
    )


class ScenarioUpdateRequest(BaseModel):
    """Request model for POST /api/v1/simulator/scenario."""

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
        description=(
            "Scenario or sensor state to activate: 'normal'/'resting' for stable baseline; "
            "'active' for elevated exertion; 'recovering' for gradual return to baseline; "
            "'signal_interruption' for offline device simulation; "
            "'alert_test', 'elevated_hr', 'low_spo2' for clinical threshold evaluation."
        ),
    )
    target_patient_id: Optional[str] = Field(
        default=None,
        description="Target patient identifier (e.g. 'P101'). If omitted, applies to demo cohort.",
    )
    alert_metric: Literal["heart_rate", "spo2", "temperature", "all"] = Field(
        default="all",
        description="Specific metric to elevate into alert state during alert_test mode.",
    )
    reason: Optional[str] = Field(
        default="Demo scenario trigger",
        description="Optional human-readable reason or clinical context for the scenario transition.",
    )


class InterruptionRequest(BaseModel):
    """Request model for POST /api/v1/simulator/interruption."""

    patient_id: Optional[str] = Field(
        default=None,
        description="Target patient identifier (e.g. 'P101'). If omitted, toggles whole cohort.",
    )
    interrupted: bool = Field(
        default=True,
        description="True to simulate connectivity loss (stops sending); False to resume normal transmission.",
    )
    reason: Optional[str] = Field(
        default="simulated_device_connectivity_loss",
        description="Demonstration rationale or context for this interruption event",
    )


class ControlActionResponse(BaseModel):
    """Generic response for state-changing simulator actions (start, stop, scenario, interruption)."""

    message: str = Field(..., description="Action result description")
    is_running: bool = Field(..., description="Current running state of the generator")
    lifecycle_state: str = Field(
        default="STOPPED",
        description="Explicit lifecycle state: 'RUNNING', 'STOPPING', 'STOPPED', 'ERROR'",
    )
    timestamp_utc: datetime = Field(..., description="Timestamp of execution")
    interrupted_patients: Optional[List[str]] = Field(None, description="Current interrupted patients list if applicable")
