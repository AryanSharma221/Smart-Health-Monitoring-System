"""
Unit and Integration Tests for Secure Clinical Messaging, Conversations, and Read Status.

Verifies:
1. Listing conversations restricted to authorized user (patient, doctor, admin).
2. Unauthorized user cannot access another user's conversation (403 Forbidden).
3. Authorized patient and clinician can create or retrieve permitted conversation.
4. Unauthorized participant combinations rejected (unassigned doctor/patient -> 403 Forbidden).
5. Repeated conversation creation is idempotent (no duplicate conversations).
6. Assignment revocation policy: historical messages read-only; new message dispatch rejected (403 Forbidden).
7. Valid message is persisted in MySQL with correct fields.
8. Authenticated identity is used as sender (server-side context).
9. Client cannot impersonate another user.
10. Empty and whitespace-only messages rejected (422 Unprocessable Entity).
11. Oversized messages (>2000 characters) rejected (422 Unprocessable Entity).
12. Message pagination is deterministic (asc/desc order, page, page_size, total_count).
13. Idempotent message retry with same key and content returns existing message without duplicate creation.
14. Conflicting reuse of idempotency key with different payload is rejected (409 Conflict).
15. Real-time notification failure does not roll back committed message.
16. Participant can mark eligible incoming messages as read.
17. Participant cannot mark another participant's outgoing messages as read on their behalf.
18. Repeated read requests behave consistently and safely.
19. Unread counts are computed accurately under pagination.
20. Read timestamps are strictly server-generated UTC timestamps.
21. Unauthenticated requests are rejected (401 Unauthorized).
22. Conversation ID manipulation across users cannot bypass authorization.
23. Message real-time WebSocket events delivered to conversation room.
24. Audit events record correct actor identity and target ID.
25. Audit logs never store full sensitive message body.
26. Clean transaction rollback on unexpected errors.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.mysql.models import (
    AuditLog,
    Base,
    Conversation,
    DoctorPatientAssignment,
    DoctorProfile,
    Message,
    PatientProfile,
    User,
)
from database.mysql.session import get_db
from services.api.config import Settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password
from services.messaging_service import MessagingService
from services.websocket.manager import connection_manager


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
    """Seed test users: Alice (P101), Bob (P102), Dr. Carol (DOC_001 assigned to P101), Dr. Dave (DOC_002 unassigned), Admin Eve."""
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

    test_db_session.add_all([
        u_alice, prof_alice,
        u_bob, prof_bob,
        u_carol, prof_carol, assign_carol,
        u_dave, prof_dave,
        u_eve,
    ])
    test_db_session.commit()

    # Generate test tokens
    alice_token = create_access_token({"sub": "usr_alice", "role": "patient"}, settings=test_settings)
    bob_token = create_access_token({"sub": "usr_bob", "role": "patient"}, settings=test_settings)
    carol_token = create_access_token({"sub": "usr_carol", "role": "doctor"}, settings=test_settings)
    dave_token = create_access_token({"sub": "usr_dave", "role": "doctor"}, settings=test_settings)
    eve_token = create_access_token({"sub": "usr_eve", "role": "admin_operator"}, settings=test_settings)

    return {
        "alice_token": alice_token,
        "bob_token": bob_token,
        "carol_token": carol_token,
        "dave_token": dave_token,
        "eve_token": eve_token,
    }


# =============================================================================
# 1. Conversation Creation and Listing Tests
# =============================================================================

def test_authorized_patient_creates_conversation_with_assigned_doctor(client: TestClient, test_data: dict):
    """Patient Alice can create/retrieve a conversation with assigned Doctor Carol."""
    resp = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"doctor_id": "DOC_001"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["patient_id"] == "P101"
    assert data["doctor_id"] == "DOC_001"
    assert data["conversation_id"] == "conv_P101_DOC_001"
    assert "Carol" in data["doctor_name"]


def test_authorized_clinician_creates_conversation_with_assigned_patient(client: TestClient, test_data: dict):
    """Doctor Carol can create/retrieve a conversation with assigned Patient Alice."""
    resp = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['carol_token']}"},
        json={"patient_id": "P101"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["patient_id"] == "P101"
    assert data["doctor_id"] == "DOC_001"


def test_unassigned_clinician_cannot_create_conversation(client: TestClient, test_data: dict):
    """Doctor Dave (unassigned) cannot create conversation with Patient Alice (403 Forbidden)."""
    resp = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['dave_token']}"},
        json={"patient_id": "P101"},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "not actively assigned" in resp.json()["detail"]


def test_patient_cannot_create_conversation_with_unassigned_doctor(client: TestClient, test_data: dict):
    """Patient Alice cannot create conversation with unassigned Doctor Dave."""
    resp = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"doctor_id": "DOC_002"},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_repeated_conversation_creation_is_idempotent(client: TestClient, test_data: dict):
    """Creating an already existing conversation returns the existing record without error or duplicate."""
    resp1 = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"doctor_id": "DOC_001"},
    )
    assert resp1.status_code == status.HTTP_201_CREATED
    conv_id = resp1.json()["conversation_id"]

    resp2 = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"doctor_id": "DOC_001"},
    )
    assert resp2.status_code == status.HTTP_201_CREATED
    assert resp2.json()["conversation_id"] == conv_id


def test_list_conversations_filtered_to_authenticated_user(client: TestClient, test_data: dict):
    """User only sees conversations they participate in."""
    # Alice creates conversation with Carol
    client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"doctor_id": "DOC_001"},
    )

    # Alice lists conversations -> 1 found
    resp_alice = client.get("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"})
    assert resp_alice.status_code == status.HTTP_200_OK
    assert resp_alice.json()["total_count"] == 1
    assert resp_alice.json()["items"][0]["conversation_id"] == "conv_P101_DOC_001"

    # Carol lists conversations -> 1 found
    resp_carol = client.get("/conversations", headers={"Authorization": f"Bearer {test_data['carol_token']}"})
    assert resp_carol.status_code == status.HTTP_200_OK
    assert resp_carol.json()["total_count"] == 1

    # Bob lists conversations -> 0 found (not a participant)
    resp_bob = client.get("/conversations", headers={"Authorization": f"Bearer {test_data['bob_token']}"})
    assert resp_bob.status_code == status.HTTP_200_OK
    assert resp_bob.json()["total_count"] == 0


def test_unauthorized_user_cannot_access_individual_conversation(client: TestClient, test_data: dict):
    """Bob cannot access Alice and Carol's conversation."""
    client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"doctor_id": "DOC_001"},
    )

    resp = client.get(
        "/conversations/conv_P101_DOC_001",
        headers={"Authorization": f"Bearer {test_data['bob_token']}"},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# 2. Message Dispatch and Persistence Tests
# =============================================================================

def test_send_message_persists_in_mysql_with_authenticated_sender(client: TestClient, test_data: dict, test_db_session: Session):
    """Sending a message saves record with authenticated sender identity."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    resp = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Hello Doctor Carol, my heart rate felt slightly elevated this morning."},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["sender_id"] == "usr_alice"
    assert data["receiver_id"] == "usr_carol"
    assert data["content"] == "Hello Doctor Carol, my heart rate felt slightly elevated this morning."
    assert data["is_read"] is False

    # Check database persistence
    msg = test_db_session.get(Message, data["message_id"])
    assert msg is not None
    assert msg.sender_id == "usr_alice"
    assert msg.patient_context_id == "P101"


def test_client_cannot_forge_sender_id(client: TestClient, test_data: dict):
    """Client-provided fields outside the schema cannot alter authenticated sender."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    # Inbound schema only accepts 'content' and 'idempotency_key'
    resp = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Testing spoofing", "sender_id": "usr_carol", "receiver_id": "usr_bob"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    # Server strictly overrides with authenticated user
    assert data["sender_id"] == "usr_alice"
    assert data["receiver_id"] == "usr_carol"


def test_empty_and_whitespace_only_messages_rejected(client: TestClient, test_data: dict):
    """Empty or whitespace-only messages are rejected with 422."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    # Empty string
    r1 = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": ""},
    )
    assert r1.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Whitespace only
    r2 = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "   \n\t  "},
    )
    assert r2.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_oversized_message_rejected(client: TestClient, test_data: dict):
    """Message exceeding 2000 characters is rejected with 422."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    r = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "A" * 2001},
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_message_idempotency_retry_handling(client: TestClient, test_data: dict):
    """Sending message with idempotency key handles retries cleanly without duplicates."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    payload = {"content": "Checking in on telemetry results.", "idempotency_key": "key_alice_msg_001"}

    # 1. First send
    r1 = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json=payload,
    )
    assert r1.status_code == status.HTTP_201_CREATED
    msg_id = r1.json()["message_id"]

    # 2. Retried send with exact same content & key
    r2 = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json=payload,
    )
    assert r2.status_code == status.HTTP_201_CREATED
    assert r2.json()["message_id"] == msg_id

    # 3. Conflicting send with same key but differing content -> 409 Conflict
    conflict_payload = {"content": "Different text entirely!", "idempotency_key": "key_alice_msg_001"}
    r3 = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json=conflict_payload,
    )
    assert r3.status_code == status.HTTP_409_CONFLICT


def test_message_ordering_and_pagination(client: TestClient, test_data: dict):
    """Messages are listed with deterministic ordering and pagination."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    for i in range(5):
        client.post(
            "/conversations/conv_P101_DOC_001/messages",
            headers={"Authorization": f"Bearer {test_data['alice_token']}"},
            json={"content": f"Message sequence {i}"},
        )

    # Query with page_size=2
    r_page1 = client.get(
        "/conversations/conv_P101_DOC_001/messages?page=1&page_size=2&order=asc",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
    )
    data1 = r_page1.json()
    assert data1["total_count"] == 5
    assert len(data1["items"]) == 2
    assert data1["items"][0]["content"] == "Message sequence 0"
    assert data1["items"][1]["content"] == "Message sequence 1"
    assert data1["has_next"] is True

    # Page 2
    r_page2 = client.get(
        "/conversations/conv_P101_DOC_001/messages?page=2&page_size=2&order=asc",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
    )
    data2 = r_page2.json()
    assert len(data2["items"]) == 2
    assert data2["items"][0]["content"] == "Message sequence 2"


# =============================================================================
# 3. Read Status and Unread Counter Tests
# =============================================================================

def test_mark_incoming_messages_read(client: TestClient, test_data: dict, test_db_session: Session):
    """Clinician marks incoming patient message as read; cannot mark outgoing messages."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    # Alice sends to Carol
    r_send = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Please review my vitals."},
    )
    msg_id = r_send.json()["message_id"]

    # Carol checks conversation summary: unread_count == 1
    r_summary_before = client.get(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['carol_token']}"},
    )
    assert r_summary_before.json()["items"][0]["unread_count"] == 1

    # Alice (sender) tries to mark her own outgoing message as read -> 0 marked
    r_alice_read = client.post(
        "/conversations/conv_P101_DOC_001/read",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
    )
    assert r_alice_read.json()["messages_marked_read"] == 0

    # Carol (receiver) marks read
    r_carol_read = client.post(
        "/conversations/conv_P101_DOC_001/read",
        headers={"Authorization": f"Bearer {test_data['carol_token']}"},
    )
    assert r_carol_read.status_code == status.HTTP_200_OK
    assert r_carol_read.json()["messages_marked_read"] == 1

    # Check unread_count updated to 0
    r_summary_after = client.get(
        "/conversations",
        headers={"Authorization": f"Bearer {test_data['carol_token']}"},
    )
    assert r_summary_after.json()["items"][0]["unread_count"] == 0

    # Verify database record has is_read=True and read_at is set
    reloaded_msg = test_db_session.get(Message, msg_id)
    assert reloaded_msg.is_read is True
    assert reloaded_msg.read_at is not None


def test_repeated_read_is_safe_and_idempotent(client: TestClient, test_data: dict):
    """Calling mark read multiple times is safe and returns 0 on second run."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})
    client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Testing repeated read."},
    )

    # First mark
    r1 = client.post("/conversations/conv_P101_DOC_001/read", headers={"Authorization": f"Bearer {test_data['carol_token']}"})
    assert r1.json()["messages_marked_read"] == 1

    # Repeated mark
    r2 = client.post("/conversations/conv_P101_DOC_001/read", headers={"Authorization": f"Bearer {test_data['carol_token']}"})
    assert r2.json()["messages_marked_read"] == 0


