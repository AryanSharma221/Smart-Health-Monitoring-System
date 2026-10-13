"""
FastAPI WebSocket Router for Real-Time Health Telemetry and Alert Notifications.

Provides authenticated, patient-scoped real-time event delivery:
- Endpoints: /ws and /api/v1/ws
- Authentication: Token via query parameter (?token=...) or initial handshake message.
- Subscriptions: Patients auto-subscribed to own events; clinicians can subscribe to assigned patients.
- Monitored Events: reading.created, alert.created, alert.acknowledged.
- Disconnect: Automatic cleanup and unsubscription.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from database.mysql.models import User
from database.mysql.session import get_db
from services.api.config import Settings, get_settings
from services.websocket.auth import (
    authenticate_websocket_token,
    check_subscription_permission,
)
from services.websocket.manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Real-Time WebSockets"])

MAX_MESSAGE_BYTES = 65536  # 64 KB message size cap


@router.websocket("/ws")
@router.websocket("/api/v1/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Bearer JWT access token for connection authentication"),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> None:
    """
    Primary WebSocket gateway for real-time notifications.
    
    Handshake Protocol:
    1. If token is supplied via query param, validates immediately before accepting socket.
    2. If token is not in query, accepts connection in unauthenticated state and awaits an
       explicit {"action": "authenticate", "token": "..."} message within 5.0 seconds.
    3. Invalid or expired credentials result in socket closure (code 1008 Policy Violation).
    4. Authenticated patients are automatically subscribed to their own patient stream.
    5. Clinicians may dynamically subscribe/unsubscribe to assigned patient streams.
    """
    user: Optional[User] = None

    # Path A: Authenticate via query parameter before accepting socket
    if token:
        user = authenticate_websocket_token(token, db=db, settings=settings)
        if user is None:
            logger.warning("Rejecting WebSocket connection: invalid or expired query token.")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication failed")
            return
        await websocket.accept()

    # Path B: Accept and await initial authentication message
    else:
        await websocket.accept()
        try:
            raw_auth = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            auth_msg = json.loads(raw_auth)
            if auth_msg.get("action") != "authenticate" or not auth_msg.get("token"):
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "code": "AUTH_REQUIRED",
                    "detail": "Expected {'action': 'authenticate', 'token': '...'}",
                }))
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
                return

            msg_token = auth_msg.get("token", "")
            user = authenticate_websocket_token(msg_token, db=db, settings=settings)
            if user is None:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "code": "AUTH_FAILED",
                    "detail": "Invalid or expired access token.",
                }))
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication failed")
                return

        except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
            logger.debug("WebSocket client disconnected or timed out during initial auth handshake.")
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Auth timeout")
            except Exception:
                pass
            return

    # Extract user profile information for connection registry
    user_info = {
        "user_id": user.user_id,
        "role": user.role,
        "patient_id": getattr(user.patient_profile, "patient_id", None) if user.patient_profile else None,
    }

    # Register in connection manager (auto-subscribes patient to own ID)
    await connection_manager.connect(websocket, user_info)

    # Send welcome handshake confirmation
    await websocket.send_text(json.dumps({
        "type": "connection_established",
        "user_id": user.user_id,
        "role": user.role,
        "auto_subscribed_patient": user_info.get("patient_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))

    # Message Processing Loop
    try:
        while True:
            text_data = await websocket.receive_text()

            # Message size guardrail
            if len(text_data) > MAX_MESSAGE_BYTES:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "code": "MESSAGE_TOO_LARGE",
                    "detail": f"Inbound message exceeds {MAX_MESSAGE_BYTES} byte limit.",
                }))
                continue

            try:
                message = json.loads(text_data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "code": "MALFORMED_JSON",
                    "detail": "Message must be valid JSON object.",
                }))
                continue

            action = message.get("action")

            # 1. Ping / Keepalive
            if action == "ping":
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }))

            # 2. Subscribe to Patient Stream
            elif action == "subscribe":
                target_patient = message.get("patient_id")
                if not target_patient:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "code": "MISSING_PATIENT_ID",
                        "detail": "Action 'subscribe' requires 'patient_id' parameter.",
                    }))
                    continue

                # Enforce server-side patient-clinician authorization
                is_authorized, reason = check_subscription_permission(
                    user=user,
                    patient_id=str(target_patient),
                    db=db,
                )
                if not is_authorized:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "code": "SUBSCRIPTION_FORBIDDEN",
                        "detail": reason,
                        "patient_id": target_patient,
                    }))
                    continue

                await connection_manager.subscribe(websocket, str(target_patient))
                await websocket.send_text(json.dumps({
                    "type": "subscription_success",
                    "patient_id": target_patient,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }))

            # 3. Unsubscribe from Patient Stream
            elif action == "unsubscribe":
                target_patient = message.get("patient_id")
                if target_patient:
                    await connection_manager.unsubscribe(websocket, str(target_patient))
                    await websocket.send_text(json.dumps({
                        "type": "unsubscription_success",
                        "patient_id": target_patient,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }))

            # 4. Unknown Action
            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "code": "UNKNOWN_ACTION",
                    "detail": f"Action '{action}' is not supported. Allowed: ping, subscribe, unsubscribe.",
                }))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected gracefully for user %s", user.user_id)
    except Exception as exc:
        logger.warning("Unhandled exception on WebSocket connection for user %s: %s", user.user_id, exc)
    finally:
        await connection_manager.disconnect(websocket)
