"""
Telemetry and Vitals Domain Service.

Provides telemetry timeseries aggregation, freshness assessment, and observation queries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from database.mysql.models import VitalsReading
from database.mysql.repositories.vitals_repository import VitalsRepository


class VitalsService:
    """Application service for querying patient telemetry and canonical vitals."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = VitalsRepository(session)

    def get_latest_vitals_summary(self, patient_id: str) -> Dict[str, VitalsReading]:
        """Fetch the most recent reading for each vital metric as a dictionary."""
        readings = self.repo.get_latest_vitals(patient_id)
        return {r.metric_code: r for r in readings}

    def get_patient_history(
        self,
        patient_id: str,
        metric_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[VitalsReading]:
        """Retrieve historical telemetry timeseries."""
        return self.repo.get_vitals_history(
            patient_id=patient_id,
            metric_code=metric_code,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    @staticmethod
    def assess_freshness(
        reading: Optional[VitalsReading],
        max_staleness_seconds: int = 300,
    ) -> str:
        """
        Assess telemetry freshness against a staleness window.
        Returns 'active', 'stale', or 'missing'.
        """
        if not reading:
            return "missing"

        now = datetime.now(timezone.utc)
        measured_at = reading.measured_at
        if measured_at.tzinfo is None:
            measured_at = measured_at.replace(tzinfo=timezone.utc)

        age_seconds = (now - measured_at).total_seconds()
        if age_seconds < 0:
            return "active"  # Observation timestamp in future / simulator
        return "active" if age_seconds <= max_staleness_seconds else "stale"

    @staticmethod
    def map_event_to_reading_dict(event) -> Dict[str, Any]:
        """Transform an IngestionEvent and its normalized readings into an API reading structure."""
        reading: Dict[str, Any] = {
            "event_id": event.event_id,
            "patient_id": event.patient_id,
            "measured_at": event.measured_at,
            "source": event.source,
            "is_simulated": event.is_simulated,
            "heart_rate": None,
            "spo2": None,
            "temperature_f": None,
            "temperature_c": None,
        }
        for r in event.readings:
            if r.metric_code == "heart_rate":
                reading["heart_rate"] = float(r.value)
            elif r.metric_code == "spo2":
                reading["spo2"] = float(r.value)
            elif r.metric_code == "temperature":
                reading["temperature_c"] = float(r.value)
                if r.raw_unit == "degF":
                    reading["temperature_f"] = float(r.raw_value)
                else:
                    reading["temperature_f"] = round(float(r.value) * 9.0 / 5.0 + 32.0, 2)
        return reading

    def get_paginated_readings(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        source: Optional[str] = None,
        is_simulated: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Query paginated readings for a patient.
        Validates timestamp ordering and delegates to repository.
        """
        if start_time and end_time and start_time > end_time:
            raise ValueError("Invalid time range: start_time cannot be later than end_time.")

        events, total_count = self.repo.get_patient_events_paginated(
            patient_id=patient_id,
            start_time=start_time,
            end_time=end_time,
            source=source,
            is_simulated=is_simulated,
            page=page,
            page_size=page_size,
        )
        items = [self.map_event_to_reading_dict(e) for e in events]
        return items, total_count

    def get_latest_reading(self, patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the newest observation event for a patient.
        Returns mapped dictionary or None if no readings exist.
        """
        event = self.repo.get_latest_patient_event(patient_id)
        if not event:
            return None
        return self.map_event_to_reading_dict(event)