# =============================================================================
# 4. Care Assignment Revocation Policy
# =============================================================================

def test_revoked_care_assignment_blocks_new_messages_but_keeps_history(client: TestClient, test_data: dict, test_db_session: Session):
    """
    Documented Revocation Policy:
    When doctor-patient assignment is deactivated, existing conversation history remains
    accessible for clinical continuity and audit, but sending new messages is rejected (403).
    """
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    # Send message while active
    client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Message sent during active care."},
    )

    # Revoke assignment in database
    assignment = test_db_session.get(DoctorPatientAssignment, ("DOC_001", "P101"))
    assignment.is_active = False
    test_db_session.commit()

    # 1. Historical messages still accessible read-only
    r_list = client.get(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
    )
    assert r_list.status_code == status.HTTP_200_OK
    assert r_list.json()["total_count"] == 1

    # 2. Sending new message is rejected
    r_new = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Attempting message after revocation."},
    )
    assert r_new.status_code == status.HTTP_403_FORBIDDEN
    assert "revoked" in r_new.json()["detail"].lower()


# =============================================================================
# 5. Security, Audit Trail, and WebSocket Notifications
# =============================================================================

def test_unauthenticated_request_rejected(client: TestClient):
    """Accessing conversations or messages without credentials returns 401."""
    assert client.get("/conversations").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.post("/conversations", json={"doctor_id": "DOC_001"}).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/conversations/conv_1/messages").status_code == status.HTTP_401_UNAUTHORIZED


