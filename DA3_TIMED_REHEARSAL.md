# DA3 Timed Demonstration Rehearsal Runbook

**Project:** AI-Powered Smart Health Monitoring System  
**Academic Milestone:** Digital Assignment 3 (DA3) Live Demonstration & Technical Defense  
**Rehearsal Execution Date:** 2026-10-15  
**Demonstration Duration Target:** 10–12 Minutes (Adjustable 8–15 Minutes)  
**Evaluator Target:** Academic Database Systems Examiner & Viva Committee  
**Database Protection Status:**  
* **MongoDB Cloud Atlas:** Strictly READ-ONLY (2,955 Invariant Documents, Zero Mutations)  
* **Relational Database:** Protected Baseline Cohorts (`P001`–`P005` & `P101`–`P105` Deletion Blocked)  
* **Academic Evaluation Fixtures:** Isolated to `evaluation_records` table and `EVAL_*` test records  

---

## 1. Executive Summary & Timed Rehearsal Overview

This runbook defines the exact minute-by-minute operational protocol for the live DA3 examination. Every URL, API endpoint, query, button click, and proof mechanism in this guide has been tested and verified against the running microservices on 2026-10-15.

### 1.1 Timing Breakdown (12-Minute Standard Sequence)

```
[0:00 - 1:30] Phase 1: Problem, Objectives & Architecture Overview (1.5 min)
[1:30 - 2:30] Phase 2: Opening Application & Preflight Diagnostics (1.0 min)
[2:30 - 3:30] Phase 3: Database Connectivity & Patient Cohort Inspection (1.0 min)
[3:30 - 5:00] Phase 4: Safe MySQL CRUD on Evaluation Records (1.5 min)
[5:00 - 6:30] Phase 5: Multi-Table Joins, Nested Queries & Views (1.5 min)
[6:30 - 7:30] Phase 6: Stored Functions, Procedures & Triggers (1.0 min)
[7:30 - 8:30] Phase 7: Read-Only MongoDB Atlas Analytics & Invariant (1.0 min)
[8:30 - 9:30] Phase 8: Dashboard Visualizations & Streamlit Analytics (1.0 min)
[9:30 - 10:30] Phase 9: Authentication, RBAC & Security Boundary Tests (1.0 min)
[10:30 - 11:30] Phase 10: Automated Test Evidence & Benchmark Scorecard (1.0 min)
[11:30 - 12:30] Phase 11: Smartwatch Simulator Start, Stop & Resume (1.0 min)
[12:30 - 13:00] Phase 12: Viva Conclusion & Honest Scope Disclosure (0.5 min)
```

---

## 2. Minute-by-Minute Operational Protocol

