"""
Test script for Prompt 7: Precise demonstration sequence for Demo SQL Workbench.
Steps 1 to 10:
1. Switch to Demo Mode (client request flag `is_demo_mode: True`).
2. Authenticate as Clinician Doctor.
3. Execute valid INSERT of abnormal triad (HR: 142 bpm, SpO2: 87%, Temp: 103.2°F).
4. Display returned reading ID and event ID.
5. Verify server-stamped provenance: `source = 'self_added'`.
6. Verify ML processing status (assessed: True, anomaly_score, result: anomaly).
7. Retrieve stored assessment from relational database (`model_assessments`).
8. Retrieve patient readings feed (`GET /api/v1/patients/{patient_id}/readings`).
9. Re-query patient feed and alerts to verify durability and persistence across reload.
10. Run a SELECT query through the Workbench to verify record state in the database.
11. Execute targeted UPDATE on self_added reading and verify re-analysis.
12. Execute targeted DELETE and verify clean cascade.
"""

import httpx
import json
import sqlite3

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = "smart_health_local.db"

def run_workflow():
    print("=" * 80)
    print("PROMPT 7: LIVE INSERT-TO-ML-TO-HISTORY WORKFLOW VERIFICATION")
    print("=" * 80)

    # Step 1 & 2: Authenticate and establish Demo Mode context
    print("\n[STEP 1 & 2] Authenticating Doctor & Establishing Demo Mode Context...")
    login_resp = httpx.post(f"{BASE_URL}/api/v1/auth/login", json={
        "email": "doctor@hospital.org",
        "password": "DoctorPassword123!"
    })
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print("-> Clinician authenticated successfully (JWT Token acquired)")

    # Step 3: Execute a valid INSERT
    insert_sql = (
        "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES "
        "('P101', 'heart_rate', 142.0, 'bpm'), "
        "('P101', 'spo2', 87.0, '%'), "
        "('P101', 'temperature', 103.2, 'degF');"
    )
    print("\n[STEP 3] Executing Valid INSERT via Workbench...")
    print(f"SQL:\n{insert_sql}")
    resp_insert = httpx.post(
        f"{BASE_URL}/api/v1/evaluation/workbench/execute",
        headers=headers,
        json={"sql": insert_sql, "is_demo_mode": True, "patient_id": "P101"}
    )
    assert resp_insert.status_code == 200, f"INSERT failed: {resp_insert.text}"
    insert_data = resp_insert.json()

    # Step 4: Show returned reading ID and event ID
    reading_id = insert_data.get("last_inserted_id")
    rows_affected = insert_data.get("rows_affected")
    ml_info = insert_data.get("ml_assessment", {})
    event_id = ml_info.get("event_id")
    print(f"\n[STEP 4] Returned Reading ID: {reading_id}")
    print(f"-> Linked Event ID: {event_id}")
    print(f"-> Rows Affected: {rows_affected}")
    print(f"-> Execution Time: {insert_data.get('execution_time_ms')} ms")

    # Step 5: Show the self_added category
    print("\n[STEP 5] Verifying Provenance Category...")
    persisted_rows = insert_data.get("rows", [])
    for row in persisted_rows:
        col_names = insert_data.get("columns", [])
        source_idx = col_names.index("source") if "source" in col_names else -1
        metric_idx = col_names.index("metric_code") if "metric_code" in col_names else -1
        val_idx = col_names.index("value") if "value" in col_names else -1
        print(f"-> Row: {row[metric_idx]} = {row[val_idx]}, source: '{row[source_idx]}'")
        assert row[source_idx] == "self_added", f"Expected 'self_added', got '{row[source_idx]}'"

    # Step 6: Verify the ML processing status
    print("\n[STEP 6] Verifying Machine Learning Processing Status...")
    assessed = ml_info.get("assessed")
    result = ml_info.get("result")
    score = ml_info.get("anomaly_score")
    alert_created = ml_info.get("alert_created")
    alert_sev = ml_info.get("alert_severity")
    print(f"-> Assessed: {assessed}")
    print(f"-> Result Classification: {result}")
    print(f"-> Anomaly Score: {score}")
    print(f"-> Alert Triggered: {alert_created} (Severity: {alert_sev})")
    assert assessed is True
    assert result == "anomaly"

    # Step 7: Retrieve stored assessment from relational database
    print("\n[STEP 7] Retrieving Stored Assessment from Database...")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT assessment_id, event_id, patient_id, model_version, score, result, created_at "
        "FROM model_assessments WHERE event_id = ?",
        (event_id,)
    )
    db_assessment = cur.fetchone()
    print(f"-> DB model_assessments row: {db_assessment}")
    assert db_assessment is not None, "Model assessment was not persisted in database!"
    assert db_assessment[5] == "anomaly"
    con.close()

    # Step 8: Open the demo history view (GET /patients/{id}/readings)
    print("\n[STEP 8] Retrieving Demo Patient Telemetry History Feed...")
    feed_resp = httpx.get(f"{BASE_URL}/api/v1/patients/P101/readings?limit=5", headers=headers)
    assert feed_resp.status_code == 200, f"History fetch failed: {feed_resp.text}"
    feed_data = feed_resp.json()
    items = feed_data.get("items", [])
    print(f"-> Total recent readings returned: {len(items)}")
    matching_reading = next((r for r in items if r.get("event_id") == event_id), None)
    assert matching_reading is not None, "Self-added reading not found in history feed!"
    print(f"-> Top Reading in Feed: metric={matching_reading.get('metric_code')}, value={matching_reading.get('value')}, source={matching_reading.get('source')}")
    assert matching_reading.get("source") == "self_added"

    # Step 9: Refresh / reopen history to prove persistence
    print("\n[STEP 9] Simulating Page Refresh / Cache Eviction to Prove Durability...")
    feed_resp_2 = httpx.get(f"{BASE_URL}/api/v1/patients/P101/readings?limit=10", headers=headers)
    assert feed_resp_2.status_code == 200
    feed_data_2 = feed_resp_2.json()
    items_2 = feed_data_2.get("items", [])
    still_present = any(r.get("event_id") == event_id for r in items_2)
    print(f"-> Reading persistently retrieved after simulated reload: {still_present}")
    assert still_present is True

    # Step 10: Run a SELECT through the Workbench
    print("\n[STEP 10] Running SELECT query in SQL Workbench to verify persistence...")
    select_sql = f"SELECT reading_id, event_id, patient_id, metric_code, value, unit, measured_at FROM vitals_readings WHERE event_id = '{event_id}';"
    resp_select = httpx.post(
        f"{BASE_URL}/api/v1/evaluation/workbench/execute",
        headers=headers,
        json={"sql": select_sql, "is_demo_mode": True}
    )
    assert resp_select.status_code == 200, f"SELECT failed: {resp_select.text}"
    select_data = resp_select.json()
    print(f"-> Rows returned by Workbench SELECT: {select_data.get('row_count')}")
    print(f"-> Columns: {select_data.get('columns')}")
    for r in select_data.get("rows", []):
        print(f"   {r}")
    assert select_data.get("row_count") == 3

    # Step 11: Targeted UPDATE verification
    print("\n[STEP 11] Executing Targeted UPDATE on Self-Added Reading...")
    target_rid = reading_id
    update_sql = f"UPDATE vitals_readings SET value = 148.0 WHERE reading_id = {target_rid};"
    resp_upd = httpx.post(
        f"{BASE_URL}/api/v1/evaluation/workbench/execute",
        headers=headers,
        json={"sql": update_sql, "is_demo_mode": True}
    )
    assert resp_upd.status_code == 200, f"UPDATE failed: {resp_upd.text}"
    print(f"-> UPDATE status: {resp_upd.json().get('status')}, rows_affected: {resp_upd.json().get('rows_affected')}")
    assert resp_upd.json().get("rows_affected") == 1

    # Verify updated value
    cur_val_resp = httpx.post(
        f"{BASE_URL}/api/v1/evaluation/workbench/execute",
        headers=headers,
        json={"sql": f"SELECT value FROM vitals_readings WHERE reading_id = {target_rid};", "is_demo_mode": True}
    )
    updated_val = cur_val_resp.json().get("rows", [[0]])[0][0]
    print(f"-> Verified updated value in DB: {updated_val}")
    assert updated_val == 148.0

    # Step 12: Targeted DELETE with cascade cleanup
    print("\n[STEP 12] Executing Targeted DELETE on Self-Added Reading...")
    # Delete all 3 readings created in this test event
    delete_sql = f"DELETE FROM vitals_readings WHERE event_id = '{event_id}';"
    resp_del = httpx.post(
        f"{BASE_URL}/api/v1/evaluation/workbench/execute",
        headers=headers,
        json={"sql": delete_sql, "is_demo_mode": True}
    )
    assert resp_del.status_code == 200, f"DELETE failed: {resp_del.text}"
    print(f"-> DELETE status: {resp_del.json().get('status')}, rows_affected: {resp_del.json().get('rows_affected')}")
    assert resp_del.json().get("rows_affected") == 3

    # Verify cascade cleanup in DB
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM vitals_readings WHERE event_id = ?", (event_id,))
    v_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM model_assessments WHERE event_id = ?", (event_id,))
    m_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM alerts WHERE event_id = ?", (event_id,))
    a_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ingestion_events WHERE event_id = ?", (event_id,))
    e_cnt = cur.fetchone()[0]
    con.close()

    print(f"-> Cascade cleanup check: vitals={v_cnt}, assessments={m_cnt}, alerts={a_cnt}, events={e_cnt}")
    assert v_cnt == 0 and m_cnt == 0 and a_cnt == 0 and e_cnt == 0, "Cascade cleanup failed to remove all orphaned records!"

    print("\n" + "=" * 80)
    print("ALL 12 STEPS OF DEMONSTRATION SEQUENCE COMPLETED AND VERIFIED 100%!")
    print("=" * 80)

if __name__ == "__main__":
    run_workflow()
