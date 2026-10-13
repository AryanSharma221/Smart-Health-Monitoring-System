"""
Unit and Integration Tests for Real-Time WebSockets Protocol and Event Delivery.

Verifies:
1. Unauthenticated connection rejection via query token (WS 1008 Policy Violation).
2. Unauthenticated connection rejection via handshake message timeout/failure.
3. Successful authentication via query parameter (?token=...).
4. Successful authentication via initial handshake message ({"action": "authenticate", ...}).
5. Parity between root /ws and versioned /api/v1/ws endpoints.
6. Patient auto-subscription to own patient ID upon connection.
7. Patient forbidden from subscribing to other patients (SUBSCRIPTION_FORBIDDEN).
8. Clinician permitted to subscribe to assigned patients.
9. Clinician forbidden from subscribing to unassigned patients.
10. Admin operator permitted to subscribe to any patient.
11. Clinician unsubscription workflow.
12. Ping/pong keepalive protocol.
13. Malformed JSON message handling (MALFORMED_JSON).
14. Unknown action handling (UNKNOWN_ACTION).
15. Missing patient_id validation in subscribe action.
16. Inbound message size cap enforcement (MESSAGE_TOO_LARGE).
17. Inactive user rejection.
18. Expired token rejection.
19. Live event delivery: reading.created.
20. Live event delivery: alert.created.
21. Live event delivery: alert.acknowledged.
22. Slow client isolation and bounded send timeouts.
23. ConnectionManager stats and graceful shutdown (close_all).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import WebSocketDisconnect, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    Alert,
    Base,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from services.websocket.auth import authenticate_websocket_token, check_subscription_permission
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


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def test_settings() -> Settings:
    """Isolated test settings with dedicated JWT test secret."""
    return Settings(
        app_env="testing",
        jwt_secret="testing_secret_key_at_least_32_characters_long_for_security!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
    )


@pytest.fixture(scope="function")
def test_db_session() -> Generator[Session, None, None]:
    """In-memory SQLite session with StaticPool."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def client(test_db_session: Session, test_settings: Settings) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden database and settings."""
    app = create_app(settings=test_settings)

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="function")
def test_data(test_db_session: Session, test_settings: Settings) -> dict:
    """Seed test users: Alice (Patient P101), Bob (Patient P102), Dr. Carol (Assigned to P101), Dr. Dave (Unassigned), Admin Eve, Inactive Frank."""
    # 1. Patient Alice (P101)
    u_alice = User(
        user_id="usr_alice",
        email="alice@test.local",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="patient",
        is_active=True,
    )
    prof_alice = PatientProfile(patient_id="P101", user_id="usr_alice", first_name="Alice", last_name="Smith")

    # 2. Patient Bob (P102)
    u_bob = User(
        user_id="usr_bob",
        email="bob@test.local",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="patient",
        is_active=True,
    )
    prof_bob = PatientProfile(patient_id="P102", user_id="usr_bob", first_name="Bob", last_name="Jones")

    # 3. Doctor Carol (DOC_001) - assigned to P101
    u_carol = User(
        user_id="usr_carol",
        email="carol@hospital.org",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="doctor",
        is_active=True,
    )
    prof_carol = DoctorProfile(
        doctor_id="DOC_001",
        user_id="usr_carol",
        first_name="Carol",
        last_name="Danvers",
        license_number="MD-CAROL-12345",
    )
    assign_carol = DoctorPatientAssignment(
        doctor_id="DOC_001",
        patient_id="P101",
        is_active=True,
        notes="Primary cardiologist",
    )

    # 4. Doctor Dave (DOC_002) - unassigned
    u_dave = User(
        user_id="usr_dave",
        email="dave@hospital.org",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="doctor",
        is_active=True,
    )
    prof_dave = DoctorProfile(
        doctor_id="DOC_002",
        user_id="usr_dave",
        first_name="Dave",
        last_name="Bowman",
        license_number="MD-DAVE-67890",
    )

    # 5. Admin Eve
    u_eve = User(
        user_id="usr_eve",
        email="eve@hospital.org",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="admin_operator",
        is_active=True,
    )

    # 6. Inactive Frank
    u_frank = User(
        user_id="usr_frank",
        email="frank@test.local",
        password_hash=hash_password("Pass1234!", rounds=4),
        role="patient",
        is_active=False,
    )

    test_db_session.add_all([
        u_alice, prof_alice,
        u_bob, prof_bob,
        u_carol, prof_carol, assign_carol,
        u_dave, prof_dave,
        u_eve,
        u_frank,
    ])
    test_db_session.commit()

    # Generate test tokens
    alice_token = create_access_token({"sub": "usr_alice", "role": "patient"}, settings=test_settings)
    bob_token = create_access_token({"sub": "usr_bob", "role": "patient"}, settings=test_settings)
    carol_token = create_access_token({"sub": "usr_carol", "role": "doctor"}, settings=test_settings)
    dave_token = create_access_token({"sub": "usr_dave", "role": "doctor"}, settings=test_settings)
    eve_token = create_access_token({"sub": "usr_eve", "role": "admin_operator"}, settings=test_settings)
    frank_token = create_access_token({"sub": "usr_frank", "role": "patient"}, settings=test_settings)
    expired_token = create_access_token(
        {"sub": "usr_alice", "role": "patient"},
        expires_delta=timedelta(minutes=-10),
        settings=test_settings,
    )

    return {
        "alice_token": alice_token,
        "bob_token": bob_token,
        "carol_token": carol_token,
        "dave_token": dave_token,
        "eve_token": eve_token,
        "frank_token": frank_token,
        "expired_token": expired_token,
    }


