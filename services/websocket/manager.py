"""
Centralized In-Memory WebSocket Connection and Subscription Manager.

Manages:
1. Active WebSocket connections and authenticated user identities.
2. Patient-scoped subscriptions for both patients and assigned clinicians.
3. Thread-safe subscription registry with asynchronous locking.
4. Bounded, non-blocking broadcasts with individual send timeouts (slow client isolation).
5. Clean disconnection handling and resource disposal on server shutdown.

NOTE: This is an in-memory manager suitable for single-process deployments.
Cross-worker horizontal scaling across multiple ASGI processes requires a message broker (e.g. Redis).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and patient event subscriptions."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._socket_user: Dict[WebSocket, Dict[str, Any]] = {}
        self._patient_subs: Dict[str, Set[WebSocket]] = {}
        self._socket_subs: Dict[WebSocket, Set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_info: Dict[str, Any]) -> None:
        """Register newly authenticated WebSocket connection."""
        async with self._lock:
            self._connections.add(websocket)
            self._socket_user[websocket] = user_info
            self._socket_subs[websocket] = set()

            # Auto-subscribe patients to their own patient ID
            patient_id = user_info.get("patient_id")
            if user_info.get("role") == "patient" and patient_id:
                if patient_id not in self._patient_subs:
                    self._patient_subs[patient_id] = set()
                self._patient_subs[patient_id].add(websocket)
                self._socket_subs[websocket].add(patient_id)
                logger.info("Patient auto-subscribed to patient_id '%s'", patient_id)

        logger.info(
            "WebSocket connected for user %s (role: %s). Total active connections: %d",
            user_info.get("user_id"),
            user_info.get("role"),
            len(self._connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove connection and clean up all subscriptions."""
        async with self._lock:
            self._connections.discard(websocket)
            user_info = self._socket_user.pop(websocket, None)

            # Clean up all patient subscriptions for this socket
            subscribed_patients = self._socket_subs.pop(websocket, set())
            for pid in subscribed_patients:
                if pid in self._patient_subs:
                    self._patient_subs[pid].discard(websocket)
                    if not self._patient_subs[pid]:
                        del self._patient_subs[pid]

        user_id = user_info.get("user_id") if user_info else "unknown"
        logger.info(
            "WebSocket disconnected for user %s. Remaining active connections: %d",
            user_id,
            len(self._connections),
        )

    async def subscribe(self, websocket: WebSocket, patient_id: str) -> None:
        """Subscribe an active connection to events for a specific patient."""
        async with self._lock:
            if websocket not in self._connections:
                return

            if patient_id not in self._patient_subs:
                self._patient_subs[patient_id] = set()
            self._patient_subs[patient_id].add(websocket)

            if websocket in self._socket_subs:
                self._socket_subs[websocket].add(patient_id)

        logger.debug("Socket subscribed to patient '%s'", patient_id)

    async def unsubscribe(self, websocket: WebSocket, patient_id: str) -> None:
        """Unsubscribe connection from events for a specific patient."""
        async with self._lock:
            if patient_id in self._patient_subs:
                self._patient_subs[patient_id].discard(websocket)
                if not self._patient_subs[patient_id]:
                    del self._patient_subs[patient_id]

            if websocket in self._socket_subs:
                self._socket_subs[websocket].discard(patient_id)

        logger.debug("Socket unsubscribed from patient '%s'", patient_id)

    async def broadcast_to_patient(
        self,
        patient_id: str,
        event_dict: Dict[str, Any],
        send_timeout: float = 2.0,
    ) -> int:
        """
        Deliver an event to all authorized subscribers of patient_id.
        Applies a bounded send timeout so slow/hung clients do not block other clients.
        Returns the count of successfully notified subscribers.
        """
        async with self._lock:
            sockets = list(self._patient_subs.get(patient_id, set()))

        if not sockets:
            logger.debug("No active subscribers for patient '%s'. Event dropped from live stream.", patient_id)
            return 0

        payload = json.dumps(event_dict)
        successful_sends = 0
        dead_sockets: List[WebSocket] = []

        for ws in sockets:
            try:
                # Enforce bounded send timeout to isolate slow clients
                await asyncio.wait_for(ws.send_text(payload), timeout=send_timeout)
                successful_sends += 1
            except (WebSocketDisconnect, asyncio.TimeoutError, Exception) as exc:
                logger.warning("Error delivering to socket subscriber: %s. Scheduling disconnect.", exc)
                dead_sockets.append(ws)

        # Clean up any dead or timed-out sockets
        for dead_ws in dead_sockets:
            await self.disconnect(dead_ws)

        return successful_sends

    async def broadcast_system(self, event_dict: Dict[str, Any], send_timeout: float = 2.0) -> int:
        """Broadcast system-wide event to all active connections."""
        async with self._lock:
            sockets = list(self._connections)

        payload = json.dumps(event_dict)
        successful = 0
        for ws in sockets:
            try:
                await asyncio.wait_for(ws.send_text(payload), timeout=send_timeout)
                successful += 1
            except Exception:
                pass
        return successful

    def get_stats(self) -> Dict[str, Any]:
        """Diagnostic snapshot of active connections and subscriptions."""
        return {
            "active_connections": len(self._connections),
            "subscribed_patients_count": len(self._patient_subs),
            "subscribed_patient_ids": list(self._patient_subs.keys()),
        }

    async def close_all(self, code: int = 1001, reason: str = "Server shutting down") -> None:
        """Gracefully close all open WebSockets during application shutdown."""
        async with self._lock:
            sockets = list(self._connections)
            self._connections.clear()
            self._socket_user.clear()
            self._patient_subs.clear()
            self._socket_subs.clear()

        for ws in sockets:
            try:
                await ws.close(code=code, reason=reason)
            except Exception:
                pass
        logger.info("Closed all active WebSocket connections (%d total).", len(sockets))


# Global singleton connection manager instance
connection_manager = ConnectionManager()
