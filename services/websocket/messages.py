"""
WebSocket Real-Time Event Message Schemas and Serialization.

Defines standardized, versioned event schemas for notifications:
- reading.created: New physiological observation persisted in MySQL.
- alert.created: New clinical alert triggered and persisted in MySQL.
- alert.acknowledged: Alert reviewed and acknowledged by clinician.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from database.mysql.models import Alert, IngestionEvent, Message


class RealtimeEvent(BaseModel):
    """Authoritative envelope for all real-time notifications."""

    event_id: str = Field(default_factory=lambda: f"ws_evt_{uuid.uuid4().hex[:16]}")
    event_type: str = Field(..., description="Action category (e.g., reading.created, alert.created)")
    schema_version: int = Field(default=1, description="Message format schema version")
    occurred_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Event creation timestamp in ISO 8601 UTC",
    )
    patient_id: str = Field(..., description="Target patient domain identifier")
    resource_id: str = Field(..., description="Authoritative MySQL resource primary key")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event-specific metadata")


def build_reading_created_event(event: IngestionEvent) -> RealtimeEvent:
    """
    Build a minimal notification for a newly committed health reading.
    Omits full medical payloads to ensure clients fetch authoritative data via REST API.
    """
    metrics_present = [r.metric_code for r in getattr(event, "readings", [])]
    return RealtimeEvent(
        event_type="reading.created",
        occurred_at=event.measured_at.isoformat() if hasattr(event.measured_at, "isoformat") else datetime.now(timezone.utc).isoformat(),
        patient_id=event.patient_id,
        resource_id=event.event_id,
        payload={
            "source": event.source,
            "is_simulated": event.is_simulated,
            "metrics": sorted(list(set(metrics_present))),
        },
    )


def build_alert_created_event(alert: Alert) -> RealtimeEvent:
    """Build notification for newly triggered clinical alert."""
    return RealtimeEvent(
        event_type="alert.created",
        occurred_at=alert.created_at.isoformat() if hasattr(alert.created_at, "isoformat") else datetime.now(timezone.utc).isoformat(),
        patient_id=alert.patient_id,
        resource_id=alert.alert_id,
        payload={
            "rule_id": alert.rule_id,
            "severity": alert.severity,
            "category": alert.category,
            "status": alert.status,
            "reason": alert.reason[:250],
        },
    )


def build_alert_acknowledged_event(
    alert: Alert,
    actor_id: str,
    note: Optional[str] = None,
) -> RealtimeEvent:
    """Build notification for an acknowledged alert."""
    now_iso = datetime.now(timezone.utc).isoformat()
    ack_time = alert.acknowledged_at.isoformat() if alert.acknowledged_at else now_iso
    return RealtimeEvent(
        event_type="alert.acknowledged",
        occurred_at=ack_time,
        patient_id=alert.patient_id,
        resource_id=alert.alert_id,
        payload={
            "status": "ACKNOWLEDGED",
            "acknowledged_by": actor_id,
            "acknowledged_at": ack_time,
            "note": note[:200] if note else None,
        },
    )


def build_message_created_event(message: Message, patient_id: str) -> RealtimeEvent:
    """Build notification for a newly committed direct message."""
    now_iso = (
        message.created_at.isoformat()
        if hasattr(message.created_at, "isoformat")
        else datetime.now(timezone.utc).isoformat()
    )
    return RealtimeEvent(
        event_type="message.created",
        occurred_at=now_iso,
        patient_id=patient_id,
        resource_id=message.message_id,
        payload={
            "conversation_id": message.conversation_id,
            "message_id": message.message_id,
            "sender_id": message.sender_id,
            "receiver_id": message.receiver_id,
            "created_at": now_iso,
        },
    )


def build_message_read_event(
    conversation_id: str,
    patient_id: str,
    read_by: str,
    count: int,
    read_at: str,
) -> RealtimeEvent:
    """Build notification for messages marked as read in a conversation."""
    return RealtimeEvent(
        event_type="message.read",
        occurred_at=read_at,
        patient_id=patient_id,
        resource_id=conversation_id,
        payload={
            "conversation_id": conversation_id,
            "read_by": read_by,
            "messages_marked_read": count,
            "read_at": read_at,
        },
    )