# =============================================================================
# 1. Authentication Handshake Tests
# =============================================================================

def test_ws_unauthenticated_query_token_rejected(client: TestClient):
    """Connecting with an invalid query token closes connection with 1008 Policy Violation."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws?token=invalid_garbage_token"):
            pass
    assert excinfo.value.code == status.WS_1008_POLICY_VIOLATION


def test_ws_expired_query_token_rejected(client: TestClient, test_data: dict):
    """Connecting with an expired JWT closes connection with 1008 Policy Violation."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws?token={test_data['expired_token']}"):
            pass
    assert excinfo.value.code == status.WS_1008_POLICY_VIOLATION


def test_ws_inactive_user_rejected(client: TestClient, test_data: dict):
    """Deactivated user token is rejected with 1008 Policy Violation."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws?token={test_data['frank_token']}"):
            pass
    assert excinfo.value.code == status.WS_1008_POLICY_VIOLATION


def test_ws_handshake_message_auth_success(client: TestClient, test_data: dict):
    """Connecting without query token, then sending auth message succeeds."""
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"action": "authenticate", "token": test_data["alice_token"]}))
        resp = ws.receive_json()
        assert resp["type"] == "connection_established"
        assert resp["user_id"] == "usr_alice"
        assert resp["role"] == "patient"
        assert resp["auto_subscribed_patient"] == "P101"


def test_ws_handshake_message_auth_failure(client: TestClient):
    """Connecting without query token, then sending invalid token closes with 1008."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"action": "authenticate", "token": "bad_token"}))
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["code"] == "AUTH_FAILED"
            # Next receive should raise WebSocketDisconnect
            ws.receive_text()
    assert excinfo.value.code == status.WS_1008_POLICY_VIOLATION


