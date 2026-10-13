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
