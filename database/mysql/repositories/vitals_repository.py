"""
Telemetry Ingestion Events and Canonical Vitals Repository.

Provides encapsulated data access for ingestion events, canonical vitals readings,
idempotency checks, and patient historical queries.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, Set

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from database.mysql.models import IngestionEvent, VitalsReading


class VitalsRepository:
    """Encapsulates relational persistence queries for health telemetry and measurements."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_event(self, event: IngestionEvent) -> IngestionEvent:
        """Stage an ingestion event."""
        self.session.add(event)
        self.session.flush()
        return event

    def add_readings(self, readings: Sequence[VitalsReading]) -> None:
        """Stage multiple normalized vitals readings."""
        self.session.add_all(list(readings))
        self.session.flush()

    def get_event_by_id(self, event_id: str) -> Optional[IngestionEvent]:
        """Fetch ingestion event by event_id."""
        return self.session.get(IngestionEvent, event_id)

    def get_existing_source_event_ids(
        self,
        source: str,
        source_event_ids: Sequence[str],
    ) -> Set[str]:
        """
        Query for already-persisted source_event_ids to guarantee idempotent deduplication.
        Executes in chunks to avoid SQL IN-clause parameter limits.
        """
        if not source_event_ids:
            return set()

        existing: Set[str] = set()
        chunk_size = 500
        ids_list = list(source_event_ids)
        for i in range(0, len(ids_list), chunk_size):
            chunk = ids_list[i : i + chunk_size]
            stmt = select(IngestionEvent.source_event_id).where(
                IngestionEvent.source == source,
                IngestionEvent.source_event_id.in_(chunk),
            )
            existing.update(self.session.scalars(stmt).all())
        return existing

    def get_vitals_history(
        self,
        patient_id: str,
        metric_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[VitalsReading]:
        """
        Retrieve chronological vitals readings for a patient filtered by metric and time.
        Accelerated by composite index idx_vitals_patient_metric_time.
        """
        stmt = select(VitalsReading).where(VitalsReading.patient_id == patient_id)

        if metric_code:
            stmt = stmt.where(VitalsReading.metric_code == metric_code)
        if start_time:
            stmt = stmt.where(VitalsReading.measured_at >= start_time)
        if end_time:
            stmt = stmt.where(VitalsReading.measured_at <= end_time)

        stmt = stmt.order_by(desc(VitalsReading.measured_at)).limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_latest_vitals(self, patient_id: str) -> List[VitalsReading]:
        """
        Retrieve the latest reading for each distinct metric for a given patient.
        """
        metrics = ["heart_rate", "spo2", "temperature", "respiratory_rate", "bp_systolic", "bp_diastolic"]
        latest_readings: List[VitalsReading] = []
        for code in metrics:
            stmt = (
                select(VitalsReading)
                .where(VitalsReading.patient_id == patient_id, VitalsReading.metric_code == code)
                .order_by(desc(VitalsReading.measured_at))
                .limit(1)
            )
            r = self.session.scalar(stmt)
            if r is not None:
                latest_readings.append(r)
        return latest_readings

    def get_patient_events_paginated(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        source: Optional[str] = None,
        is_simulated: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[IngestionEvent], int]:
        """
        Query paginated ingestion events for a patient with eager loaded vitals readings.
        Deterministic tie-breaker on event_id.
        Returns (list_of_events, total_count).
        """
        filters = [IngestionEvent.patient_id == patient_id]
        if start_time is not None:
            filters.append(IngestionEvent.measured_at >= start_time)
        if end_time is not None:
            filters.append(IngestionEvent.measured_at <= end_time)
        if source is not None:
            filters.append(IngestionEvent.source == source)
        if is_simulated is not None:
            filters.append(IngestionEvent.is_simulated == is_simulated)

        # 1. Total count
        count_stmt = select(func.count(IngestionEvent.event_id)).where(*filters)
        total_count = self.session.scalar(count_stmt) or 0

        # 2. Paginated results with joinedload to eliminate N+1 queries
        offset = (page - 1) * page_size
        stmt = (
            select(IngestionEvent)
            .options(joinedload(IngestionEvent.readings))
            .where(*filters)
            .order_by(desc(IngestionEvent.measured_at), desc(IngestionEvent.event_id))
            .offset(offset)
            .limit(page_size)
        )
        events = list(self.session.scalars(stmt).unique().all())
        return events, total_count

    def get_latest_patient_event(self, patient_id: str) -> Optional[IngestionEvent]:
        """
        Retrieve the latest IngestionEvent for a patient with eager loaded readings.
        Deterministic tie-breaker on event_id.
        """
        stmt = (
            select(IngestionEvent)
            .options(joinedload(IngestionEvent.readings))
            .where(IngestionEvent.patient_id == patient_id)
            .order_by(desc(IngestionEvent.measured_at), desc(IngestionEvent.event_id))
            .limit(1)
        )
        return self.session.scalars(stmt).unique().first()