def test_ws_handshake_message_missing_token_or_action(client: TestClient):
    """Connecting without query token, then sending invalid action closes with 1008."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"action": "not_auth"}))
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["code"] == "AUTH_REQUIRED"
            ws.receive_text()
    assert excinfo.value.code == status.WS_1008_POLICY_VIOLATION


def test_ws_query_token_success_patient(client: TestClient, test_data: dict):
    """Connecting with valid query token establishes connection immediately."""
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        resp = ws.receive_json()
        assert resp["type"] == "connection_established"
        assert resp["user_id"] == "usr_alice"
        assert resp["role"] == "patient"
        assert resp["auto_subscribed_patient"] == "P101"


def test_ws_versioned_endpoint_parity(client: TestClient, test_data: dict):
    """Endpoint /api/v1/ws behaves identically to /ws."""
    with client.websocket_connect(f"/api/v1/ws?token={test_data['alice_token']}") as ws:
        resp = ws.receive_json()
        assert resp["type"] == "connection_established"
        assert resp["user_id"] == "usr_alice"


# =============================================================================
# 2. Subscription RBAC and Scoping Tests
# =============================================================================

def test_ws_patient_forbidden_from_subscribing_to_other_patients(client: TestClient, test_data: dict):
    """Patient Alice (P101) cannot subscribe to Patient Bob (P102)."""
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "subscribe", "patient_id": "P102"}))
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "SUBSCRIPTION_FORBIDDEN"
        assert "Access denied" in resp["detail"]


def test_ws_patient_subscribing_to_own_patient_id(client: TestClient, test_data: dict):
    """Patient Alice can explicitly subscribe to own patient ID P101."""
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "subscribe", "patient_id": "P101"}))
        resp = ws.receive_json()
        assert resp["type"] == "subscription_success"
        assert resp["patient_id"] == "P101"


def test_ws_clinician_assigned_subscription_success(client: TestClient, test_data: dict):
    """Doctor Carol (assigned to P101) successfully subscribes to P101."""
    with client.websocket_connect(f"/ws?token={test_data['carol_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "subscribe", "patient_id": "P101"}))
        resp = ws.receive_json()
        assert resp["type"] == "subscription_success"
        assert resp["patient_id"] == "P101"


def test_ws_clinician_unassigned_subscription_forbidden(client: TestClient, test_data: dict):
    """Doctor Dave (NOT assigned to P101) is rejected when subscribing to P101."""
    with client.websocket_connect(f"/ws?token={test_data['dave_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "subscribe", "patient_id": "P101"}))
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "SUBSCRIPTION_FORBIDDEN"
        assert "not assigned" in resp["detail"]


def test_ws_admin_subscription_allowed(client: TestClient, test_data: dict):
    """Admin Eve has operational clearance to subscribe to any patient."""
    with client.websocket_connect(f"/ws?token={test_data['eve_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "subscribe", "patient_id": "P101"}))
        resp = ws.receive_json()
        assert resp["type"] == "subscription_success"
        assert resp["patient_id"] == "P101"


def test_ws_unsubscribe_action(client: TestClient, test_data: dict):
    """Clinician can unsubscribe from a previously subscribed patient."""
    with client.websocket_connect(f"/ws?token={test_data['carol_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "subscribe", "patient_id": "P101"}))
        sub_resp = ws.receive_json()
        assert sub_resp["type"] == "subscription_success"

        ws.send_text(json.dumps({"action": "unsubscribe", "patient_id": "P101"}))
        unsub_resp = ws.receive_json()
        assert unsub_resp["type"] == "unsubscription_success"
        assert unsub_resp["patient_id"] == "P101"


# =============================================================================
# 3. Protocol, Keepalive, and Inbound Guardrails
# =============================================================================

def test_ws_ping_pong(client: TestClient, test_data: dict):
    """Ping action returns pong with ISO timestamp."""
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "ping"}))
        resp = ws.receive_json()
        assert resp["type"] == "pong"
        assert "timestamp" in resp


def test_ws_malformed_json_handling(client: TestClient, test_data: dict):
    """Sending non-JSON string returns MALFORMED_JSON error without closing socket."""
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text("this is definitely not json")
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "MALFORMED_JSON"

        # Subsequent ping should still succeed
        ws.send_text(json.dumps({"action": "ping"}))
        pong = ws.receive_json()
        assert pong["type"] == "pong"


def test_ws_unknown_action(client: TestClient, test_data: dict):
    """Sending unsupported action returns UNKNOWN_ACTION error."""
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "unsupported_action_123"}))
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "UNKNOWN_ACTION"


def test_ws_missing_patient_id_in_subscribe(client: TestClient, test_data: dict):
    """Subscribe action without patient_id returns MISSING_PATIENT_ID error."""
    with client.websocket_connect(f"/ws?token={test_data['carol_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(json.dumps({"action": "subscribe"}))
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "MISSING_PATIENT_ID"


def test_ws_message_too_large(client: TestClient, test_data: dict):
    """Sending message exceeding 64 KB returns MESSAGE_TOO_LARGE error."""
    oversized = json.dumps({"action": "ping", "junk": "X" * 70000})
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        ws.receive_json()  # connection_established
        ws.send_text(oversized)
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "MESSAGE_TOO_LARGE"


# =============================================================================
# 4. Outbound Real-Time Event Dispatch & Isolation
# =============================================================================

def test_realtime_event_builders():
    """Verify event builders construct valid RealtimeEvent envelopes."""
    # 1. Reading created event
    ev = IngestionEvent(
        event_id="evt_test_001",
        patient_id="P101",
        source="wearable",
        is_simulated=True,
        measured_at=datetime(2026, 10, 13, 20, 0, 0, tzinfo=timezone.utc),
    )
    reading = VitalsReading(
        reading_id="r_01",
        event_id="evt_test_001",
        patient_id="P101",
        metric_code="heart_rate",
        value=85.0,
        unit="bpm",
        measured_at=ev.measured_at,
    )
    ev.readings = [reading]

    rt_reading = build_reading_created_event(ev)
    assert rt_reading.event_type == "reading.created"
    assert rt_reading.patient_id == "P101"
    assert rt_reading.resource_id == "evt_test_001"
    assert rt_reading.payload["metrics"] == ["heart_rate"]
    assert rt_reading.payload["is_simulated"] is True

    # 2. Alert created event
    alt = Alert(
        alert_id="alt_test_001",
        patient_id="P101",
        event_id="evt_test_001",
        rule_id="RULE_HR_HIGH",
        severity="HIGH",
        category="cardiac",
        reason="Heart rate high",
        status="NEW",
        created_at=datetime(2026, 10, 13, 20, 0, 0, tzinfo=timezone.utc),
    )
    rt_alert = build_alert_created_event(alt)
    assert rt_alert.event_type == "alert.created"
    assert rt_alert.payload["severity"] == "HIGH"
    assert rt_alert.payload["rule_id"] == "RULE_HR_HIGH"

    # 3. Alert acknowledged event
    alt.acknowledged_at = datetime(2026, 10, 13, 20, 5, 0, tzinfo=timezone.utc)
    rt_ack = build_alert_acknowledged_event(alt, actor_id="DOC_001", note="Patient checked")
    assert rt_ack.event_type == "alert.acknowledged"
    assert rt_ack.payload["status"] == "ACKNOWLEDGED"
    assert rt_ack.payload["acknowledged_by"] == "DOC_001"
    assert rt_ack.payload["note"] == "Patient checked"


@pytest.mark.anyio
async def test_connection_manager_broadcast_and_stats():
    """Verify ConnectionManager registry, broadcast routing, and stats."""
    manager = ConnectionManager()

    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()

    # User 1 is patient P101 (auto-subscribes)
    await manager.connect(mock_ws1, {"user_id": "usr_p101", "role": "patient", "patient_id": "P101"})

    # User 2 is clinician subscribing to P101
    await manager.connect(mock_ws2, {"user_id": "usr_doc1", "role": "doctor", "patient_id": None})
    await manager.subscribe(mock_ws2, "P101")

    stats = manager.get_stats()
    assert stats["active_connections"] == 2
    assert "P101" in stats["subscribed_patient_ids"]

    # Broadcast event to P101
    event_payload = {"event_type": "reading.created", "patient_id": "P101", "resource_id": "evt_1"}
    delivered = await manager.broadcast_to_patient("P101", event_payload)
    assert delivered == 2
    assert mock_ws1.send_text.await_count == 1
    assert mock_ws2.send_text.await_count == 1

    # Disconnect ws1
    await manager.disconnect(mock_ws1)
    stats_after = manager.get_stats()
    assert stats_after["active_connections"] == 1

    # Close all
    await manager.close_all()
    stats_closed = manager.get_stats()
    assert stats_closed["active_connections"] == 0


@pytest.mark.anyio
async def test_connection_manager_slow_client_isolation():
    """Slow or timed out client is isolated and disconnected without blocking others."""
    manager = ConnectionManager()

    mock_fast_ws = AsyncMock()

    # Create a hanging ws
    mock_slow_ws = AsyncMock()
    async def hang(*args, **kwargs):
        await asyncio.sleep(5.0)

    mock_slow_ws.send_text.side_effect = hang

    await manager.connect(mock_fast_ws, {"user_id": "usr_fast", "role": "patient", "patient_id": "P101"})
    await manager.connect(mock_slow_ws, {"user_id": "usr_slow", "role": "doctor", "patient_id": None})
    await manager.subscribe(mock_slow_ws, "P101")

    # Broadcast with short timeout (0.05s)
    delivered = await manager.broadcast_to_patient("P101", {"msg": "hello"}, send_timeout=0.05)
    assert delivered == 1
    assert mock_fast_ws.send_text.await_count == 1

    # Slow socket should have been disconnected
    stats = manager.get_stats()
    assert stats["active_connections"] == 1


def test_ws_live_event_delivery_over_client_connection(client: TestClient, test_data: dict):
    """Verify live event emitted via connection_manager reaches connected client."""
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws:
        init_resp = ws.receive_json()
        assert init_resp["type"] == "connection_established"

        # Dispatch reading.created event to Alice (P101)
        event = RealtimeEvent(
            event_type="reading.created",
            patient_id="P101",
            resource_id="evt_test_100",
            payload={"source": "wearable", "is_simulated": True, "metrics": ["heart_rate"]},
        )
        asyncio.run(connection_manager.broadcast_to_patient("P101", event.model_dump()))

        received = ws.receive_json()
        assert received["event_type"] == "reading.created"
        assert received["patient_id"] == "P101"
        assert received["resource_id"] == "evt_test_100"
        assert received["payload"]["metrics"] == ["heart_rate"]


def test_ws_live_alert_events_delivery_and_scoping(client: TestClient, test_data: dict):
    """
    Verify alert.created and alert.acknowledged events are delivered to authorized subscribers
    (patient and assigned clinician) while unassigned/other patients receive nothing.
    """
    # 1. Connect Alice (P101)
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws_alice:
        ws_alice.receive_json()  # connection_established

        # 2. Connect Bob (P102)
        with client.websocket_connect(f"/ws?token={test_data['bob_token']}") as ws_bob:
            ws_bob.receive_json()  # connection_established

            # 3. Connect Carol (Clinician assigned to P101) and subscribe to P101
            with client.websocket_connect(f"/ws?token={test_data['carol_token']}") as ws_carol:
                ws_carol.receive_json()  # connection_established
                ws_carol.send_text(json.dumps({"action": "subscribe", "patient_id": "P101"}))
                assert ws_carol.receive_json()["type"] == "subscription_success"

                # 4. Dispatch alert.created for P101
                alert_created = RealtimeEvent(
                    event_type="alert.created",
                    patient_id="P101",
                    resource_id="alt_p101_hr_critical",
                    payload={
                        "rule_id": "RULE_HR_CRITICAL_HIGH",
                        "severity": "CRITICAL",
                        "category": "cardiac",
                        "status": "NEW",
                        "reason": "Severe tachycardia detected",
                    },
                )
                asyncio.run(connection_manager.broadcast_to_patient("P101", alert_created.model_dump()))

                # Alice receives it
                msg_alice = ws_alice.receive_json()
                assert msg_alice["event_type"] == "alert.created"
                assert msg_alice["resource_id"] == "alt_p101_hr_critical"
                assert msg_alice["payload"]["severity"] == "CRITICAL"

                # Carol receives it
                msg_carol = ws_carol.receive_json()
                assert msg_carol["event_type"] == "alert.created"
                assert msg_carol["resource_id"] == "alt_p101_hr_critical"

                # Bob did NOT receive P101's alert. Sending ping from Bob yields immediate pong
                ws_bob.send_text(json.dumps({"action": "ping"}))
                msg_bob = ws_bob.receive_json()
                assert msg_bob["type"] == "pong"  # Not an alert.created event!

                # 5. Dispatch alert.acknowledged for P101
                alert_ack = RealtimeEvent(
                    event_type="alert.acknowledged",
                    patient_id="P101",
                    resource_id="alt_p101_hr_critical",
                    payload={
                        "status": "ACKNOWLEDGED",
                        "acknowledged_by": "DOC_001",
                        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
                        "note": "Attending patient in person",
                    },
                )
                asyncio.run(connection_manager.broadcast_to_patient("P101", alert_ack.model_dump()))

                # Alice and Carol receive acknowledgment
                ack_alice = ws_alice.receive_json()
                assert ack_alice["event_type"] == "alert.acknowledged"
                assert ack_alice["payload"]["acknowledged_by"] == "DOC_001"

                ack_carol = ws_carol.receive_json()
                assert ack_carol["event_type"] == "alert.acknowledged"
                assert ack_carol["payload"]["acknowledged_by"] == "DOC_001"


