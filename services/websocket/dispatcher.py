"""
Real-Time Event Dispatcher.

Integrates authoritative MySQL persistence with WebSocket notifications:
- Dispatches notifications only AFTER transactions are successfully committed.
- Binds to the active asyncio loop or fails gracefully if no loop is active.
- Delivery failures never roll back or invalidate authoritative MySQL records.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from database.mysql.models import Alert, IngestionEvent, Message
from services.websocket.manager import connection_manager
from services.websocket.messages import (
    RealtimeEvent,
    build_alert_acknowledged_event,
    build_alert_created_event,
    build_message_created_event,
    build_message_read_event,
    build_reading_created_event,
)

logger = logging.getLogger(__name__)


def dispatch_event(event: RealtimeEvent) -> None:
    """
    Safely schedule event broadcast on the active asyncio event loop.
    Non-blocking: if called from synchronous code or background threads,
    dispatches as an async task on the running loop or executes via temporary runner.
    """
    event_dict = event.model_dump()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(connection_manager.broadcast_to_patient(event.patient_id, event_dict))
    except RuntimeError:
        # No running event loop in this thread (e.g. running in synchronous worker or TestClient)
        try:
            asyncio.run(connection_manager.broadcast_to_patient(event.patient_id, event_dict))
        except Exception as exc:
            logger.debug("Live WebSocket dispatch failed without running loop: %s", exc)


async def dispatch_event_async(event: RealtimeEvent) -> int:
    """
    Direct asynchronous broadcast of a RealtimeEvent.
    Returns the count of subscribers successfully notified.
    """
    event_dict = event.model_dump()
    return await connection_manager.broadcast_to_patient(event.patient_id, event_dict)


def notify_reading_created(event: IngestionEvent) -> None:
    """Emit reading.created event after IngestionEvent has been committed in MySQL."""
    event_msg = build_reading_created_event(event)
    dispatch_event(event_msg)


def notify_alert_created(alert: Alert) -> None:
    """Emit alert.created event after Alert has been committed in MySQL."""
    event_msg = build_alert_created_event(alert)
    dispatch_event(event_msg)


def notify_alert_acknowledged(alert: Alert, actor_id: str, note: Optional[str] = None) -> None:
    """Emit alert.acknowledged event after acknowledgement has been committed in MySQL."""
    event_msg = build_alert_acknowledged_event(alert, actor_id=actor_id, note=note)
    dispatch_event(event_msg)


def notify_message_created(message: Message, patient_id: str) -> None:
    """Emit message.created event after Message has been committed in MySQL."""
    event_msg = build_message_created_event(message, patient_id=patient_id)
    dispatch_event(event_msg)


def notify_message_read(
    conversation_id: str,
    patient_id: str,
    read_by: str,
    count: int,
    read_at: str,
) -> None:
    """Emit message.read event after read status has been committed in MySQL."""
    event_msg = build_message_read_event(
        conversation_id=conversation_id,
        patient_id=patient_id,
        read_by=read_by,
        count=count,
        read_at=read_at,
    )
    dispatch_event(event_msg)

