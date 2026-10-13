"""
Real-Time WebSockets Package.
"""

from services.websocket.auth import (
    authenticate_websocket_token,
    check_subscription_permission,
)
from services.websocket.dispatcher import (
    dispatch_event,
    dispatch_event_async,
    notify_alert_acknowledged,
    notify_alert_created,
    notify_reading_created,
)
from services.websocket.manager import ConnectionManager, connection_manager
from services.websocket.messages import (
    RealtimeEvent,
    build_alert_acknowledged_event,
    build_alert_created_event,
    build_reading_created_event,
)

__all__ = [
    "ConnectionManager",
    "connection_manager",
    "RealtimeEvent",
    "build_reading_created_event",
    "build_alert_created_event",
    "build_alert_acknowledged_event",
    "authenticate_websocket_token",
    "check_subscription_permission",
    "dispatch_event",
    "dispatch_event_async",
    "notify_reading_created",
    "notify_alert_created",
    "notify_alert_acknowledged",
]