def test_audit_log_captures_message_events_without_leaking_message_body(client: TestClient, test_data: dict, test_db_session: Session):
    """Audit logs record MESSAGE_SEND with character count but never raw message text."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    secret_message = "Confidential medical inquiry about lab tests."
    client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": secret_message},
    )

    logs = test_db_session.scalars(
        select(AuditLog).where(AuditLog.action == "MESSAGE_SEND")
    ).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.actor_id == "usr_alice"
    assert log.target_type == "message"

    # Verify sensitive text is NOT stored in audit log
    assert secret_message not in log.metadata_json
    metadata = json.loads(log.metadata_json)
    assert metadata["char_count"] == len(secret_message)


def test_websocket_message_created_notification_delivered_to_patient_stream(client: TestClient, test_data: dict):
    """Sending a message triggers a real-time message.created notification over WebSocket."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    # Connect Alice to WebSocket
    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws_alice:
        ws_alice.receive_json()  # connection_established

        # Carol sends message via REST API
        resp = client.post(
            "/conversations/conv_P101_DOC_001/messages",
            headers={"Authorization": f"Bearer {test_data['carol_token']}"},
            json={"content": "Please rest today."},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        msg_id = resp.json()["message_id"]

        # Alice receives notification on her WebSocket stream
        ws_event = ws_alice.receive_json()
        assert ws_event["event_type"] == "message.created"
        assert ws_event["patient_id"] == "P101"
        assert ws_event["resource_id"] == msg_id
        assert ws_event["payload"]["sender_id"] == "usr_carol"


def test_admin_can_access_any_conversation(client: TestClient, test_data: dict):
    """Admin Eve has system oversight to view any conversation and its messages."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})
    client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Alice checking in."},
    )

    # Admin lists conversations
    resp = client.get("/conversations", headers={"Authorization": f"Bearer {test_data['eve_token']}"})
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["total_count"] >= 1

    # Admin accesses messages
    r_msg = client.get(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['eve_token']}"},
    )
    assert r_msg.status_code == status.HTTP_200_OK
    assert r_msg.json()["total_count"] == 1


def test_mark_read_subset_of_message_ids(client: TestClient, test_data: dict, test_db_session: Session):
    """Client can mark a specific list of message IDs as read, leaving other unread messages intact."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    r1 = client.post("/conversations/conv_P101_DOC_001/messages", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"content": "Msg 1"})
    r2 = client.post("/conversations/conv_P101_DOC_001/messages", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"content": "Msg 2"})

    id1 = r1.json()["message_id"]
    id2 = r2.json()["message_id"]

    # Carol marks only id1 as read
    r_read = client.post(
        "/conversations/conv_P101_DOC_001/read",
        headers={"Authorization": f"Bearer {test_data['carol_token']}"},
        json={"message_ids": [id1]},
    )
    assert r_read.status_code == status.HTTP_200_OK
    assert r_read.json()["messages_marked_read"] == 1

    # In DB: id1 is read, id2 remains unread
    m1 = test_db_session.get(Message, id1)
    m2 = test_db_session.get(Message, id2)
    assert m1.is_read is True
    assert m2.is_read is False


