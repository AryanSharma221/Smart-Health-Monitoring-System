"""
Comprehensive Security Regression Test Suite.

Verifies end-to-end security invariants across all layers of the Smart Health Monitoring System:
1. Unauthenticated request rejection across all protected endpoints (HTTP 401).
2. Credential validation: expired, tampered, malformed, and inactive tokens (HTTP 401).
3. Cross-patient isolation: multi-tenant boundary between Patient A and Patient B (HTTP 403).
4. Clinician care assignment boundaries: assigned vs unassigned doctors (HTTP 200 vs HTTP 403).
5. Privileged clinical alert lifecycle: patient forbidden, assigned doctor and admin permitted.
6. Care participant messaging isolation: eavesdropping and injection denied (HTTP 403).
7. Error response sanitization: suppression of stack traces, password hashes, and raw SQL.
8. WebSocket authentication and granular subscription boundary enforcement.
9. Read-only route idempotency: zero mutation side-effects on GET requests.
10. Strict Read-Only MongoDB Atlas double verification: write operations trigger MongoWriteViolationError.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.mongodb.read_only_guard import MongoWriteViolationError, StrictReadOnlyMongoDatabase
from database.mysql.models import Alert, User, VitalsReading
from services.api.config import Settings
from services.websocket.auth import (
    authenticate_websocket_token,
    check_subscription_permission,
)


# =============================================================================
# 1. Unauthenticated Access Rejections (HTTP 401)
# =============================================================================

@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/patients/P101/readings"),
        ("GET", "/api/v1/patients/P101/readings/latest"),
        ("GET", "/api/v1/alerts"),
        ("GET", "/api/v1/patients/P101/alerts"),
        ("GET", "/api/v1/alerts/ALT_P101_001"),
        ("POST", "/api/v1/alerts/ALT_P101_001/acknowledge"),
        ("POST", "/api/v1/alerts/ALT_P101_001/resolve"),
        ("GET", "/api/v1/conversations"),
        ("POST", "/api/v1/conversations"),
        ("GET", "/api/v1/conversations/CONV_ALICE_P101/messages"),
        ("POST", "/api/v1/conversations/CONV_ALICE_P101/messages"),
        ("POST", "/api/v1/conversations/CONV_ALICE_P101/read"),
        ("POST", "/api/v1/ws-ticket"),
    ],
)
def test_unauthenticated_requests_return_401(api_client: TestClient, method: str, path: str):
    """Verify that every protected operational endpoint strictly rejects unauthenticated access."""
    if method == "GET":
        response = api_client.get(path)
    else:
        response = api_client.post(path, json={})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED, (
        f"Protected endpoint {method} {path} returned {response.status_code}; expected 401 Unauthorized."
    )
    data = response.json()
    assert "detail" in data, f"Error response on {path} must contain standard 'detail' field."


# =============================================================================
# 2. Credential Validation & Token Rejections (HTTP 401)
# =============================================================================

@pytest.mark.parametrize(
    "persona_key,expected_detail_substring",
    [
        ("expired_token", "expired"),
        ("tampered_token", "Could not validate"),
        ("inactive_user_token", "inactive"),
    ],
)
def test_invalid_tokens_rejected_with_401(
    api_client: TestClient,
    security_personas: Dict[str, Any],
    persona_key: str,
    expected_detail_substring: str,
):
    """Verify that expired, tampered, and inactive-account tokens return 401 Unauthorized."""
    token = security_personas[persona_key]
    headers = {"Authorization": f"Bearer {token}"}
    response = api_client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert expected_detail_substring.lower() in response.json()["detail"].lower()


def test_malformed_token_header_rejected_with_401(api_client: TestClient):
    """Verify malformed headers, empty tokens, and non-bearer schemes are rejected with 401."""
    # Malformed token string
    resp1 = api_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.valid.jwt"})
    assert resp1.status_code == status.HTTP_401_UNAUTHORIZED

    # Non-Bearer scheme
    resp2 = api_client.get("/api/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED

    # Empty token string
    resp3 = api_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer "})
    assert resp3.status_code == status.HTTP_401_UNAUTHORIZED


# =============================================================================
# 3. Cross-Patient Isolation / Multi-Tenant Boundary (HTTP 403)
# =============================================================================

def test_patient_cross_tenant_isolation(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify that Patient B is strictly forbidden from accessing Patient A (P101) data."""
    token_b = security_personas["patient_b_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Patient B attempts to read Patient A's vitals timeseries
    resp_readings = api_client.get("/api/v1/patients/P101/readings", headers=headers_b)
    assert resp_readings.status_code == status.HTTP_403_FORBIDDEN

    # 2. Patient B attempts to read Patient A's latest vitals
    resp_latest = api_client.get("/api/v1/patients/P101/readings/latest", headers=headers_b)
    assert resp_latest.status_code == status.HTTP_403_FORBIDDEN

    # 3. Patient B attempts to query Patient A's alerts
    resp_alerts = api_client.get("/api/v1/patients/P101/alerts", headers=headers_b)
    assert resp_alerts.status_code == status.HTTP_403_FORBIDDEN

    # 4. Patient B attempts to view Patient A's specific alert
    resp_alert_detail = api_client.get("/api/v1/alerts/ALT_P101_001", headers=headers_b)
    assert resp_alert_detail.status_code == status.HTTP_403_FORBIDDEN

    # 5. Patient B attempts to acknowledge Patient A's alert
    resp_ack = api_client.post(
        "/api/v1/alerts/ALT_P101_001/acknowledge",
        json={"note": "Malicious acknowledgement attempt"},
        headers=headers_b,
    )
    assert resp_ack.status_code == status.HTTP_403_FORBIDDEN

    # 6. Patient B attempts to filter /alerts by Patient A's ID
    resp_filtered = api_client.get("/api/v1/alerts?patient_id=P101", headers=headers_b)
    assert resp_filtered.status_code == status.HTTP_403_FORBIDDEN


def test_patient_self_access_permitted(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify Patient A can legitimately view their own vitals and alerts."""
    token_a = security_personas["patient_a_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Own vitals readings
    resp_readings = api_client.get("/api/v1/patients/P101/readings", headers=headers_a)
    assert resp_readings.status_code == status.HTTP_200_OK

    # Own latest readings
    resp_latest = api_client.get("/api/v1/patients/P101/readings/latest", headers=headers_a)
    assert resp_latest.status_code == status.HTTP_200_OK

    # Own alerts
    resp_alerts = api_client.get("/api/v1/patients/P101/alerts", headers=headers_a)
    assert resp_alerts.status_code == status.HTTP_200_OK

    # Own alert detail
    resp_detail = api_client.get("/api/v1/alerts/ALT_P101_001", headers=headers_a)
    assert resp_detail.status_code == status.HTTP_200_OK
    assert resp_detail.json()["alert_id"] == "ALT_P101_001"


# =============================================================================
# 4. Clinician Care Assignment Boundaries (HTTP 200 vs HTTP 403)
# =============================================================================

def test_assigned_clinician_access_permitted(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify Doctor Alice (assigned to P101) can access Patient A's clinical records."""
    token_alice = security_personas["assigned_clinician_token"]
    headers_alice = {"Authorization": f"Bearer {token_alice}"}

    # Readings
    resp_readings = api_client.get("/api/v1/patients/P101/readings", headers=headers_alice)
    assert resp_readings.status_code == status.HTTP_200_OK

    # Alerts
    resp_alerts = api_client.get("/api/v1/patients/P101/alerts", headers=headers_alice)
    assert resp_alerts.status_code == status.HTTP_200_OK

    # Alert detail
    resp_alert = api_client.get("/api/v1/alerts/ALT_P101_001", headers=headers_alice)
    assert resp_alert.status_code == status.HTTP_200_OK


def test_unassigned_clinician_access_denied(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify Doctor Bob (unassigned to P101) is strictly denied from Patient A's clinical records."""
    token_bob = security_personas["unassigned_clinician_token"]
    headers_bob = {"Authorization": f"Bearer {token_bob}"}

    # Readings
    resp_readings = api_client.get("/api/v1/patients/P101/readings", headers=headers_bob)
    assert resp_readings.status_code == status.HTTP_403_FORBIDDEN

    # Alerts
    resp_alerts = api_client.get("/api/v1/patients/P101/alerts", headers=headers_bob)
    assert resp_alerts.status_code == status.HTTP_403_FORBIDDEN

    # Alert detail
    resp_alert = api_client.get("/api/v1/alerts/ALT_P101_001", headers=headers_bob)
    assert resp_alert.status_code == status.HTTP_403_FORBIDDEN

    # Alert acknowledge
    resp_ack = api_client.post(
        "/api/v1/alerts/ALT_P101_001/acknowledge",
        json={"note": "Unassigned clinician attempting action"},
        headers=headers_bob,
    )
    assert resp_ack.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# 5. Privileged Alert Lifecycle (Role & Ownership Enforcement)
# =============================================================================

def test_patient_forbidden_from_modifying_alerts(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify patients cannot acknowledge or resolve alerts even if the alert is their own."""
    token_a = security_personas["patient_a_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Attempt acknowledge
    resp_ack = api_client.post(
        "/api/v1/alerts/ALT_P101_001/acknowledge",
        json={"note": "Patient attempting to acknowledge"},
        headers=headers_a,
    )
    assert resp_ack.status_code == status.HTTP_403_FORBIDDEN
    assert "clinicians and administrative operators" in resp_ack.json()["detail"].lower()

    # Attempt resolve
    resp_res = api_client.post(
        "/api/v1/alerts/ALT_P101_001/resolve",
        json={"note": "Patient attempting to resolve"},
        headers=headers_a,
    )
    assert resp_res.status_code == status.HTTP_403_FORBIDDEN


def test_assigned_clinician_and_admin_alert_lifecycle(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify assigned clinician can acknowledge, and admin can resolve the alert."""
    token_alice = security_personas["assigned_clinician_token"]
    headers_alice = {"Authorization": f"Bearer {token_alice}"}

    # 1. Assigned Doctor Acknowledges Alert
    resp_ack = api_client.post(
        "/api/v1/alerts/ALT_P101_001/acknowledge",
        json={"note": "Clinician Dr. Alice acknowledged critical alert"},
        headers=headers_alice,
    )
    assert resp_ack.status_code == status.HTTP_200_OK
    assert resp_ack.json()["status"] == "ACKNOWLEDGED"

    # 2. Administrator Resolves Alert
    token_admin = security_personas["admin_token"]
    headers_admin = {"Authorization": f"Bearer {token_admin}"}

    resp_res = api_client.post(
        "/api/v1/alerts/ALT_P101_001/resolve",
        json={"note": "Admin resolved alert following clinical stabilization"},
        headers=headers_admin,
    )
    assert resp_res.status_code == status.HTTP_200_OK
    assert resp_res.json()["status"] == "RESOLVED"


# =============================================================================
# 6. Care Participant Messaging Isolation (HTTP 403)
# =============================================================================

def test_conversation_participant_isolation(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify non-participants cannot read, post messages to, or mark conversations as read."""
    # CONV_ALICE_P101 is between Alice and Patient A (P101).
    token_pat_b = security_personas["patient_b_token"]
    headers_b = {"Authorization": f"Bearer {token_pat_b}"}

    # Patient B attempts to read conversation messages
    resp_get = api_client.get("/api/v1/conversations/CONV_ALICE_P101/messages", headers=headers_b)
    assert resp_get.status_code == status.HTTP_403_FORBIDDEN

    # Patient B attempts to send message
    resp_post = api_client.post(
        "/api/v1/conversations/CONV_ALICE_P101/messages",
        json={"content": "Malicious injected message"},
        headers=headers_b,
    )
    assert resp_post.status_code == status.HTTP_403_FORBIDDEN

    # Patient B attempts to mark as read
    resp_read = api_client.post("/api/v1/conversations/CONV_ALICE_P101/read", headers=headers_b)
    assert resp_read.status_code == status.HTTP_403_FORBIDDEN

    # Doctor Bob (unassigned doctor) attempts to post to Alice's conversation
    token_bob = security_personas["unassigned_clinician_token"]
    headers_bob = {"Authorization": f"Bearer {token_bob}"}

    resp_bob_post = api_client.post(
        "/api/v1/conversations/CONV_ALICE_P101/messages",
        json={"content": "Dr. Bob unauthorized message"},
        headers=headers_bob,
    )
    assert resp_bob_post.status_code == status.HTTP_403_FORBIDDEN


def test_conversation_participants_can_exchange_messages(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify Doctor Alice and Patient A can successfully read and send messages."""
    token_alice = security_personas["assigned_clinician_token"]
    headers_alice = {"Authorization": f"Bearer {token_alice}"}

    # Alice views messages
    resp_alice_get = api_client.get("/api/v1/conversations/CONV_ALICE_P101/messages", headers=headers_alice)
    assert resp_alice_get.status_code == status.HTTP_200_OK

    # Patient A sends response
    token_a = security_personas["patient_a_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    resp_send = api_client.post(
        "/api/v1/conversations/CONV_ALICE_P101/messages",
        json={"content": "Thank you Dr. Alice, my symptoms are improving."},
        headers=headers_a,
    )
    assert resp_send.status_code == status.HTTP_201_CREATED
    assert resp_send.json()["content"] == "Thank you Dr. Alice, my symptoms are improving."


# =============================================================================
# 7. Error Response Sanitization & Credential Suppression
# =============================================================================

def test_error_responses_sanitized_and_uninformative_to_attackers(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify error responses do not leak stack traces, SQL syntax, or internal file paths."""
    token_admin = security_personas["admin_token"]
    headers = {"Authorization": f"Bearer {token_admin}"}

    probes = [
        ("GET", "/api/v1/patients/P101'--/readings"),
        ("GET", "/api/v1/alerts/NONEXISTENT_ALERT_999999"),
        ("POST", "/api/v1/alerts/ALT_P101_001/acknowledge"),  # Missing required JSON body
        ("GET", "/api/v1/patients/P101/readings?page=invalid"),
    ]

    for method, path in probes:
        if method == "GET":
            resp = api_client.get(path, headers=headers)
        else:
            resp = api_client.post(path, content="invalid_json_string{", headers={**headers, "Content-Type": "application/json"})

        raw_body = resp.text
        # Assertions for security information suppression
        assert "Traceback (most recent call last)" not in raw_body, f"Leakage detected on {path}: Python traceback"
        assert "password_hash" not in raw_body, f"Leakage detected on {path}: password_hash field"
        assert "sqlite3.OperationalError" not in raw_body, f"Leakage detected on {path}: raw SQLite driver error"
        assert "SELECT " not in raw_body or "SELECT *" not in raw_body, f"Leakage detected on {path}: raw SQL query"


def test_auth_me_suppresses_credentials(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify /auth/me payload never includes password hash or salt."""
    for token_key in ["patient_a_token", "assigned_clinician_token", "admin_token"]:
        token = security_personas[token_key]
        resp = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "password_hash" not in data
        assert "password" not in data
        assert "salt" not in data


# =============================================================================
# 8. WebSocket Authentication & Subscription Boundary Enforcement
# =============================================================================

def test_websocket_token_authentication(
    isolated_db: Session,
    security_test_settings: Settings,
    security_personas: Dict[str, Any],
):
    """Verify authenticate_websocket_token accepts valid tokens and rejects invalid/expired ones."""
    # 1. Valid Token -> Returns active User
    user = authenticate_websocket_token(
        security_personas["patient_a_token"],
        db=isolated_db,
        settings=security_test_settings,
    )
    assert user is not None
    assert user.user_id == "U_PAT_101"

    # 2. Expired Token -> Returns None
    expired_user = authenticate_websocket_token(
        security_personas["expired_token"],
        db=isolated_db,
        settings=security_test_settings,
    )
    assert expired_user is None

    # 3. Tampered Token -> Returns None
    tampered_user = authenticate_websocket_token(
        security_personas["tampered_token"],
        db=isolated_db,
        settings=security_test_settings,
    )
    assert tampered_user is None

    # 4. Inactive User Token -> Returns None
    inactive_user = authenticate_websocket_token(
        security_personas["inactive_user_token"],
        db=isolated_db,
        settings=security_test_settings,
    )
    assert inactive_user is None


def test_websocket_subscription_boundaries(
    isolated_db: Session,
    security_personas: Dict[str, Any],
):
    """Verify check_subscription_permission enforces patient and clinician assignment boundaries."""
    user_pat_a = isolated_db.query(User).filter(User.user_id == "U_PAT_101").first()
    user_doc_alice = isolated_db.query(User).filter(User.user_id == "U_DOC_ALICE").first()
    user_doc_bob = isolated_db.query(User).filter(User.user_id == "U_DOC_BOB").first()
    user_admin = isolated_db.query(User).filter(User.user_id == "U_ADMIN").first()

    # Patient A subscribing to own records (P101) -> True
    ok, _ = check_subscription_permission(user_pat_a, "P101", isolated_db)
    assert ok is True

    # Patient A subscribing to Patient B records (P102) -> False
    ok, _ = check_subscription_permission(user_pat_a, "P102", isolated_db)
    assert ok is False

    # Doctor Alice (assigned to P101) subscribing to P101 -> True
    ok, _ = check_subscription_permission(user_doc_alice, "P101", isolated_db)
    assert ok is True

    # Doctor Alice (not assigned to P102) subscribing to P102 -> False
    ok, _ = check_subscription_permission(user_doc_alice, "P102", isolated_db)
    assert ok is False

    # Doctor Bob (assigned to P102) subscribing to P102 -> True
    ok, _ = check_subscription_permission(user_doc_bob, "P102", isolated_db)
    assert ok is True

    # Doctor Bob (not assigned to P101) subscribing to P101 -> False
    ok, _ = check_subscription_permission(user_doc_bob, "P101", isolated_db)
    assert ok is False

    # Admin subscribing to any patient -> True
    ok, _ = check_subscription_permission(user_admin, "P101", isolated_db)
    assert ok is True
    ok, _ = check_subscription_permission(user_admin, "P102", isolated_db)
    assert ok is True


def test_websocket_ticket_endpoint_protection(
    api_client: TestClient,
    security_personas: Dict[str, Any],
):
    """Verify /ws-ticket issues short-lived single-use ticket for authenticated actors."""
    # Unauthenticated -> 401
    resp_unauth = api_client.post("/api/v1/ws-ticket")
    assert resp_unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # Authenticated Patient A -> 200 with ticket
    token_a = security_personas["patient_a_token"]
    resp_auth = api_client.post("/api/v1/ws-ticket", headers={"Authorization": f"Bearer {token_a}"})
    assert resp_auth.status_code == status.HTTP_200_OK
    assert "ticket" in resp_auth.json()


# =============================================================================
# 9. Read-Only Route Idempotency Verification
# =============================================================================

def test_readonly_endpoints_have_no_mutation_side_effects(
    api_client: TestClient,
    isolated_db: Session,
    security_personas: Dict[str, Any],
):
    """Verify that calling GET endpoints repeatedly causes zero row mutations or deletions."""
    token_alice = security_personas["assigned_clinician_token"]
    headers = {"Authorization": f"Bearer {token_alice}"}

    # Count initial rows
    initial_readings = isolated_db.query(func.count(VitalsReading.reading_id)).scalar()
    initial_alerts = isolated_db.query(func.count(Alert.alert_id)).scalar()

    # Issue multiple read operations
    for _ in range(5):
        resp1 = api_client.get("/api/v1/patients/P101/readings", headers=headers)
        assert resp1.status_code == status.HTTP_200_OK

        resp2 = api_client.get("/api/v1/patients/P101/readings/latest", headers=headers)
        assert resp2.status_code == status.HTTP_200_OK

        resp3 = api_client.get("/api/v1/patients/P101/alerts", headers=headers)
        assert resp3.status_code == status.HTTP_200_OK

        resp4 = api_client.get("/api/v1/alerts/ALT_P101_001", headers=headers)
        assert resp4.status_code == status.HTTP_200_OK

    # Verify counts remain strictly identical
    post_readings = isolated_db.query(func.count(VitalsReading.reading_id)).scalar()
    post_alerts = isolated_db.query(func.count(Alert.alert_id)).scalar()

    assert post_readings == initial_readings, "Readings count must not change on GET calls."
    assert post_alerts == initial_alerts, "Alerts count must not change on GET calls."


# =============================================================================
# 10. Strict Read-Only MongoDB Atlas Double Verification
# =============================================================================

def test_readonly_mongo_double_allows_queries_and_blocks_mutations(
    readonly_mongo_db: StrictReadOnlyMongoDatabase,
):
    """
    Verify that the StrictReadOnlyMongoDatabase test double permits analytical reads
    but aggressively rejects all insert, update, replace, delete, bulk write, and $out stages.
    """
    coll = readonly_mongo_db["telemetry_events"]

    # 1. Read operations succeed
    count = coll.count_documents({})
    assert count == 10

    doc = coll.find_one({"event_id": "EVT_MOCK_0"})
    assert doc is not None
    assert doc["patient_id"] == "P101"

    cursor = list(coll.find({"patient_id": "P101"}).limit(5))
    assert len(cursor) == 5

    # 2. Write operations are strictly blocked with MongoWriteViolationError
    with pytest.raises(MongoWriteViolationError, match="insert_one.*is strictly forbidden"):
        coll.insert_one({"event_id": "MALICIOUS_INSERT", "patient_id": "P101"})

    with pytest.raises(MongoWriteViolationError, match="insert_many.*is strictly forbidden"):
        coll.insert_many([{"event_id": "MALICIOUS_BATCH"}])

    with pytest.raises(MongoWriteViolationError, match="update_one.*is strictly forbidden"):
        coll.update_one({"event_id": "EVT_MOCK_0"}, {"$set": {"heart_rate": 999}})

    with pytest.raises(MongoWriteViolationError, match="update_many.*is strictly forbidden"):
        coll.update_many({}, {"$set": {"tampered": True}})

    with pytest.raises(MongoWriteViolationError, match="delete_one.*is strictly forbidden"):
        coll.delete_one({"event_id": "EVT_MOCK_0"})

    with pytest.raises(MongoWriteViolationError, match="delete_many.*is strictly forbidden"):
        coll.delete_many({})

    with pytest.raises(MongoWriteViolationError, match="drop.*is strictly forbidden"):
        coll.drop()

    with pytest.raises(MongoWriteViolationError, match=r"aggregation stage '\$out'"):
        coll.aggregate([{"$match": {"patient_id": "P101"}}, {"$out": "telemetry_dump"}])

    with pytest.raises(MongoWriteViolationError, match=r"aggregation stage '\$merge'"):
        coll.aggregate([{"$match": {"patient_id": "P101"}}, {"$merge": {"into": "telemetry_dump"}}])

    # 3. Verify document count remains invariant at 10
    assert coll.count_documents({}) == 10
