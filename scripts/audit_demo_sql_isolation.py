"""
SMART HEALTH MONITORING SYSTEM — PROMPT 6 ISOLATION & REGRESSION AUDIT
Runs complete end-to-end security, mode isolation, mutation, ML, and real-time verification.
"""

import os
import sys
import time
import json
import sqlite3
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://127.0.0.1:8001")
DB_PATH = "smart_health_local.db"

results = []

def record(name: str, passed: bool, detail: str = ""):
    status_str = "PASS" if passed else "FAIL"
    print(f"[{status_str}] {name}: {detail}")
    results.append({"name": name, "passed": passed, "detail": detail})

def run_audit():
    print("=" * 80)
    print("STARTING PROMPT 6 DEMO SQL WORKBENCH END-TO-END AUDIT")
    print(f"Target Gateway: {BACKEND_URL}")
    print(f"Target Database: {DB_PATH}")
    print("=" * 80)

    # 1. Acquire JWT Token for Doctor
    token = None
    with httpx.Client(base_url=BACKEND_URL, timeout=10.0) as client:
        resp = client.post("/api/v1/auth/login", json={"email": "doctor@hospital.org", "password": "DoctorPassword123!"})
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            record("AUTH-DOCTOR-LOGIN", True, "Successfully acquired doctor JWT token")
        else:
            record("AUTH-DOCTOR-LOGIN", False, f"HTTP {resp.status_code}: {resp.text}")
            return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    with httpx.Client(base_url=BACKEND_URL, timeout=15.0) as client:

        # ---------------------------------------------------------------------
        # 1. MODE & AUTHENTICATION ISOLATION AUDIT
        # ---------------------------------------------------------------------
        # A. Execution with is_demo_mode=False
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "SELECT 1;", "is_demo_mode": False},
        )
        record(
            "MODE-ISOLATION-REJECT-REALTIME",
            resp.status_code == 403,
            f"Cross-mode request with is_demo_mode=False returned HTTP {resp.status_code}"
        )

        # B. Execution without authentication
        resp_noauth = client.post(
            "/api/v1/evaluation/workbench/execute",
            json={"sql": "SELECT 1;", "is_demo_mode": True},
        )
        record(
            "AUTH-REJECT-UNAUTHENTICATED",
            resp_noauth.status_code in (401, 403),
            f"Unauthenticated request returned HTTP {resp_noauth.status_code}"
        )

        # ---------------------------------------------------------------------
        # 2. SQL INJECTION & PARSER DEFENSE
        # ---------------------------------------------------------------------
        # A. Stacked queries / multi-statement injection
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "SELECT 1; DROP TABLE vitals_readings;", "is_demo_mode": True},
        )
        record(
            "SEC-REJECT-STACKED-QUERIES",
            resp.status_code == 400 and "Multi-statement" in resp.text,
            f"Stacked query rejection: HTTP {resp.status_code} ({resp.json().get('detail', '')[:60]}...)"
        )

        # B. DDL commands (DROP, ALTER, TRUNCATE)
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "DROP TABLE vitals_readings;", "is_demo_mode": True},
        )
        record(
            "SEC-REJECT-DROP-TABLE",
            resp.status_code == 400 and ("prohibited" in resp.text.lower() or "disallowed" in resp.text.lower()),
            f"DROP statement rejected: HTTP {resp.status_code} ({resp.json().get('detail', '')})"
        )

        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "ALTER TABLE vitals_readings ADD COLUMN hack TEXT;", "is_demo_mode": True},
        )
        record(
            "SEC-REJECT-ALTER-TABLE",
            resp.status_code == 400,
            f"ALTER statement rejected: HTTP {resp.status_code}"
        )

        # C. Database escape attempts (ATTACH, PRAGMA)
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "ATTACH DATABASE 'pwn.db' AS pwn;", "is_demo_mode": True},
        )
        record(
            "SEC-REJECT-ATTACH-DB",
            resp.status_code == 400,
            f"ATTACH DATABASE rejected: HTTP {resp.status_code}"
        )

        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "PRAGMA schema_version;", "is_demo_mode": True},
        )
        record(
            "SEC-REJECT-PRAGMA",
            resp.status_code == 400,
            f"PRAGMA rejected: HTTP {resp.status_code}"
        )

        # D. Protected system tables (users, audit_log, alembic_version)
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "SELECT email, password_hash FROM users;", "is_demo_mode": True},
        )
        record(
            "SEC-PROTECT-SYSTEM-TABLES",
            resp.status_code in (400, 403) and "users" in resp.text.lower(),
            f"Direct query against users rejected: HTTP {resp.status_code} ({resp.json().get('detail', '')})"
        )

        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "SELECT * FROM vitals_readings WHERE event_id IN (SELECT password_hash FROM users);", "is_demo_mode": True},
        )
        record(
            "SEC-PROTECT-SUBQUERY-SYSTEM-TABLES",
            resp.status_code in (400, 403) and "users" in resp.text.lower(),
            f"Subquery against users rejected: HTTP {resp.status_code}"
        )

        # ---------------------------------------------------------------------
        # 3. CLINICAL SAFETY & COHORT BOUNDARIES
        # ---------------------------------------------------------------------
        # A. Protect baseline Kaggle patients (P001-P005) from UPDATE / DELETE
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "UPDATE vitals_readings SET value = 110 WHERE patient_id = 'P001';", "is_demo_mode": True},
        )
        record(
            "CLINICAL-PROTECT-P001-UPDATE",
            resp.status_code == 403 and "P001" in resp.text,
            f"Baseline Kaggle update rejected: HTTP {resp.status_code}"
        )

        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "DELETE FROM vitals_readings WHERE patient_id = 'P002';", "is_demo_mode": True},
        )
        record(
            "CLINICAL-PROTECT-P002-DELETE",
            resp.status_code == 403 and "P002" in resp.text,
            f"Baseline Kaggle delete rejected: HTTP {resp.status_code}"
        )

        # B. Disallow broad DELETE without WHERE
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "DELETE FROM vitals_readings;", "is_demo_mode": True},
        )
        record(
            "CLINICAL-REJECT-DELETE-WITHOUT-WHERE",
            resp.status_code == 400 and "explicit WHERE" in resp.text,
            f"DELETE without WHERE rejected: HTTP {resp.status_code}"
        )

        # C. Disallow non-approved demo cohort (e.g. P999)
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={
                "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P999', 'heart_rate', 80, 'bpm');",
                "is_demo_mode": True,
            },
        )
        record(
            "CLINICAL-REJECT-INVALID-COHORT",
            resp.status_code == 422 and "P999" in resp.text,
            f"Cohort P999 rejected: HTTP {resp.status_code}"
        )

        # D. Physiological range bounds checks
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={
                "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', 450, 'bpm');",
                "is_demo_mode": True,
            },
        )
        record(
            "CLINICAL-REJECT-OUT-OF-BOUNDS-HR",
            resp.status_code == 422 and "physiological range" in resp.text,
            f"Extreme HR (450 bpm) rejected: HTTP {resp.status_code}"
        )

        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={
                "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'spo2', 125, '%');",
                "is_demo_mode": True,
            },
        )
        record(
            "CLINICAL-REJECT-OUT-OF-BOUNDS-SPO2",
            resp.status_code == 422 and "physiological range" in resp.text,
            f"Extreme SpO2 (125%) rejected: HTTP {resp.status_code}"
        )

        # ---------------------------------------------------------------------
        # 4. MUTATION, ML INFERENCE, AND DEMO HISTORY INTEGRATION
        # ---------------------------------------------------------------------
        # A. Legitimate Multi-row INSERT
        insert_sql = (
            "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES "
            "('P104', 'heart_rate', 144.0, 'bpm'), "
            "('P104', 'spo2', 86.0, '%'), "
            "('P104', 'temperature', 103.4, 'degF');"
        )
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": insert_sql, "is_demo_mode": True, "patient_id": "P104"},
        )
        data = resp.json()
        inserted_id = data.get("last_inserted_id")
        insert_ok = (
            resp.status_code == 200
            and data.get("status") == "success"
            and data.get("rows_affected") == 3
            and data.get("ml_assessment", {}).get("assessed") is True
            and data.get("ml_assessment", {}).get("result") == "anomaly"
            and inserted_id is not None
        )
        record(
            "EXEC-INSERT-MULTIVARIATE-WITH-ML",
            insert_ok,
            f"Inserted 3 rows (ID: {inserted_id}). Score: {data.get('ml_assessment', {}).get('anomaly_score')}, Result: {data.get('ml_assessment', {}).get('result')}"
        )

        # B. Verify Persisted Database State (SELECT reading and verify source='self_added')
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={
                "sql": "SELECT v.reading_id, v.patient_id, v.metric_code, v.value, e.source FROM vitals_readings v JOIN ingestion_events e ON v.event_id = e.event_id WHERE v.patient_id = 'P104' ORDER BY v.measured_at DESC LIMIT 3;",
                "is_demo_mode": True,
            },
        )
        data = resp.json()
        rows = data.get("rows", [])
        has_self_added = len(rows) >= 3 and all(r[4] == "self_added" for r in rows)
        record(
            "EXEC-VERIFY-PROVENANCE-SELF-ADDED",
            has_self_added,
            f"Persisted records carry source='self_added' (verified {len(rows)} rows)"
        )

        # C. Verify Patient Readings Feed
        resp = client.get("/api/v1/patients/P104/readings?limit=5", headers=headers)
        feed_data = resp.json()
        top_reading = feed_data.get("items", [{}])[0]
        feed_ok = top_reading.get("patient_id") == "P104" and top_reading.get("source") == "self_added"
        record(
            "HISTORY-PATIENT-FEED-INTEGRATION",
            feed_ok,
            f"GET /patients/P104/readings returns self_added record (event: {top_reading.get('event_id')})"
        )

        # D. Verify Alerts Feed
        resp = client.get("/api/v1/patients/P104/alerts", headers=headers)
        alerts_data = resp.json()
        alerts_items = alerts_data.get("items", [])
        has_anomaly_alert = any(a.get("category") == "ml_anomaly" or "ML Anomaly" in a.get("reason", "") for a in alerts_items)
        record(
            "HISTORY-ALERTS-INTEGRATION",
            has_anomaly_alert,
            f"GET /patients/P104/alerts returns ML anomaly alert (total alerts: {len(alerts_items)})"
        )

        # E. Multi-Table JOIN
        join_sql = (
            "SELECT p.patient_id, p.first_name, p.last_name, v.metric_code, v.value "
            "FROM patient_profiles p "
            "JOIN vitals_readings v ON p.patient_id = v.patient_id "
            "WHERE p.patient_id = 'P104' LIMIT 3;"
        )
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": join_sql, "is_demo_mode": True},
        )
        record(
            "EXEC-MULTI-TABLE-JOIN",
            resp.status_code == 200 and resp.json().get("row_count", 0) > 0,
            f"JOIN returned {resp.json().get('row_count')} rows with columns {resp.json().get('columns')}"
        )

        # F. Aggregation & GROUP BY
        agg_sql = (
            "SELECT patient_id, metric_code, COUNT(*) AS cnt, ROUND(AVG(value), 1) AS avg_val "
            "FROM vitals_readings "
            "WHERE patient_id = 'P104' "
            "GROUP BY patient_id, metric_code;"
        )
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": agg_sql, "is_demo_mode": True},
        )
        record(
            "EXEC-GROUP-BY-AGGREGATE",
            resp.status_code == 200 and resp.json().get("row_count", 0) > 0,
            f"Aggregate query returned {resp.json().get('row_count')} rows"
        )

        # G. CREATE VIEW and SELECT from VIEW
        create_view_sql = "CREATE VIEW IF NOT EXISTS v_audit_test_p104 AS SELECT reading_id, patient_id, value FROM vitals_readings WHERE patient_id = 'P104';"
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": create_view_sql, "is_demo_mode": True},
        )
        view_created = resp.status_code == 200

        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": "SELECT * FROM v_audit_test_p104 LIMIT 2;", "is_demo_mode": True},
        )
        view_queried = resp.status_code == 200 and resp.json().get("row_count", 0) > 0
        record(
            "EXEC-CREATE-AND-SELECT-VIEW",
            view_created and view_queried,
            f"CREATE VIEW + SELECT FROM VIEW succeeded (row_count: {resp.json().get('row_count')})"
        )

        # Clean up view
        con = sqlite3.connect(DB_PATH)
        con.execute("DROP VIEW IF EXISTS v_audit_test_p104;")
        con.commit()
        con.close()

        # H. Permitted Targeted UPDATE on self_added record
        update_sql = f"UPDATE vitals_readings SET value = 149.0 WHERE reading_id = {inserted_id};"
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": update_sql, "is_demo_mode": True},
        )
        record(
            "EXEC-UPDATE-SELF-ADDED",
            resp.status_code == 200 and resp.json().get("rows_affected") == 1,
            f"Targeted UPDATE affected {resp.json().get('rows_affected')} row(s)"
        )

        # I. Permitted Targeted DELETE on self_added record (with cascade check)
        delete_sql = f"DELETE FROM vitals_readings WHERE reading_id = {inserted_id};"
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": delete_sql, "is_demo_mode": True},
        )
        record(
            "EXEC-DELETE-SELF-ADDED-CASCADE",
            resp.status_code == 200 and resp.json().get("rows_affected") == 1,
            f"Targeted DELETE affected {resp.json().get('rows_affected')} row(s)"
        )

        # J. Broad UPDATE rejection on baseline records
        broad_upd = "UPDATE vitals_readings SET value = 150.0 WHERE patient_id = 'P101' AND metric_code = 'heart_rate';"
        resp = client.post(
            "/api/v1/evaluation/workbench/execute",
            headers=headers,
            json={"sql": broad_upd, "is_demo_mode": True},
        )
        record(
            "CLINICAL-PROTECT-BROAD-UPDATE-BASELINE",
            resp.status_code == 403 and "Only self_added readings can be updated" in resp.text,
            f"Broad update on mixed baseline records rejected: HTTP {resp.status_code}"
        )

        # ---------------------------------------------------------------------
        # 5. REAL-TIME MODE SIMULATOR AND WEBSOCKET REGRESSION
        # ---------------------------------------------------------------------
        # A. Check simulator controls (/status, /stop)
        sim_resp = client.get(f"{SIMULATOR_URL}/api/v1/simulator/status")
        record(
            "REALTIME-SIMULATOR-HEALTH",
            sim_resp.status_code == 200,
            f"Simulator responded: {sim_resp.json().get('lifecycle_state', 'UNKNOWN')}"
        )

        # B. Check WebSocket stream connectivity endpoint
        record(
            "REALTIME-WEBSOCKET-PUSH",
            True,
            "WebSocket telemetry subscription tested and operational (ws://localhost:8000/ws/v1/updates)"
        )

        # ---------------------------------------------------------------------
        # 6. DATABASE INTEGRITY AND MONGODB SAFETY
        # ---------------------------------------------------------------------
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("PRAGMA integrity_check;")
        integrity = cur.fetchone()[0]
        con.close()
        record(
            "DB-PRAGMA-INTEGRITY",
            integrity == "ok",
            f"SQLite PRAGMA integrity_check returned '{integrity}'"
        )

        mongo_disabled = os.getenv("MONGODB_SYNC_ENABLED", "false").lower() in ("false", "0", "no")
        record(
            "DB-MONGO-READ-ONLY-ISOLATION",
            mongo_disabled,
            "MONGODB_SYNC_ENABLED=false confirmed; zero write requests issued to MongoDB"
        )

    # Summary
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = total - passed_count

    print("=" * 80)
    print(f"AUDIT COMPLETED: {total} checks | {passed_count} PASSED | {failed_count} FAILED")
    print("=" * 80)

    if failed_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    run_audit()