### Phase 1: Problem, Objectives & Architecture (Minute 0:00 – 1:30)
* **What to Open:** Slide 1–5 in [`docs/submission/Smart_Health_Monitoring_DA3_Presentation.pptx`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/Smart_Health_Monitoring_DA3_Presentation.pptx) or [`docs/submission/02_system_architecture.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/02_system_architecture.md).
* **Operation to Execute:**
  1. State the clinical problem: Wearable sensors generate continuous, high-frequency telemetry (1 Hz) that overwhelms traditional transactional EHR databases.
  2. Explain the hybrid dual-database solution:
     - **Relational System of Record (MySQL 8 InnoDB / SQLite):** Strictly ACID-compliant storage for patient profiles, medical history, clinical alerts, user credentials, and auditable triage notes.
     - **NoSQL System of Analysis (MongoDB Atlas):** High-throughput, schema-less document repository for raw timeseries telemetry events and population-level analytical aggregations.
  3. Highlight ML Integration: Direct FastAPI in-process inference using an unsupervised Isolation Forest model (38 engineered features) with continuous anomaly scoring.
* **Expected Result:** Examiner recognizes clear separation between transactional EHR needs and timeseries analytics.
* **How to Prove Authenticity:**
  - Point to the Mermaid architecture diagram in Section 1 of `02_system_architecture.md`.
  - Cite the 17 authoritative relational tables in [`database/mysql/schema.sql`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mysql/schema.sql).
* **Failure Contingency:** If presentation software is unavailable, open [`docs/submission/presentation_slide_deck.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/presentation_slide_deck.md) in VS Code Markdown Preview.
* **Fallback:** Walk through the architecture flowchart in [`docs/submission/DA3_COMPLETE_PROJECT_REPORT.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/DA3_COMPLETE_PROJECT_REPORT.md).

---

### Phase 2: Opening the Application & Preflight Diagnostics (Minute 1:30 – 2:30)
* **What to Open:** Browser at `http://127.0.0.1:5173` and Terminal window.
* **Operation to Execute:**
  1. In Terminal, execute: `python scripts/preflight_check.py`
  2. Observe the 34-point diagnostic scorecard pass completely (0 WARN, 0 FAIL).
  3. In the browser, observe the React Clinician Workstation header showing the green badge: `"Live Gateway Mode active (FastAPI at localhost:8000)"`.
* **Expected Result:** All 34 diagnostic probes pass with green `[PASS]` tags; Vite web workstation connects to backend port 8000.
* **How to Prove Authenticity:**
  - Terminal prints genuine runtime timestamps, Python 3.12 version, SQLite PRAGMA integrity check, and JWT secret redaction.
  - Browser DevTools Network tab shows `GET http://127.0.0.1:8000/api/v1/health` returning `HTTP 200 OK` with JSON `{"status": "healthy", "version": "3.0.0"}` in < 2ms.
* **Failure Contingency:** If a port is blocked, run `powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1` and re-run `python scripts/launch_demo.py --no-browser`.
* **Fallback:** Show archived preflight report in `logs/backend.log` and `da3_preflight_report.json`.

---

### Phase 3: Database Connectivity & Patient Cohort Inspection (Minute 2:30 – 3:30)
* **What to Open:** React Clinician Portal at `http://127.0.0.1:5173/`
* **Operation to Execute:**
  1. Log in with clinician credentials: `doctor@hospital.org` / `DoctorPassword123!`.
  2. Inspect the patient table displaying the Kaggle baseline cohort: `P101`, `P102`, `P103`, `P104`, `P105`.
  3. Click on Patient `P101` to open the dedicated clinical chart view (`http://127.0.0.1:5173/patients/P101`).
* **Expected Result:** Patient demographic profile loads with age, gender, assigned doctor, and historical vital recordings.
* **How to Prove Authenticity:**
  - Browser Network tab displays `GET /api/v1/patients/P101` returning HTTP 200 with JWT Bearer token in request headers.
  - Show the record in the local database:
    ```bash
    sqlite3 smart_health_local.db "SELECT patient_id, first_name, last_name, gender FROM patient_profiles WHERE patient_id='P101';"
    ```
    Output: `P101|Emma|Watson|Female`
* **Failure Contingency:** If web browser session expires, re-login or use Swagger UI at `http://127.0.0.1:8000/docs#/Patients/get_patient_api_v1_patients__patient_id__get`.
* **Fallback:** Show raw dataset file [`data/raw/kaggle_health_dataset.csv`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/data/raw/kaggle_health_dataset.csv).

---

### Phase 4: Safe MySQL CRUD on Designated Evaluation Records (Minute 3:30 – 5:00)
* **What to Open:** DA3 Evaluation Console at `http://127.0.0.1:5173/evaluation` $\to$ **Tab A: CRUD Operations**.
* **Operation to Execute:**
  1. **INSERT:** Select Patient `P101`, Record Type `clinical_note`, Title `"DA3 Live Evaluation Triage Note"`, Content `"Patient exhibiting normal baseline recovery."` Click **"Create Record"**.
     - Observe: Record created with ID `EVAL_NOTE_<hex>`, HTTP 201 Created.
  2. **RETRIEVE:** Enter the generated Record ID. Click **"Fetch Record"**.
     - Observe: Record details retrieved with full clinical metadata, HTTP 200 OK.
  3. **UPDATE:** Change Title to `"DA3 Live Evaluation Triage Note - VERIFIED BY EXAMINER"`. Click **"Update Record"**.
     - Observe: Updated title reflected immediately, HTTP 200 OK.
  4. **DELETE:** Click **"Delete Evaluation Record"**.
     - Observe: Success message returned, HTTP 200 OK.
  5. **VERIFY 404:** Click **"Fetch Record"** again on the deleted ID.
     - Observe: Returns `HTTP 404 Not Found` ("Evaluation record not found").
  6. **BASELINE PROTECTION GUARD:** In the Patient ID field, enter baseline patient `P001` or `P101` and attempt deletion.
     - Observe: Request is blocked with `HTTP 403 Forbidden` ("Core EHR patient baseline records are immutable").
* **Expected Result:** Complete 4-step CRUD lifecycle passes; baseline clinical data remains completely unmodified.
* **How to Prove Authenticity:**
  - Show the `evaluation_records` table in SQLite before and after:
    ```bash
    sqlite3 smart_health_local.db "SELECT record_id, patient_id, title FROM evaluation_records;"
    ```
  - Show `audit_logs` table recording the timestamped mutation events.
* **Failure Contingency:** If the frontend console encounters a network error, execute the verified Python script:
  `python scratch/verify_rehearsal_crud.py` directly in the terminal to demonstrate all 6 CRUD steps over REST.
* **Fallback:** Open [`services/api/routes/evaluation.py#L160-L240`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/services/api/routes/evaluation.py) and show the SQLAlchemy CRUD implementation.

---

### Phase 5: Multi-Table Joins, Nested Queries & Relational Views (Minute 5:00 – 6:30)
* **What to Open:** DA3 Evaluation Console at `http://127.0.0.1:5173/evaluation` $\to$ **Tab B: Advanced SQL & Tab C: Database Objects**.
* **Operation to Execute:**
  1. **Multi-Table JOIN:** In Tab B, select `"3-Table Join (Profiles ⋈ Vitals ⋈ Alerts)"`. Click **"Execute Query"**.
     - SQL Executed:
       ```sql
       SELECT p.patient_id, p.first_name, p.last_name, v.heart_rate, v.spo2, a.alert_type, a.severity
       FROM patient_profiles p
       JOIN patient_vitals v ON p.patient_id = v.patient_id
       LEFT JOIN clinical_alerts a ON p.patient_id = a.patient_id
       WHERE p.patient_id = 'P101' LIMIT 10;
       ```
  2. **Nested Subquery:** Select `"Nested Subquery (Vitals Above Patient Average)"`. Click **"Execute Query"**.
     - SQL Executed:
       ```sql
       SELECT vital_id, heart_rate, measured_at FROM patient_vitals
       WHERE patient_id = 'P101' AND heart_rate > (
           SELECT AVG(heart_rate) FROM patient_vitals WHERE patient_id = 'P101'
       ) LIMIT 10;
       ```
  3. **Relational View:** In Tab C, select View `v_latest_patient_vitals`. Click **"Query View"**.
     - Returns current vital signs for all patients computed from the underlying timeseries table.
  4. **Covering Index Execution Plan:** Select `"EXPLAIN Plan Comparison"`.
     - Demonstrates `SEARCH TABLE patient_vitals USING INDEX idx_vitals_patient_metric_time` (Covering B-Tree Index Scan) vs full table scan `SCAN TABLE patient_vitals`.
* **Expected Result:** Queries return formatted tabular results in < 5ms latency; EXPLAIN plan proves index scan.
* **How to Prove Authenticity:**
  - Console shows actual SQL statement, column headers, execution time, and raw SQLite query plan output.
* **Failure Contingency:** Query SQLite directly:
  ```bash
  sqlite3 smart_health_local.db "EXPLAIN QUERY PLAN SELECT * FROM patient_vitals WHERE patient_id='P101' ORDER BY measured_at DESC LIMIT 5;"
  ```
* **Fallback:** Refer to Section 1.7 of [`docs/submission/03_database_design.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/03_database_design.md).

---

### Phase 6: Stored Functions, Procedures & Triggers (Minute 6:30 – 7:30)
* **What to Open:** DA3 Evaluation Console at `http://127.0.0.1:5173/evaluation` $\to$ **Tab C: Database Objects**.
* **Operation to Execute:**
  1. **Stored Function (BMI Calculator):**
     - Enter `Height: 175 cm`, `Weight: 70 kg`. Click **"Calculate BMI"**.
     - Returns: `BMI = 22.86`, Category: `"Normal weight"`.
  2. **Stored Function (Fever Classifier):**
     - Enter `Temperature: 102.5 °F`. Click **"Classify Fever"**.
     - Returns: Category: `"High Fever"`.
  3. **Database Trigger Demonstration:**
     - Select an active alert for Patient `P101`.
     - Update alert status from `ACTIVE` to `ACKNOWLEDGED`.
     - Click **"Inspect Trigger History"**.
     - Shows newly inserted record in `alert_status_history` generated automatically by database trigger `trg_alert_status_history_after_update`.
* **Expected Result:** Accurate mathematical computation; automatic trigger execution captures previous state, new state, and timestamp without application-level insert.
* **How to Prove Authenticity:**
  - Query SQLite trigger history table:
    ```bash
    sqlite3 smart_health_local.db "SELECT history_id, alert_id, old_status, new_status, changed_at FROM alert_status_history ORDER BY changed_at DESC LIMIT 1;"
    ```
* **Failure Contingency:** Inspect trigger DDL in [`database/mysql/schema.sql#L465-L485`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mysql/schema.sql#L465-L485).
* **Fallback:** Explain SQLite trigger implementation vs MySQL 8 syntax from Chapter 3 of the project report.

---

### Phase 7: Read-Only MongoDB Atlas Analytics & Invariant (Minute 7:30 – 8:30)
* **What to Open:** DA3 Evaluation Console at `http://127.0.0.1:5173/evaluation` $\to$ **Tab D: MongoDB Cloud Analytics**.
* **Operation to Execute:**
  1. **Cloud Cluster Connectivity:**
     - Observe cluster endpoint: `cluster0.offnaie.mongodb.net` (MongoDB 7.0 Atlas Cloud).
     - Status: Connected with TLS encryption.
  2. **Strict Read-Only Invariant:**
     - Display total telemetry document count: **2,955 documents**.
     - Show lock indicator: `is_read_only_enforced: true`, `MONGODB_SYNC_ENABLED: false`.
  3. **Analytical Aggregation Pipeline:**
     - Select pipeline: `"Patient Vitals Summary (Hourly Bucket)"`. Click **"Run Aggregation"**.
     - Pipeline executed:
       ```javascript
       [
         { "$match": { "patient_id": "P101" } },
         { "$group": {
             "_id": "$patient_id",
             "avg_hr": { "$avg": "$heart_rate" },
             "min_hr": { "$min": "$heart_rate" },
             "max_hr": { "$max": "$heart_rate" },
             "avg_spo2": { "$avg": "$spo2" },
             "event_count": { "$sum": 1 }
         }},
         { "$project": { "_id": 1, "avg_hr": { "$round": ["$avg_hr", 1] }, "avg_spo2": { "$round": ["$avg_spo2", 1] }, "event_count": 1 } }
       ]
       ```
     - Observe: Returns real aggregated metrics in ~120ms cloud roundtrip. Document count remains invariant at 2,955.
* **Expected Result:** Live cloud query succeeds without mutating cloud data.
* **How to Prove Authenticity:**
  - Point to real cloud connection latency (~120ms network RTT).
  - Verify document count in terminal before and after:
    ```bash
    python -c "from database.mongodb.client import get_mongo_database, get_settings; print(get_mongo_database(get_settings())['telemetry_events'].count_documents({}))"
    ```
    Output: `2955`
* **Failure Contingency:** If internet connection drops, the console displays cached benchmark results with a clear `"Offline / Read-Only Fallback"` banner.
* **Fallback:** Open Section 2.5 of [`docs/submission/03_database_design.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/03_database_design.md).

---

### Phase 8: Dashboard Visualizations & Streamlit Analytics (Minute 8:30 – 9:30)
* **What to Open:** React Clinician Workstation (`http://127.0.0.1:5173/patients/P101`) and Streamlit Analytics Visualizer (`http://localhost:8501`).
* **Operation to Execute:**
  1. In the React dashboard, inspect the **Interactive Physiological Timeseries Chart**:
     - Dual-axis SVG rendering: Heart Rate (bpm) in red, SpO2 (%) in blue, Temperature (°F) in green.
     - Clinical threshold bands: Tachycardia (> 100 bpm), Bradycardia (< 60 bpm), Hypoxemia (< 95%).
     - Discontinuous gap detection: Polyline breaks when reading intervals exceed 20 minutes.
  2. Switch to the Streamlit window (`http://localhost:8501`):
     - View **SQL vs NoSQL Latency Benchmark**: Relational indexed lookup (1.2ms) vs Cloud MongoDB aggregation (120ms).
     - View **Population Risk Stratification**: Interactive cohort distribution histogram.
* **Expected Result:** Fluid, interactive visualizations render live data from both local relational and cloud NoSQL stores.
* **How to Prove Authenticity:**
  - Hover over SVG data points to show exact millisecond timestamps and physiological values.
  - Streamlit dashboard allows dynamic filtering by patient ID and metric type.
* **Failure Contingency:** If Streamlit is closed, open [`docs/submission/09_sql_vs_nosql_benchmark_report.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/09_sql_vs_nosql_benchmark_report.md).
* **Fallback:** Use the built-in React chart workstation which operates independently.

---

### Phase 9: Authentication, Authorization & Security Boundaries (Minute 9:30 – 10:30)
* **What to Open:** DA3 Evaluation Console at `http://127.0.0.1:5173/evaluation` $\to$ **Tab E: Live Challenge Mode**.
* **Operation to Execute:**
  1. Execute the 7 automated security challenge probes:
     - `authorized_read`: Valid Clinician JWT token $\to$ `HTTP 200 OK (PERMITTED)`.
     - `denied_unassigned_patient`: Clinician accessing unassigned patient profile $\to$ `HTTP 403 Forbidden (DENIED)`.
     - `denied_baseline_delete`: Attempting to delete patient `P001` $\to$ `HTTP 403 Forbidden (DENIED)`.
     - `invalid_reading_range`: Ingesting `heart_rate: 999.0` (out-of-bounds) $\to$ `HTTP 422 Unprocessable Entity (VALIDATION_FAILED)`.
     - `duplicate_event_rejection`: Re-submitting identical `event_id` $\to$ `HTTP 409 Conflict (CONFLICT_HANDLED)`.
     - `missing_record_lookup`: Requesting non-existent record ID $\to$ `HTTP 404 Not Found (NOT_FOUND)`.
     - `unauthenticated_request`: Requesting protected route without Bearer token $\to$ `HTTP 401 Unauthorized (DENIED)`.
* **Expected Result:** All 7 security probes return exact expected HTTP status codes with sanitized error payloads.
* **How to Prove Authenticity:**
  - Show the response status code, latency, and sanitized clinical message in the challenge results table.
* **Failure Contingency:** Execute terminal test:
  `python -m pytest tests/unit/test_security.py -q`
* **Fallback:** Show [`backend/app/core/security.py`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/backend/app/core/security.py) and [`database/mysql/provision_least_privilege_users.sql`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mysql/provision_least_privilege_users.sql).

---

### Phase 10: Automated Test Evidence & Benchmark Scorecard (Minute 10:30 – 11:30)
* **What to Open:** DA3 Evaluation Console at `http://127.0.0.1:5173/evaluation` $\to$ **Tab F: Test Runner Evidence**.
* **Operation to Execute:**
  1. Click **"Run Automated DA3 Test Suite"**.
  2. Observe live test execution across all 6 academic categories:
     - Category A: Relational Models & Schemas (12 assertions) $\to$ `PASS`
     - Category B: SQL Joins, Nested Queries & Aggregates (15 assertions) $\to$ `PASS`
     - Category C: Database Objects (Views, Trigger, Stored Routines) (10 assertions) $\to$ `PASS`
     - Category D: Read-Only MongoDB Atlas Analytics (10 assertions) $\to$ `PASS`
     - Category E: Security, RBAC & Safe Invariant Guards (12 assertions) $\to$ `PASS`
     - Category F: Live Microservices & Demonstration Workflow (15 assertions) $\to$ `PASS`
  3. Total Score: **74 / 74 Assertions Passed (100.0%)** in ~3.5 seconds.
* **Expected Result:** Full green test matrix with 100% pass rate; zero assertions skipped or failed.
* **How to Prove Authenticity:**
  - Show the generated test report file [`da3_test_evidence_report.json`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/da3_test_evidence_report.json) with execution timestamps.
* **Failure Contingency:** Execute test runner via terminal: `python scripts/run_da3_tests.py --quick`.
* **Fallback:** Open [`docs/submission/08_test_and_verification_report.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/08_test_and_verification_report.md).

---

### Phase 11: Smartwatch Simulator Start, Stop & Resume (Minute 11:30 – 12:30)
* **What to Open:** React Clinician Portal Header (`http://127.0.0.1:5173/`) and Simulator Status endpoint `http://127.0.0.1:8001/api/v1/simulator/status`.
* **Operation to Execute:**
  1. **START:** In the top header bar, click **"Start Telemetry"**.
     - Observe: Header badge changes to `"Streaming (1 Hz)"`. Fresh readings stream into the patient charts.
     - Event ID increments: `evt_sim_2536_ea5d9577`.
  2. **STOP:** Click **"Stop Telemetry"**.
     - Observe: Generation halts immediately. Simulator state changes to `STOPPED`.
     - Confirm: No additional events arrive after Stop completes (P101 event ID remains static).
  3. **CONTINUED NORMAL APPLICATION USE:** While the simulator is stopped, navigate to the Patients tab, view medical history, acknowledge an alert, and run an evaluation query.
     - Demonstrates that core clinical EHR operations remain 100% operational and are completely decoupled from synthetic generation.
  4. **RESUME:** Click **"Resume Telemetry"**.
     - Observe: Streaming resumes immediately with new sequential event IDs (`evt_sim_2541_c240ec84`) without restarting the backend gateway or web server.
  5. **CLEAN STOP:** Click **"Stop Telemetry"** to restore clean stopped baseline.
* **Expected Result:** Flawless start $\to$ stop $\to$ normal use $\to$ resume $\to$ stop lifecycle.
* **How to Prove Authenticity:**
  - DevTools Network tab shows `POST /api/v1/simulator/start` and `POST /api/v1/simulator/stop` returning HTTP 200 with JSON payload `{"is_running": true/false, "lifecycle_state": "RUNNING/STOPPED"}`.
* **Failure Contingency:** Run Python verification script:
  `python scratch/verify_rehearsal_simulator.py`
* **Fallback:** Explain the microservice decoupling architecture from Section 4 of [`docs/submission/02_system_architecture.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/02_system_architecture.md).

---

### Phase 12: Viva Conclusion & Transparent Scope Disclosure (Minute 12:30 – 13:00)
* **What to Open:** Slide 20 in [`docs/submission/Smart_Health_Monitoring_DA3_Presentation.pptx`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/Smart_Health_Monitoring_DA3_Presentation.pptx) or Section 4 of [`docs/submission/01_project_overview.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/01_project_overview.md).
* **Operation to Execute:**
  1. Summarize key technical achievements:
     - Relational EHR core normalized to BCNF with strict referential integrity.
     - Hybrid MongoDB Atlas pipeline providing high-throughput raw telemetry analytics.
     - Integrated unsupervised Isolation Forest model (38 features) for real-time anomaly detection.
     - Dual-mode Clinician Workstation with WebSocket streaming and automated test runner.
  2. State transparent academic boundaries:
     - Mobile App Scope: Native Flutter app is documented as external/planned scope; telemetry ingestion is demonstrated via CSV replay and authenticated REST endpoints.
     - Screenshot Assets: 7 UI screenshots captured from live session for final PDF report printing.
* **Expected Result:** Examiner recognizes technical maturity, rigorous verification, and academic integrity.
* **How to Prove Authenticity:**
  - Invite examiner questions on any topic: Normalization proofs, ACID vs BASE, Index Structures, or Machine Learning baselines. All covered in [`docs/submission/13_project_presentation_and_viva_guide.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/13_project_presentation_and_viva_guide.md).
* **Failure Contingency:** Use the Viva Q&A flashcards in Slide Deck Markdown (`docs/submission/presentation_slide_deck.md#examiner-qa-defense-cheat-sheet`).
* **Fallback:** Conclude with the Master Project Report summary.

---

## 3. Live Rehearsal Execution Evidence (2026-10-15 Rehearsal Run)

The timed demonstration sequence was rehearsed live on 2026-10-15. The exact execution outcomes are recorded below:

### 3.1 Preflight Diagnostic Verification Run
* **Command:** `python scripts/preflight_check.py`
* **Execution Timestamp:** `2026-10-15 05:25:47 UTC`
* **Scorecard:** Total Checks: **34** | Passed: **34** | Warn: **0** | Failed: **0** (100.0%)
* **Verdict:** `SYSTEM IS CERTIFIED READY FOR LIVE DEMONSTRATION`

### 3.2 12-Point Live Demonstration Workflow Acceptance
* **Command:** `python scripts/validate_da3_demo_workflow.py`
* **Report ID:** `workflow-eval-1792041957`
* **Total Duration:** 3,301.44 ms (3.30 seconds)
* **Scorecard:** Steps Passed: **12 / 12 (100.0%)**

| Step | Name | Duration | Measured Outcome | Status |
| :-: | :--- | :-: | :--- | :-: |
| 1 | Backend Startup & Health Probe | 130.8 ms | Gateway HTTP 200, Relational DB connected | `PASS` |
| 2 | Dashboard Connectivity | 20.4 ms | React UI HTTP 200, Streamlit HTTP 200 | `PASS` |
| 3 | MySQL Evaluation CRUD Lifecycle | 133.6 ms | Create 201, Read 200, Update 200, Delete 200, 404 verified, Guard 403 | `PASS` |
| 4 | SQL Queries & EXPLAIN Plan | 61.6 ms | 5 named queries, Index `idx_vitals_patient_metric_time` | `PASS` |
| 5 | Read-Only MongoDB Inspection | 616.9 ms | Cloud Atlas connected, Read-Only enforced, 2,955 docs | `PASS` |
| 6 | Security Controls & Error Probes | 55.1 ms | 7/7 probes passed (200, 401, 403, 409, 422, 404) | `PASS` |
| 7 | ML Inference & Alert Triggering | 35.2 ms | Telemetry ingestion (HR=138), Alert triggered, View active | `PASS` |
| 8 | Simulator Start Lifecycle | 14.9 ms | POST /start $\to$ `is_running: True, state: RUNNING` | `PASS` |
| 9 | Simulator Stop Lifecycle | 31.3 ms | POST /stop $\to$ `is_running: False, state: STOPPED` | `PASS` |
| 10 | Continued Application Use After Stop | 33.6 ms | Gateway healthy, 5 patients accessible, alerts active | `PASS` |
| 11 | Simulator Resume Without Restart | 57.0 ms | Resumed generation, clean post-test stop | `PASS` |
| 12 | Frontend Build & Regression Tests | 370.1 ms | 28/28 frontend assertions passed, bundle verified | `PASS` |

### 3.3 CRUD Repeatability & Invariant Verification
* **Test Script:** `python scratch/verify_rehearsal_crud.py`
* **Outcomes:**
  - Initial evaluation records: 2
  - Record Created: `EVAL_NOTE_C40C6013` (HTTP 201)
  - Record Retrieved: `EVAL_NOTE_C40C6013` (HTTP 200)
  - Record Updated: `"Rehearsal Check Note - UPDATED FOR PROFESSOR"` (HTTP 200)
  - Record Deleted: Status HTTP 200
  - Re-fetch Verification: `HTTP 404 Not Found`
  - Baseline Patient Protection: Attempting to delete `P001` rejected with `HTTP 403 Forbidden`
  - Final evaluation records: 2 (Baseline count perfectly preserved)

### 3.4 Simulator Controls Rehearsal
* **Test Script:** `python scratch/verify_rehearsal_simulator.py`
* **Outcomes:**
  - Simulator Start: `HTTP 200`, event generated (`evt_sim_2536_ea5d9577`, HR=71.5 bpm)
  - Simulator Stop: `HTTP 200`, `state: STOPPED`
  - Generation Halting: Event ID before pause (`evt_sim_2536_ea5d9577`) identical to event ID after 2s pause (`evt_sim_2536_ea5d9577`) $\to$ Generation halted immediately.
  - Normal Application Operations: Authenticated clinician fetched 5 patients and 50 alerts while simulator was stopped.
  - Simulator Resume: `HTTP 200`, new sequential event generated (`evt_sim_2541_c240ec84`) without restarting backend or frontend.
  - Clean Post-Rehearsal Stop: `HTTP 200`, `is_running: False`.

### 3.5 Database Invariant Check
* **MongoDB Atlas Document Count:** Exactly **2,955 documents** in `smart_health.telemetry_events`. Zero mutations detected.
* **MySQL Baseline Cohorts:** Cohorts `P001`–`P005` and `P101`–`P105` intact and unmodified.

---

## 4. Comprehensive Failure Contingency Matrix

| Failure Mode | Symptoms | Root Cause | Immediate Remediation (Live Fix) | Fallback Procedure (No Falsified Success) |
| :--- | :--- | :--- | :--- | :--- |
| **Backend Gateway Offline (:8000)** | UI displays red connection pill; API calls return `HTTP 0` or `WinError 10061`. | Process crashed or port conflict. | Run: `python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000` | Demonstrate database schemas, triggers, and BCNF normalization proofs directly via SQLite CLI: `sqlite3 smart_health_local.db`. |
| **Relational DB Connectivity Failure** | `/health/ready` returns `database: disconnected`. | Database lock or file permission issue. | Check file locks on `smart_health_local.db`. Restart backend gateway. | Query schema definitions and DDL scripts directly from [`database/mysql/schema.sql`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mysql/schema.sql). |
| **Frontend UI Unreachable (:5173)** | Browser displays "Site cannot be reached" or connection refused. | Vite dev server stopped. | In `frontend/apps/doctor_web`, run: `cmd.exe /c npx vite --host 127.0.0.1 --port 5173` | Demonstrate all clinical and evaluation endpoints directly via interactive Swagger documentation: `http://127.0.0.1:8000/docs`. |
| **WebSocket Stream Disconnected** | Vitals chart stops animating; "WS Disconnected" badge displayed. | Browser dropped WebSocket or token expired. | Click "Reconnect WebSocket" or refresh browser page (`Ctrl + F5`). | Demonstrate REST polling mode: Vitals are fetched every 5 seconds over standard HTTP REST. |
| **ML Model Loading Failure** | Anomaly scores return null; log displays `model.joblib not found`. | Serialized model file path error. | Verify `models/iforest_v1/model.joblib` exists (1,149,449 bytes). | System automatically falls back to rule-based clinical heuristic triage (tachycardia > 100, hypoxemia < 95). Transparently explain rule-based fallback. |
| **Simulator Control Failure (:8001)** | Start/Stop buttons return 500 or timeout. | Simulator microservice port hung. | Terminate PID on port 8001 and restart: `python -m uvicorn simulator.main:app --host 127.0.0.1 --port 8001` | Use manual single-reading injection in the Evaluation Console (Tab A) to feed clinical vitals. |
| **Streamlit Dashboard Offline (:8501)** | Streamlit window fails to open or returns 404. | Optional analytics daemon not launched. | Run: `python -m streamlit run dashboard/app.py --server.port 8501` | **Non-blocking optional service.** Point examiner to pre-compiled benchmarks in [`docs/submission/09_sql_vs_nosql_benchmark_report.md`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/09_sql_vs_nosql_benchmark_report.md). |
| **MongoDB Atlas Internet Outage** | Tab D shows "Connection timed out" or DNS failure. | Campus Wi-Fi blocks outbound cloud MongoDB port 27017. | Switch to mobile hotspot or tethered connection. | **Do not claim cloud connection.** Show cached benchmark comparisons and the verified local SQLite relational implementation. Point to Category D passing tests in [`da3_test_evidence_report.json`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/da3_test_evidence_report.json). |

---

## 5. Remaining Presentation Blockers & Readiness Verdict

* **P0 (Presentation Blockers):** **ZERO (0).** All microservices, routes, database objects, and tests are verified and functional.
* **P1 (Required Submission Gap):** **ONE (1).** Capture 7 physical PNG screenshots from the live web workstation and place in `docs/screenshots/` prior to printing the final PDF submission binder.
* **P2 (Planned External Scope):** **ONE (1).** Native Flutter mobile application is truthfully disclosed as planned/external scope. Telemetry ingestion is fully demonstrated via CSV replay and authenticated REST endpoints.

**FINAL REHEARSAL VERDICT:** **READY FOR EVALUATION. PROCEED WITH 12-MINUTE TIMED PRESENTATION.**
