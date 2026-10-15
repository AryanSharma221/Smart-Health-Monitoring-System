"""
Configuration settings for the Standalone Smartwatch Sensor Simulator.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SimulatorSettings(BaseSettings):
    """Configuration for synthetic telemetry generation and simulator API."""

    model_config = SettingsConfigDict(
        env_prefix="SIMULATOR_",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = Field(
        default="Smartwatch Sensor Telemetry Simulator",
        description="Simulator service name",
    )
    version: str = Field(default="1.0.0", description="Simulator service version")
    host: str = Field(default="127.0.0.1", description="Bind host for HTTP server")
    port: int = Field(default=8001, description="Bind port (default 8001 to avoid gateway port 8000)")
    interval_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=3600.0,
        description="Interval in seconds between generation cycles across patients",
    )
    max_history_records: int = Field(
        default=2000,
        ge=10,
        le=50000,
        description="Maximum in-memory circular buffer capacity before discarding oldest",
    )
    random_seed: int = Field(
        default=42,
        description="Deterministic PRNG seed for reproducible baseline drift",
    )
    demo_patients: List[str] = Field(
        default=["P101", "P102", "P103", "P104", "P105"],
        description="Configured patient cohort identifiers",
    )
    source_identifier: str = Field(
        default="smartwatch_simulator",
        description="Provenance source identifier attached to all generated events",
    )
    default_scenario: str = Field(
        default="normal",
        description="Initial telemetry generation scenario ('normal' or 'alert_test')",
    )
    auto_start: bool = Field(
        default=False,
        description="Whether to automatically launch the background generation task on startup",
    )
    control_secret: Optional[str] = Field(
        default=None,
        description="Optional shared secret required in X-Simulator-Key header for control endpoints",
    )


_SETTINGS_INSTANCE: Optional[SimulatorSettings] = None


def get_simulator_settings() -> SimulatorSettings:
    """Retrieve or initialize simulator settings singleton."""
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = SimulatorSettings()
    return _SETTINGS_INSTANCE
