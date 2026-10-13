"""
Clinical Alert Management Domain Service.

Enforces alert lifecycle state transitions (NEW -> ACKNOWLEDGED -> RESOLVED)
and ensures atomic synchronization across alerts, status history, and audit logs.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from database.mysql.exceptions import EntityNotFoundError, InvalidStateTransitionError
from database.mysql.models import Alert
from database.mysql.repositories.alert_repository import AlertRepository
from database.mysql.repositories.audit_repository import AuditRepository
from database.mysql.session import transaction_scope

logger = logging.getLogger(__name__)


class AlertService:
    """Coordinates alert lifecycle state transitions and audit logging."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.alert_repo = AlertRepository(session)
        self.audit_repo = AuditRepository(session)

    def get_alert(self, alert_id: str) -> Alert:
        """Fetch alert by alert_id or raise EntityNotFoundError."""
        alert = self.alert_repo.get_by_id(alert_id)
        if not alert:
            raise EntityNotFoundError("Alert", alert_id)
        return alert

    def list_alerts(
        self,
        patient_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Alert]:
        """List alerts filtered by patient or status."""
        return self.alert_repo.list_alerts(patient_id=patient_id, status=status, limit=limit)

    def acknowledge_alert(
        self,
        alert_id: str,
        actor_id: str,
        note: Optional[str] = None,
    ) -> Alert:
        """
        Acknowledge an open alert atomically.
        Transitions state to ACKNOWLEDGED, creates an alert_status_history entry,
        and logs a security audit record within a single database transaction.
        """
        with transaction_scope(self.session):
            alert = self.get_alert(alert_id)

            if alert.status == "RESOLVED":
                raise InvalidStateTransitionError("Cannot acknowledge an already resolved alert.")

            if alert.status == "ACKNOWLEDGED":
                logger.info("Alert '%s' is already acknowledged. Skipping state update.", alert_id)
                return alert

            # Record state transition and history
            self.alert_repo.record_status_transition(
                alert=alert,
                new_status="ACKNOWLEDGED",
                actor_id=actor_id,
                note=note,
            )

            # Record compliance audit log
            self.audit_repo.record(
                actor_id=actor_id,
                action="ALERT_ACKNOWLEDGE",
                target_type="alert",
                target_id=alert_id,
                metadata_json=f'{{"patient_id": "{alert.patient_id}", "previous_status": "NEW"}}',
            )

        return alert

    def resolve_alert(
        self,
        alert_id: str,
        actor_id: str,
        note: Optional[str] = None,
    ) -> Alert:
        """
        Resolve an alert atomically.
        Transitions state to RESOLVED, creates an alert_status_history entry,
        and logs a security audit record within a single database transaction.
        """
        with transaction_scope(self.session):
            alert = self.get_alert(alert_id)

            if alert.status == "RESOLVED":
                logger.info("Alert '%s' is already resolved. Skipping state update.", alert_id)
                return alert

            old_status = alert.status

            # Record state transition and history
            self.alert_repo.record_status_transition(
                alert=alert,
                new_status="RESOLVED",
                actor_id=actor_id,
                note=note,
            )

            # Record compliance audit log
            self.audit_repo.record(
                actor_id=actor_id,
                action="ALERT_RESOLVE",
                target_type="alert",
                target_id=alert_id,
                metadata_json=f'{{"patient_id": "{alert.patient_id}", "previous_status": "{old_status}"}}',
            )

        return alert
