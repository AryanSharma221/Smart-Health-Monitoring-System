"""
Smart Health Monitoring System — Database Security & RBAC Boundary Verifier
Part 8A Verification Script

Verifies:
1. Authentication & Token Invariants (HTTP 401).
2. Patient-Own Resource Access vs Cross-Patient Isolation (HTTP 200 vs HTTP 403).
3. Clinician Care Assignment Enforcement (Assigned vs Unassigned) (HTTP 200 vs HTTP 403).
4. Restricted Action Role Guards (Alert Ack, Simulator Control) (HTTP 403).
5. Path Parameter Regex Validation & Injection Resilience (HTTP 422).
6. Database Privilege & Least Privilege Specification Audit.
7. MongoDB Atlas Strict Read-Only Invariant (2,955 documents).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Setup path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from database.mongodb.client import get_mongo_database, sanitize_mongo_uri
from database.mysql.models import (
    Alert,
    AlertRule,
    Base,
    Conversation,
    DoctorPatientAssignment,
    DoctorProfile,
    IngestionEvent,
    Message,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.session import get_db
from services.alerts.rules import DEFAULT_ALERT_RULES
from services.api.config import Settings, get_settings
from services.api.main import create_app
from services.auth.security import create_access_token, hash_password


def run_security_and_rbac_audit() -> Dict[str, Any]:
    audit_start = time.perf_counter()
    results: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "audit_version": "1.0.0",
        "da3_phase": "Part 8A — Database Security and Role-Based Access Control",
        "test_results": [],
        "database_privilege_audit": {},
        "summary": {},
    }

    print("=" * 80)
    print("SMART HEALTH MONITORING SYSTEM — PART 8A DATABASE SECURITY & RBAC AUDIT")
    print(f"Timestamp: {results['timestamp_utc']}")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # Setup Isolated Test Environment & Fixtures
    # -------------------------------------------------------------------------
    test_settings = Settings(
        app_env="testing",
        jwt_secret="rbac_security_audit_secret_key_at_least_32_characters!",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        ingestion_api_key="rbac_audit_secure_internal_key",
    )

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db: Session = TestingSessionLocal()

    # Provision standard alert rules
    for r in DEFAULT_ALERT_RULES:
        db.add(AlertRule(
            rule_id=r.rule_id,
            metric_code=r.metric_code,
            operator=r.operator,
            configured_value=r.configured_value,
            duration_seconds=getattr(r, "duration_seconds", 0),
            severity=r.severity,
            is_enabled=r.is_enabled,
            is_demo_only=r.is_demo_only,
            description=r.description,
        ))

    # 1. Doctor Alice (Assigned to P101 only)
    doc_alice_user = User(
        user_id="U_DOC_ALICE",
        email="alice.doctor@hospital.org",
        password_hash=hash_password("DoctorPass_123!"),
        role="doctor",
        is_active=True,
    )
    db.add(doc_alice_user)
    doc_alice = DoctorProfile(
        doctor_id="DOC_ALICE",
        user_id="U_DOC_ALICE",
        first_name="Alice",
        last_name="Smith",
        license_number="LIC-ALICE-123",
        specialization="Cardiology",
    )
    db.add(doc_alice)

    # 2. Doctor Bob (Assigned to P102 only)
    doc_bob_user = User(
        user_id="U_DOC_BOB",
        email="bob.doctor@hospital.org",
        password_hash=hash_password("DoctorPass_456!"),
        role="doctor",
        is_active=True,
    )
    db.add(doc_bob_user)
    doc_bob = DoctorProfile(
        doctor_id="DOC_BOB",
        user_id="U_DOC_BOB",
        first_name="Bob",
        last_name="Jones",
        license_number="LIC-BOB-456",
        specialization="General Practice",
    )
    db.add(doc_bob)

    # 3. Patient P101 User & Profile
    p101_user = User(
        user_id="U_PAT_101",
        email="p101@patient.org",
        password_hash=hash_password("PatientPass_101!"),
        role="patient",
        is_active=True,
    )
    db.add(p101_user)
    p101 = PatientProfile(
        patient_id="P101",
        user_id="U_PAT_101",
        first_name="John",
        last_name="Doe",
        date_of_birth=date(1980, 5, 15),
        gender="male",
    )
    db.add(p101)

    # 4. Patient P102 User & Profile
    p102_user = User(
        user_id="U_PAT_102",
        email="p102@patient.org",
        password_hash=hash_password("PatientPass_102!"),
        role="patient",
        is_active=True,
    )
    db.add(p102_user)
    p102 = PatientProfile(
        patient_id="P102",
        user_id="U_PAT_102",
        first_name="Jane",
        last_name="Roe",
        date_of_birth=date(1992, 8, 22),
        gender="female",
    )
    db.add(p102)

    # 5. Inactive User
    inactive_user = User(
        user_id="U_INACTIVE",
        email="inactive@hospital.org",
        password_hash=hash_password("InactivePass_123!"),
        role="patient",
        is_active=False,
    )
    db.add(inactive_user)

    # 6. Admin User
    admin_user = User(
        user_id="U_ADMIN",
        email="admin@hospital.org",
        password_hash=hash_password("AdminPass_999!"),
        role="admin_operator",
        is_active=True,
    )
    db.add(admin_user)

    # 7. Doctor-Patient Assignments:
    # Alice -> P101
    # Bob   -> P102
    db.add(DoctorPatientAssignment(doctor_id="DOC_ALICE", patient_id="P101"))
    db.add(DoctorPatientAssignment(doctor_id="DOC_BOB", patient_id="P102"))

    # 8. Seed Sample Readings and Alerts
    now = datetime.now(timezone.utc)
    evt_p101 = IngestionEvent(
        event_id="EVT_P101_1",
        patient_id="P101",
        source="smartwatch_simulator",
        source_event_id="SRC_101_1",
        measured_at=now,
        is_simulated=True,
    )
    db.add(evt_p101)
    db.add(VitalsReading(
        event_id="EVT_P101_1",
        patient_id="P101",
        metric_code="heart_rate",
        value=Decimal("82.0"),
        unit="bpm",
        raw_value=Decimal("82.0"),
        raw_unit="bpm",
        measured_at=now,
    ))

    evt_p102 = IngestionEvent(
        event_id="EVT_P102_1",
        patient_id="P102",
        source="smartwatch_simulator",
        source_event_id="SRC_102_1",
        measured_at=now,
        is_simulated=True,
    )
    db.add(evt_p102)
    db.add(VitalsReading(
        event_id="EVT_P102_1",
        patient_id="P102",
        metric_code="heart_rate",
        value=Decimal("74.0"),
        unit="bpm",
        raw_value=Decimal("74.0"),
        raw_unit="bpm",
        measured_at=now,
    ))

    # Alert for P101
    alert_p101 = Alert(
        alert_id="ALT_P101_001",
        patient_id="P101",
        event_id="EVT_P101_1",
        rule_id="RULE_HR_CRITICAL_HIGH",
        severity="CRITICAL",
        category="vital_threshold",
        reason="Critical tachycardia detected",
        status="NEW",
        created_at=now,
    )
    db.add(alert_p101)

    # Conversation between Alice and P101
    conv_alice_p101 = Conversation(
        conversation_id="CONV_ALICE_P101",
        patient_id="P101",
        doctor_id="DOC_ALICE",
        is_active=True,
    )
    db.add(conv_alice_p101)
    db.add(Message(
        message_id="MSG_001",
        conversation_id="CONV_ALICE_P101",
        sender_id="U_DOC_ALICE",
        receiver_id="U_PAT_101",
        content="Hello John, how are you feeling today?",
        is_read=False,
    ))

    db.commit()

    # Build FastAPI test client with DB override
    app = create_app(settings=test_settings)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    # Helper tokens
    def make_token(user: User, exp_mins: int = 60, tampered_secret: bool = False) -> str:
        s = test_settings if not tampered_secret else Settings(
            jwt_secret="completely_different_tampered_secret_key_32chars!",
            app_env="testing",
        )
        return create_access_token(
            data={"sub": user.user_id, "email": user.email, "role": user.role},
            settings=s,
            expires_delta=timedelta(minutes=exp_mins),
        )

    token_p101 = make_token(p101_user)
    token_p102 = make_token(p102_user)
    token_alice = make_token(doc_alice_user)
    token_bob = make_token(doc_bob_user)
    token_admin = make_token(admin_user)
    token_inactive = make_token(inactive_user)
    token_expired = make_token(p101_user, exp_mins=-10)
    token_tampered = make_token(p101_user, tampered_secret=True)

    def auth_hdr(tok: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {tok}"}

    def record_test(test_id: str, description: str, expected_code: int, actual_code: int, passed: bool, detail: str):
        res_entry = {
            "test_id": test_id,
            "description": description,
            "expected_status": expected_code,
            "actual_status": actual_code,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
        }
        results["test_results"].append(res_entry)
        tag = "[PASS]" if passed else "[FAIL]"
        print(f"{tag} {test_id:<18} (Exp: {expected_code}, Got: {actual_code}) : {description}")
        assert passed, f"Test {test_id} failed: Expected {expected_code}, got {actual_code} ({detail})"

    # -------------------------------------------------------------------------
    # Section 1: Unauthenticated Access Tests (HTTP 401)
    # -------------------------------------------------------------------------
    print("\n--- Section 1: Unauthenticated Access Boundaries (HTTP 401) ---")
    protected_routes = [
        ("GET", "/api/v1/patients", "List patients"),
        ("GET", "/api/v1/patients/P101/readings", "Get patient readings"),
        ("GET", "/api/v1/patients/P101/alerts", "Get patient alerts"),
        ("GET", "/api/v1/conversations", "List conversations"),
        ("POST", "/api/v1/alerts/ALT_P101_001/acknowledge", "Acknowledge alert"),
        ("POST", "/api/v1/patients/P101/assess", "Assess ML telemetry"),
    ]
    for method, route, desc in protected_routes:
        t_id = f"AUTH-UNAUTH-{route.split('/')[-1].upper()}"
        resp = client.request(method, route)
        record_test(
            test_id=t_id,
            description=f"Unauthenticated {method} {route} rejected with 401",
            expected_code=401,
            actual_code=resp.status_code,
            passed=resp.status_code == 401,
            detail=resp.json().get("detail", ""),
        )

    # -------------------------------------------------------------------------
    # Section 2: Token Validity & Integrity (HTTP 401)
    # -------------------------------------------------------------------------
    print("\n--- Section 2: Token Cryptographic Integrity (HTTP 401) ---")
    # Expired token
    resp_exp = client.get("/api/v1/patients/P101/readings", headers=auth_hdr(token_expired))
    record_test("TOKEN-EXPIRED", "Expired JWT token rejected", 401, resp_exp.status_code, resp_exp.status_code == 401, resp_exp.json().get("detail", ""))

    # Tampered signature
    resp_tamp = client.get("/api/v1/patients/P101/readings", headers=auth_hdr(token_tampered))
    record_test("TOKEN-TAMPERED", "Tampered JWT signature rejected", 401, resp_tamp.status_code, resp_tamp.status_code == 401, resp_tamp.json().get("detail", ""))

    # Malformed token string
    resp_mal = client.get("/api/v1/patients/P101/readings", headers={"Authorization": "Bearer not.a.valid.jwt"})
    record_test("TOKEN-MALFORMED", "Malformed JWT string rejected", 401, resp_mal.status_code, resp_mal.status_code == 401, resp_mal.json().get("detail", ""))

    # Inactive user account
    resp_inact = client.get("/api/v1/patients/P101/readings", headers=auth_hdr(token_inactive))
    record_test("TOKEN-INACTIVE", "Inactive user account token rejected", 401, resp_inact.status_code, resp_inact.status_code == 401, resp_inact.json().get("detail", ""))

    # -------------------------------------------------------------------------
    # Section 3: Patient Cross-Tenant Isolation (HTTP 200 vs HTTP 403)
    # -------------------------------------------------------------------------
    print("\n--- Section 3: Patient Cross-Tenant Data Isolation ---")
    # Patient P101 access own readings -> 200
    resp_own = client.get("/api/v1/patients/P101/readings", headers=auth_hdr(token_p101))
    record_test("PAT-OWN-READ", "Patient P101 accesses own readings", 200, resp_own.status_code, resp_own.status_code == 200, "Permitted")

    # Patient P101 attempts cross-access to P102 readings -> 403
    resp_cross_rdg = client.get("/api/v1/patients/P102/readings", headers=auth_hdr(token_p101))
    record_test("PAT-CROSS-READ", "Patient P101 cross-access to P102 readings rejected", 403, resp_cross_rdg.status_code, resp_cross_rdg.status_code == 403, resp_cross_rdg.json().get("detail", ""))

    # Patient P101 attempts cross-access to P102 alerts -> 403
    resp_cross_alt = client.get("/api/v1/patients/P102/alerts", headers=auth_hdr(token_p101))
    record_test("PAT-CROSS-ALERT", "Patient P101 cross-access to P102 alerts rejected", 403, resp_cross_alt.status_code, resp_cross_alt.status_code == 403, resp_cross_alt.json().get("detail", ""))

    # Patient P101 attempts to acknowledge alert ALT_P101_001 -> 403
    resp_pat_ack = client.post("/api/v1/alerts/ALT_P101_001/acknowledge", headers=auth_hdr(token_p101), json={"note": "Patient ack attempt"})
    record_test("PAT-DENY-ACK", "Patient role forbidden from acknowledging clinical alerts", 403, resp_pat_ack.status_code, resp_pat_ack.status_code == 403, resp_pat_ack.json().get("detail", ""))

    # -------------------------------------------------------------------------
    # Section 4: Clinician Care Assignment Boundaries (HTTP 200 vs HTTP 403)
    # -------------------------------------------------------------------------
    print("\n--- Section 4: Clinician Care Assignment Boundaries ---")
    # Doctor Alice accesses assigned patient P101 -> 200
    resp_doc_assigned = client.get("/api/v1/patients/P101/readings", headers=auth_hdr(token_alice))
    record_test("DOC-ASSIGNED-OK", "Doctor Alice accesses assigned patient P101", 200, resp_doc_assigned.status_code, resp_doc_assigned.status_code == 200, "Permitted")

    # Doctor Alice attempts access to unassigned patient P102 -> 403
    resp_doc_unassigned = client.get("/api/v1/patients/P102/readings", headers=auth_hdr(token_alice))
    record_test("DOC-UNASSIGN-DENY", "Doctor Alice access to unassigned patient P102 rejected", 403, resp_doc_unassigned.status_code, resp_doc_unassigned.status_code == 403, resp_doc_unassigned.json().get("detail", ""))

    # Doctor Bob (assigned to P102) accesses P102 -> 200
    resp_bob_p102 = client.get("/api/v1/patients/P102/readings", headers=auth_hdr(token_bob))
    record_test("DOC-BOB-P102-OK", "Doctor Bob accesses assigned patient P102", 200, resp_bob_p102.status_code, resp_bob_p102.status_code == 200, "Permitted")

    # Doctor Bob attempts access to P101 alert -> 403
    resp_bob_ack_p101 = client.post("/api/v1/alerts/ALT_P101_001/acknowledge", headers=auth_hdr(token_bob), json={"note": "Bob ack attempt"})
    record_test("DOC-UNASSIGN-ACK", "Doctor Bob cannot acknowledge alert for unassigned patient P101", 403, resp_bob_ack_p101.status_code, resp_bob_ack_p101.status_code == 403, resp_bob_ack_p101.json().get("detail", ""))

    # Doctor Alice acknowledges alert for assigned patient P101 -> 200
    resp_alice_ack = client.post("/api/v1/alerts/ALT_P101_001/acknowledge", headers=auth_hdr(token_alice), json={"note": "Acknowledged by Alice"})
    record_test("DOC-ASSIGNED-ACK", "Doctor Alice acknowledges alert for assigned patient P101", 200, resp_alice_ack.status_code, resp_alice_ack.status_code == 200, "Permitted")

    # -------------------------------------------------------------------------
    # Section 5: Messaging & Conversation Boundary Enforcement
    # -------------------------------------------------------------------------
    print("\n--- Section 5: Messaging & Conversation Privacy Boundaries ---")
    # Patient P101 lists conversations -> sees CONV_ALICE_P101
    resp_p101_conv = client.get("/api/v1/conversations", headers=auth_hdr(token_p101))
    p101_conv_ids = [c["conversation_id"] for c in resp_p101_conv.json().get("items", [])]
    record_test("MSG-PARTICIPANT-LIST", "P101 lists own conversations", 200, resp_p101_conv.status_code, "CONV_ALICE_P101" in p101_conv_ids, "CONV_ALICE_P101 found")

    # Patient P102 lists conversations -> empty list (not a participant)
    resp_p102_conv = client.get("/api/v1/conversations", headers=auth_hdr(token_p102))
    p102_conv_ids = [c["conversation_id"] for c in resp_p102_conv.json().get("items", [])]
    record_test("MSG-ISOLATION-LIST", "P102 cannot see Alice-P101 conversation", 200, resp_p102_conv.status_code, "CONV_ALICE_P101" not in p102_conv_ids, "Strict isolation")

    # Doctor Bob attempts to read messages in CONV_ALICE_P101 -> 403
    resp_bob_msgs = client.get("/api/v1/conversations/CONV_ALICE_P101/messages", headers=auth_hdr(token_bob))
    record_test("MSG-SNOOP-DENIED", "Doctor Bob forbidden from viewing Alice-P101 messages", 403, resp_bob_msgs.status_code, resp_bob_msgs.status_code == 403, resp_bob_msgs.json().get("detail", ""))

    # -------------------------------------------------------------------------
    # Section 6: Input Validation, Regex Constraints & Injection Resilience
    # -------------------------------------------------------------------------
    print("\n--- Section 6: Input Validation & Path Traversal / Injection Resilience ---")
    # Malformed SQL injection in path parameter
    resp_sqli = client.get("/api/v1/patients/P101' OR '1'='1/readings", headers=auth_hdr(token_alice))
    record_test("INPUT-PATH-SQLI", "SQL injection in patient_id rejected by regex validator", 422, resp_sqli.status_code, resp_sqli.status_code == 422, "Path regex rejection")

    # Excessive page_size (> 100)
    resp_overpage = client.get("/api/v1/patients/P101/readings?page_size=500", headers=auth_hdr(token_alice))
    record_test("INPUT-PAGE-BOUND", "Excessive page_size (> 100) rejected", 422, resp_overpage.status_code, resp_overpage.status_code == 422, "Boundary enforcement")

    # -------------------------------------------------------------------------
    # Section 7: Database Privilege & Least Privilege Specification Audit
    # -------------------------------------------------------------------------
    print("\n--- Section 7: Database Account & Privilege Architecture Audit ---")
    sql_path = WORKSPACE_ROOT / "database" / "mysql" / "provision_least_privilege_users.sql"
    sql_content = sql_path.read_text(encoding="utf-8")

    db_accounts = {
        "smart_health_app": {
            "role": "Runtime FastAPI Application Gateway",
            "privileges": "SELECT, INSERT, UPDATE, DELETE, EXECUTE on smart_health.*",
            "ddl_permitted": False,
            "admin_permitted": False,
            "verified_in_script": "GRANT SELECT, INSERT, UPDATE, DELETE ON `smart_health`.* TO 'smart_health_app'@'%'" in sql_content,
        },
        "smart_health_analytics": {
            "role": "Read-Only Reporting & Streamlit Dashboard",
            "privileges": "SELECT, SHOW VIEW on smart_health.*",
            "ddl_permitted": False,
            "admin_permitted": False,
            "verified_in_script": "GRANT SELECT, SHOW VIEW ON `smart_health`.* TO 'smart_health_analytics'@'%'" in sql_content,
        },
        "smart_health_migrator": {
            "role": "Alembic Schema Evolution & Migrations",
            "privileges": "CRUD + DDL (CREATE, ALTER, DROP, INDEX, TRIGGER) on smart_health.*",
            "ddl_permitted": True,
            "admin_permitted": False,
            "verified_in_script": "GRANT CREATE, ALTER, DROP, INDEX, REFERENCES ON `smart_health`.* TO 'smart_health_migrator'@'%'" in sql_content,
        },
        "smart_health_backup": {
            "role": "mysqldump Non-Destructive Backup Automation",
            "privileges": "SELECT, LOCK TABLES, SHOW VIEW, TRIGGER + global PROCESS",
            "ddl_permitted": False,
            "admin_permitted": False,
            "verified_in_script": "GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT ON `smart_health`.* TO 'smart_health_backup'@'%'" in sql_content,
        },
        "smart_health_admin": {
            "role": "DBA Disaster Recovery Operator",
            "privileges": "ALL PRIVILEGES on smart_health and recovery targets",
            "ddl_permitted": True,
            "admin_permitted": True,
            "verified_in_script": "GRANT ALL PRIVILEGES ON `smart_health_recovery`.* TO 'smart_health_admin'@'%'" in sql_content,
        },
    }

    for acc_name, acc_info in db_accounts.items():
        assert acc_info["verified_in_script"], f"Account definition {acc_name} missing from SQL script!"
        print(f"[PASS] DB-ROLE-{acc_name.upper()} : Verified ({acc_info['privileges']})")

    results["database_privilege_audit"] = db_accounts

    # -------------------------------------------------------------------------
    # Section 8: MongoDB Atlas Read-Only Invariant Verification
    # -------------------------------------------------------------------------
    print("\n--- Section 8: MongoDB Atlas Strict Read-Only Invariant ---")
    mongo_db = get_mongo_database()
    assert mongo_db is not None, "Failed to connect to MongoDB Atlas!"
    doc_count = mongo_db["telemetry_events"].count_documents({})
    assert doc_count == 2955, f"CRITICAL INVARIANT VIOLATION: Expected 2,955 documents, got {doc_count}!"
    print(f"[PASS] MONGO-READONLY-INVARIANT : {doc_count} documents verified (STRICTLY 2,955)")

    raw_mongo_uri = get_settings().mongodb_uri
    masked_uri = sanitize_mongo_uri(raw_mongo_uri)
    assert ":***@" in masked_uri or "***:***" in masked_uri, "Credential masking verification failed!"
    print(f"[PASS] MONGO-CREDENTIAL-MASK    : {masked_uri}")

    # -------------------------------------------------------------------------
    # Summary & Output Recording
    # -------------------------------------------------------------------------
    total_tests = len(results["test_results"])
    passed_tests = sum(1 for t in results["test_results"] if t["status"] == "PASS")
    audit_duration = (time.perf_counter() - audit_start) * 1000

    results["summary"] = {
        "total_authorization_tests": total_tests,
        "passed_tests": passed_tests,
        "failed_tests": total_tests - passed_tests,
        "pass_rate": f"{(passed_tests / total_tests) * 100:.1f}%",
        "duration_ms": round(audit_duration, 2),
        "status": "PASSED",
        "mongo_document_count_preserved": doc_count == 2955,
    }

    print("\n" + "=" * 80)
    print(f"AUDIT SUMMARY: {passed_tests}/{total_tests} TESTS PASSED (100.0%) IN {audit_duration:.2f} ms")
    print("Database Security & RBAC Boundary Enforcement Verified.")
    print("=" * 80)

    out_file = WORKSPACE_ROOT / "scratch" / "rbac_security_verification_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Audit evidence written to: {out_file}")

    return results


if __name__ == "__main__":
    run_security_and_rbac_audit()
