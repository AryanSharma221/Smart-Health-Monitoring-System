"""
Clinical Alerts and Alert Lifecycle Repository.

Encapsulates database operations for active alerts, state changes, and transition history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.mysql.models import Alert, AlertStatusHistory


class AlertRepository:
    """Encapsulates relational persistence queries for alerts and alert lifecycle state."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, alert: Alert) -> Alert:
        """Stage a new clinical alert."""
        self.session.add(alert)
        self.session.flush()
        return alert

    def get_by_id(self, alert_id: str) -> Optional[Alert]:
        """Fetch alert by alert_id."""
        return self.session.get(Alert, alert_id)

    def get_by_event_and_rule(self, event_id: str, rule_id: str) -> Optional[Alert]:
        """Fetch alert by triggering event_id and rule_id."""
        stmt = select(Alert).where(Alert.event_id == event_id, Alert.rule_id == rule_id)
        return self.session.scalars(stmt).first()

    def create_or_get_alert(self, alert: Alert) -> tuple[Alert, bool]:
        """
        Atomically persist an alert or return existing if duplicate.
        Returns (alert, was_created).
        Guarantees idempotency via database unique constraint and nested savepoints.
        """
        if alert.event_id and alert.rule_id:
            existing = self.get_by_event_and_rule(alert.event_id, alert.rule_id)
            if existing:
                return existing, False

        existing_id = self.get_by_id(alert.alert_id)
        if existing_id:
            return existing_id, False

        try:
            with self.session.begin_nested():
                self.session.add(alert)
                self.session.flush()
            return alert, True
        except IntegrityError:
            if alert.event_id and alert.rule_id:
                existing = self.get_by_event_and_rule(alert.event_id, alert.rule_id)
                if existing:
                    return existing, False
            existing_id = self.get_by_id(alert.alert_id)
            if existing_id:
                return existing_id, False
            raise

    def list_patient_alerts_paginated(
        self,
        patient_id: str,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Alert], int]:
        """
        Query paginated alerts for a patient with optional filtering by status and severity.
        Deterministic tie-breaker on alert_id.
        Returns (list_of_alerts, total_count).
        """
        filters = [Alert.patient_id == patient_id]
        if status:
            filters.append(Alert.status == status)
        if severity:
            filters.append(Alert.severity == severity)
        if start_time:
            filters.append(Alert.created_at >= start_time)
        if end_time:
            filters.append(Alert.created_at <= end_time)

        # 1. Total count
        count_stmt = select(func.count(Alert.alert_id)).where(*filters)
        total_count = self.session.scalar(count_stmt) or 0

        # 2. Paginated results ordered by creation time descending, tie-breaker alert_id
        offset = (page - 1) * page_size
        stmt = (
            select(Alert)
            .where(*filters)
            .order_by(desc(Alert.created_at), desc(Alert.alert_id))
            .offset(offset)
            .limit(page_size)
        )
        alerts = list(self.session.scalars(stmt).all())
        return alerts, total_count

    def list_alerts(
        self,
        patient_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Alert]:
        """
        List alerts optionally filtered by patient and/or status.
        Accelerated by composite index idx_alerts_patient_status_time or idx_alerts_status_created.
        """
        stmt = select(Alert)
        if patient_id:
            stmt = stmt.where(Alert.patient_id == patient_id)
        if status:
            stmt = stmt.where(Alert.status == status)

        stmt = stmt.order_by(desc(Alert.created_at)).limit(limit)
        return list(self.session.scalars(stmt).all())

    def record_status_transition(
        self,
        alert: Alert,
        new_status: str,
        actor_id: Optional[str] = None,
        note: Optional[str] = None,
    ) -> AlertStatusHistory:
        """
        Record a state change on an alert and append an entry to alert_status_history.
        """
        now = datetime.now(timezone.utc)
        old_status = alert.status
        alert.status = new_status

        if new_status == "ACKNOWLEDGED":
            alert.acknowledged_by = actor_id
            alert.acknowledged_at = now
        elif new_status == "RESOLVED":
            alert.resolved_by = actor_id
            alert.resolved_at = now

        history = AlertStatusHistory(
            alert_id=alert.alert_id,
            old_status=old_status,
            new_status=new_status,
            actor_id=actor_id,
            note=note,
            changed_at=now,
        )
        self.session.add(history)
        self.session.flush()
        return history

    def get_history(self, alert_id: str) -> List[AlertStatusHistory]:
        """Retrieve audit history trail for an alert ordered chronologically."""
        stmt = (
            select(AlertStatusHistory)
            .where(AlertStatusHistory.alert_id == alert_id)
            .order_by(AlertStatusHistory.changed_at.asc())
        )
        return list(self.session.scalars(stmt).all())
