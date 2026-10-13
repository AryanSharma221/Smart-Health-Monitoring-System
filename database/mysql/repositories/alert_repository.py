"""
Clinical Alerts and Alert Lifecycle Repository.

Encapsulates database operations for active alerts, state changes, and transition history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc, select
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
