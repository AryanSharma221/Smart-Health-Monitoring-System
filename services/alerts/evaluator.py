"""
Clinical Alert Evaluation Engine.

Evaluates incoming ingestion events and vital readings against configured clinical rules.
Enforces:
1. Source provenance eligibility (live/simulated vs historical batch data).
2. Deterministic alert ID generation.
3. Idempotent alert creation preventing duplicate alerts for identical event & rule.
4. Comprehensive audit logging and initial status history creation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from database.mysql.models import Alert, AlertStatusHistory, IngestionEvent, VitalsReading
from database.mysql.repositories.alert_repository import AlertRepository
from database.mysql.repositories.audit_repository import AuditRepository
from database.mysql.session import transaction_scope
from services.alerts.config import is_source_eligible_for_alerts
from services.alerts.rules import DEFAULT_ALERT_RULES, AlertRuleDefinition

logger = logging.getLogger(__name__)


def generate_deterministic_alert_id(event_id: str, rule_id: str) -> str:
    """Generate deterministic, collision-resistant alert ID from event and rule."""
    payload = f"{event_id}:{rule_id}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return f"alt_{digest}"


class AlertEvaluator:
    """Evaluates telemetry readings and ingestion events for clinical threshold breaches."""

    def __init__(self, session: Session, rules: Optional[Sequence[AlertRuleDefinition]] = None) -> None:
        self.session = session
        self.rules = list(rules) if rules is not None else DEFAULT_ALERT_RULES
        self.alert_repo = AlertRepository(session)
        self.audit_repo = AuditRepository(session)

    def evaluate_event(
        self,
        event: IngestionEvent,
        allow_historical: bool = False,
    ) -> List[Alert]:
        """
        Evaluate all vitals readings in an IngestionEvent against configured rules.
        
        Guarantees:
        1. Checks source provenance eligibility.
        2. Evaluates only valid quality readings.
        3. Persists alerts idempotently.
        4. Logs audit trail for newly triggered alerts.
        """
        if not is_source_eligible_for_alerts(
            source=event.source,
            is_simulated=event.is_simulated,
            allow_historical=allow_historical,
        ):
            logger.debug(
                "Skipping alert evaluation for ineligible event %s (source=%s, simulated=%s)",
                event.event_id,
                event.source,
                event.is_simulated,
            )
            return []

        triggered_alerts: List[Alert] = []
        new_alerts: List[Alert] = []

        with transaction_scope(self.session):
            for reading in event.readings:
                alerts_for_reading, newly_created = self._evaluate_reading_in_tx(
                    reading=reading,
                    event=event,
                    allow_historical=allow_historical,
                )
                triggered_alerts.extend(alerts_for_reading)
                new_alerts.extend(newly_created)

        # Notify strictly AFTER transaction has committed
        for alert in new_alerts:
            try:
                from services.websocket.dispatcher import notify_alert_created

                notify_alert_created(alert)
            except Exception as exc:
                logger.warning("Failed to emit WebSocket alert.created: %s", exc)

        return triggered_alerts

    def evaluate_readings_batch(
        self,
        event: IngestionEvent,
        readings: Sequence[VitalsReading],
        allow_historical: bool = False,
    ) -> List[Alert]:
        """
        Evaluate an explicit list of readings belonging to an event.
        Useful when readings have not yet been assigned to event.readings relationship.
        """
        if not is_source_eligible_for_alerts(
            source=event.source,
            is_simulated=event.is_simulated,
            allow_historical=allow_historical,
        ):
            return []

        triggered_alerts: List[Alert] = []
        new_alerts: List[Alert] = []

        with transaction_scope(self.session):
            for reading in readings:
                alerts_for_reading, newly_created = self._evaluate_reading_in_tx(
                    reading=reading,
                    event=event,
                    allow_historical=allow_historical,
                )
                triggered_alerts.extend(alerts_for_reading)
                new_alerts.extend(newly_created)

        # Notify strictly AFTER transaction has committed
        for alert in new_alerts:
            try:
                from services.websocket.dispatcher import notify_alert_created

                notify_alert_created(alert)
            except Exception as exc:
                logger.warning("Failed to emit WebSocket alert.created: %s", exc)

        return triggered_alerts

    def _evaluate_reading_in_tx(
        self,
        reading: VitalsReading,
        event: IngestionEvent,
        allow_historical: bool = False,
    ) -> tuple[List[Alert], List[Alert]]:
        """Internal helper to evaluate a single reading within an active transaction."""
        alerts: List[Alert] = []
        newly_created: List[Alert] = []

        for rule in self.rules:
            if not rule.evaluate(reading):
                continue

            alert_id = generate_deterministic_alert_id(event.event_id, rule.rule_id)
            
            # Construct human-readable reason with clinical provenance tag
            reason = f"[{rule.severity}] {rule.description} Observed: {reading.value} {reading.unit}."
            if not event.is_simulated and allow_historical:
                reason += " [Historical Backfill — Non-Live Record]"

            candidate_alert = Alert(
                alert_id=alert_id,
                patient_id=event.patient_id,
                event_id=event.event_id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                reason=reason,
                status="NEW",
            )

            persisted_alert, was_created = self.alert_repo.create_or_get_alert(candidate_alert)

            if was_created:
                # Record initial lifecycle status history
                history = AlertStatusHistory(
                    alert_id=persisted_alert.alert_id,
                    old_status=None,
                    new_status="NEW",
                    actor_id=None,
                    note="Triggered by threshold evaluation engine.",
                )
                self.session.add(history)

                # Record compliance audit log
                metadata = {
                    "patient_id": event.patient_id,
                    "event_id": event.event_id,
                    "rule_id": rule.rule_id,
                    "metric_code": reading.metric_code,
                    "value": str(reading.value),
                    "unit": reading.unit,
                    "severity": rule.severity,
                    "source": event.source,
                    "is_simulated": event.is_simulated,
                }
                self.audit_repo.record(
                    action="ALERT_TRIGGERED",
                    target_type="alert",
                    target_id=persisted_alert.alert_id,
                    actor_id=None,
                    metadata_json=json.dumps(metadata),
                )
                logger.info(
                    "Clinical alert %s created for patient %s (rule=%s, metric=%s)",
                    persisted_alert.alert_id,
                    event.patient_id,
                    rule.rule_id,
                    reading.metric_code,
                )
                newly_created.append(persisted_alert)

            alerts.append(persisted_alert)

        return alerts, newly_created