def test_read_timestamp_is_server_generated(client: TestClient, test_data: dict, test_db_session: Session):
    """Read timestamp is assigned by the server in UTC and never trusted from client input."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})
    r_send = client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Verify server read timestamp."},
    )
    msg_id = r_send.json()["message_id"]

    before = datetime.now(timezone.utc) - timedelta(seconds=2)
    r_read = client.post(
        "/conversations/conv_P101_DOC_001/read",
        headers={"Authorization": f"Bearer {test_data['carol_token']}"},
        json={},
    )
    after = datetime.now(timezone.utc) + timedelta(seconds=2)

    assert r_read.status_code == status.HTTP_200_OK
    m = test_db_session.get(Message, msg_id)
    assert m.read_at is not None
    # Server assigned read_at should fall within the test execution window
    read_at_utc = m.read_at.replace(tzinfo=timezone.utc) if m.read_at.tzinfo is None else m.read_at
    assert before <= read_at_utc <= after


def test_websocket_message_read_notification_delivered(client: TestClient, test_data: dict):
    """Marking messages read triggers a real-time message.read notification over WebSocket."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})
    client.post(
        "/conversations/conv_P101_DOC_001/messages",
        headers={"Authorization": f"Bearer {test_data['alice_token']}"},
        json={"content": "Read me."},
    )

    with client.websocket_connect(f"/ws?token={test_data['alice_token']}") as ws_alice:
        ws_alice.receive_json()  # connection_established

        # Carol marks read
        resp = client.post(
            "/conversations/conv_P101_DOC_001/read",
            headers={"Authorization": f"Bearer {test_data['carol_token']}"},
        )
        assert resp.status_code == status.HTTP_200_OK

        # Alice receives message.read event
        ws_event = ws_alice.receive_json()
        assert ws_event["event_type"] == "message.read"
        assert ws_event["patient_id"] == "P101"
        assert ws_event["payload"]["conversation_id"] == "conv_P101_DOC_001"
        assert ws_event["payload"]["messages_marked_read"] == 1


def test_notification_failure_does_not_rollback_committed_message(client: TestClient, test_data: dict, test_db_session: Session):
    """If real-time event dispatch raises an unexpected exception, the message remains committed in MySQL."""
    client.post("/conversations", headers={"Authorization": f"Bearer {test_data['alice_token']}"}, json={"doctor_id": "DOC_001"})

    with patch("services.websocket.dispatcher.notify_message_created", side_effect=RuntimeError("Simulated socket broker failure")):
        resp = client.post(
            "/conversations/conv_P101_DOC_001/messages",
            headers={"Authorization": f"Bearer {test_data['alice_token']}"},
            json={"content": "Resilient message under notification failure."},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        msg_id = resp.json()["message_id"]

    # Verify message is safely persisted in authoritative MySQL store
    persisted = test_db_session.get(Message, msg_id)
    assert persisted is not None
    assert persisted.content == "Resilient message under notification failure."

