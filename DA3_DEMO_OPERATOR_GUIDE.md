# DA3 Live Demonstration Operator Guide & Quick-Reference Runbook

**Project:** AI-Powered Smart Health Monitoring System  
**Academic Milestone:** Digital Assignment 3 (DA3) Live Evaluation & Technical Defense  
**Authoritative UI Portal:** `http://localhost:5173/evaluation` (DA3 Live Database Evaluation Console)  
**System Version:** `3.0.0-final`  
**Database Protection Status:**  
* **MongoDB Atlas Cloud:** Strictly READ-ONLY (2,955 Invariant Documents, Zero Mutations)  
* **Relational Database:** Protected Baseline Cohorts (`P001`–`P005` & `P101`–`P105` Deletion Blocked)  
* **Safe Write Fixtures:** Confined to `evaluation_records` table and `EVAL_*` test IDs  

---

## 1. Pre-Demonstration Setup & Preflight Diagnostics

Before presenting to the professor or evaluation committee, execute the following 2-minute setup protocol:

### 1.1 Automated Preflight Verification (Terminal)
Open a PowerShell or Command Prompt window in the project root and run:
```powershell
python scripts/preflight_check.py
```
* **Expected Result:** All **34 / 34 checks PASS** (0 WARN, 0 FAIL).
* **What This Proves:**
  - Python (>= 3.10) and Node runtimes verified.
  - Environment variables defined with secrets redacted.
  - `smart_health_local.db` contains 18 tables, 2 views, and active trigger `trg_alert_status_history_after_update`.
  - Machine learning Isolation Forest model (`model.joblib`, 38 features) loaded.
  - Ports :8000, :8001, :5173, and :8501 responsive.
  - MongoDB Atlas read-only invariant (2,955 documents) confirmed.

### 1.2 Microservice Launching (If not already running as daemons)
```powershell
# Option A: One-click script
scripts\start_all.bat

# Option B: Individual terminal commands
python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000        # FastAPI Gateway
python -m uvicorn simulator.main:app --host 127.0.0.1 --port 8001           # Smartwatch Simulator
cd frontend\apps\doctor_web && npm run dev                                   # Clinician Workstation (:5173)
python -m streamlit run dashboard/app.py --server.port 8501                 # Analytics Dashboard
```

### 1.3 Browser Workstation URLs
Open the following tabs in Google Chrome or Microsoft Edge:
1. **Primary Evaluation Console:** `http://localhost:5173/evaluation`
2. **Clinician Patient Workstation:** `http://localhost:5173`
3. **Interactive Swagger API Docs:** `http://localhost:8000/docs`
4. **Streamlit Analytics Visualizer:** `http://localhost:8501`

---

## 2. Step-by-Step Live Demonstration Protocol (12-Minute Sequence)

### Station 1: Problem Statement & Architecture (Minute 0:00 – 1:30)
* **Action:** Present Slide 1–5 of [`docs/submission/Smart_Health_Monitoring_DA3_Presentation.pptx`](docs/submission/Smart_Health_Monitoring_DA3_Presentation.pptx) or open [`docs/submission/02_system_architecture.md`](docs/submission/02_system_architecture.md).
* **Talking Points:**
  1. *Clinical Dilemma:* High-frequency smartwatch telemetry (1 Hz) floods transactional relational databases.
  2. *Dual Polyglot Persistence:*
     - **MySQL 8 InnoDB / SQLite:** Strictly ACID-compliant operational EHR for patient profiles, medical history, clinical alerts, role permissions, and auditable notes (17 authoritative tables in 3NF/BCNF).
     - **MongoDB Atlas Cloud:** Schema-less document store for timeseries telemetry events (`telemetry_events`) and multi-stage population aggregations.
  3. *Isolation Forest ML:* Real-time unsupervised anomaly scoring using 38 engineered physiological features with personal baseline drift adjustment.

---

### Station 2: Relational CRUD & Baseline EHR Protection Guard (Minute 1:30 – 3:30)
* **Location:** `http://localhost:5173/evaluation` $\to$ Tab 1: **CRUD Operations**
* **Demonstration Sequence:**
  1. **INSERT:** Select Patient `P101`, Title `Tachycardia Triage Note`, Type `consultation_note`. Click **Execute INSERT Transaction**.
     - *Observation:* Row inserted into `evaluation_records` table (`EVAL_NOTE_*`); audit record inserted into `audit_logs`. Execution time: ~0.6 ms.
  2. **READ:** View the new record rendered in the active records table.
  3. **UPDATE:** Modify content to `Patient vitals stabilized following metoprolol administration`. Click **Update Record**.
     - *Observation:* Content updated; status transitions to `UPDATED`. Execution time: ~0.4 ms.
  4. **CRITICAL SECURITY DEMONSTRATION (Baseline Deletion Guard):**
     - Click **Attempt Protected Deletion (P001)**.
     - *Observation:* The backend immediately intercepts the request and returns **HTTP 403 Forbidden**:
       > `Protected Baseline Record: Cannot delete baseline EHR patient record P001. Only designated evaluation fixtures starting with EVAL_ can be deleted.`
     - *Academic Impact:* Demonstrates server-side transactional safety; the examiner sees that baseline EHR data is strictly immutable.
  5. **DELETE:** Click **Delete** next to the newly created `EVAL_NOTE_*`.
     - *Observation:* Test record is safely removed from the database with non-repudiation logging. Execution time: ~0.9 ms.

---

### Station 3: Advanced SQL Queries & Covering Indexes (Minute 3:30 – 5:30)
* **Location:** `http://localhost:5173/evaluation` $\to$ Tab 2: **Named SQL Demos**
* **Demonstration Sequence:**
  1. **2-Table INNER JOIN:** Select `Two-Table Inner Join (patient_profiles + vitals_readings)`. Click **Execute Query**.
     - *Observation:* Demographics joined with physiological observations on `patient_id`. Execution time: ~0.08 ms.
  2. **Multi-Table Relational JOIN:** Select `5-Table Multi-Table Join`. Click **Execute Query**.
     - *Observation:* Joins `alerts`, `patient_profiles`, `doctor_patient_assignments`, `doctor_profiles`, and `users` to display assigned clinician, alert severity, and clinical triage status. Execution time: ~0.26 ms.
  3. **Nested Window Query (CTE):** Select `Nested Window Subquery (CTE)`. Click **Execute Query**.
     - *Observation:* Executes `WITH ranked_vitals AS (SELECT ..., ROW_NUMBER() OVER (PARTITION BY metric_code ORDER BY measured_at DESC))` to retrieve the latest vitals per metric code. Execution time: ~4.7 ms.
  4. **Aggregates with HAVING:** Select `GROUP BY with HAVING Clause`. Click **Execute Query**.
     - *Observation:* Computes `COUNT(*)`, `AVG(value)`, `MIN(value)`, `MAX(value)` grouped by patient, filtering cohorts having $> 5$ observations. Execution time: ~2.3 ms.
  5. **EXPLAIN Query Plan (Index Optimization):**
     - Switch to Tab 4: **Explain Plan**.
     - Click **Run EXPLAIN Comparison**.
     - *Observation:* Displays `SEARCH TABLE vitals_readings USING INDEX idx_vitals_patient_metric_time` (0.03 ms) vs unindexed full table scan (4.75 ms). 150x performance acceleration.

---

### Station 4: Relational Views, Stored Routines & Triggers (Minute 5:30 – 7:30)
* **Location:** `http://localhost:5173/evaluation` $\to$ Tab 3: **Database Objects**
* **Demonstration Sequence:**
  1. **Relational Views:**
     - Query `v_latest_patient_vitals`: Displays pre-compiled latest physiological values for patient `P101`. Execution time: ~0.68 ms.
     - Query `v_patient_active_alerts`: Displays unresolved alerts linked to patient demographics and assigned clinician. Execution time: ~0.26 ms.
  2. **Stored Functions:**
     - Test `fn_calculate_bmi` (Weight: 70 kg, Height: 1.75 m) $\to$ Returns `22.86` (Normal).
     - Test `fn_calculate_fever_category` (Temp: 38.8 °C) $\to$ Returns `High Fever`.
  3. **Stored Procedure (`sp_safe_patient_discharge` with ACID Rollback):**
     - Execute discharge for patient with active CRITICAL alerts.
     - *Observation:* The procedure rolls back to savepoint and returns:
       > `Cannot discharge patient with active CRITICAL or HIGH alerts.`
  4. **Database Trigger (`trg_alert_status_history_after_update`):**
     - Update alert status from `ACTIVE` to `ACKNOWLEDGED`.
     - Inspect the audit table `alert_status_history`.
     - *Observation:* A new history row with `old_status='ACTIVE'`, `new_status='ACKNOWLEDGED'`, and an exact UTC timestamp is automatically created by the database engine.

---

### Station 5: MongoDB Atlas Cloud Analytics (Minute 7:30 – 9:00)
* **Location:** `http://localhost:5173/evaluation` $\to$ Tab 5: **MongoDB Analytics**
* **Demonstration Sequence:**
  1. **Cloud Connection & Invariant Inspection:**
     - Displays connection to `cluster0.offnaie.mongodb.net` with TLS encryption.
     - **Document Count:** Exactly **2,955 invariant documents**. Zero writes detected.
  2. **Read-Only Document Retrieval:**
     - Query telemetry events for patient `P101` with projection excluding `_id`. Returns BSON documents in ~64 ms.
  3. **Multi-Stage Aggregation Pipeline:**
     - Select `Hourly Vital Averages Pipeline`. Click **Execute Aggregation**.
     - *Observation:* Executes `$match` $\to$ `$project` $\to$ `$group` $\to$ `$sort` pipeline computing hourly statistical moments across 2,955 events in ~52.7 ms. Zero write-producing stages (`$out`, `$merge`) are permitted.
  4. **Index Inspection:**
     - Shows registered compound index `{ patient_id: 1, measured_at: -1 }`.
     - Shows `.explain("executionStats")` utilizing `IXSCAN` (37x faster than `COLLSCAN`).

---

### Station 6: Live Challenge Mode & Automated Test Runner (Minute 9:00 – 11:00)
* **Location:** `http://localhost:5173/evaluation`
* **Demonstration Sequence:**
  1. **Tab 10: Challenge Mode (Instant Examiner Q&A Response):**
     - Select category `SQL Challenges` $\to$ Choose `sql_select_patient_readings` or `sql_demonstrate_join`.
     - Click **Execute Challenge**.
     - Shows dynamic parameter schema, executed SQL, real milliseconds timing, and returned rows without manual typing.
  2. **Tab 9: Test Runner & Verification Evidence:**
     - Click **Execute Automated DA3 Test Suite**.
     - *Observation:* Real-time execution of all **74 test assertions** across Backend Integration (13), Backend Unit (6), Schema Unit (12), ML Unit (9), Frontend Vitest (28), and Live Microservices (6). All pass with green badges.

---

### Station 7: Smartwatch Simulator Lifecycle & Decoupled State (Minute 11:00 – 12:00)
* **Demonstration Sequence:**
  1. Open Terminal or execute via Challenge Mode: `sim_lifecycle_start_stop_resume`.
  2. Demonstrate that the simulator defaults to **`STOPPED`** on startup.
  3. Start simulator: Telemetry begins streaming to FastAPI gateway.
  4. Open Clinician Workstation: Observe live SVG charts updating in real time.
  5. Stop simulator: Observe clean transition to `STOPPED`.
  6. **Decoupled Operation:** Perform CRUD or query operations while simulator is STOPPED, proving the EHR database and clinician workstation operate independently without device streaming.

---

## 3. Emergency Troubleshooting & Fail-Safe Procedures

| Symptom | Cause | Rapid Recovery Action |
| :--- | :--- | :--- |
| **Port 8000 already in use** | Stray uvicorn process | Run: `Get-Process python \| Stop-Process -Force`<br>Relaunch backend: `python -m uvicorn services.api.main:app --port 8000` |
| **Port 5173 already in use** | Stray Vite process | Run: `Get-Process node \| Stop-Process -Force`<br>Relaunch: `cd frontend\apps\doctor_web && npm run dev` |
| **MongoDB Atlas query timeout** | Internet disconnection | Explain network partition architecture: Outbox queues transactions in SQLite `analytics_outbox`; show local relational queries and cached benchmark report in [`docs/evidence/performance_evidence.json`](docs/evidence/performance_evidence.json). |
| **Frontend displays connection banner** | Backend not started | Start backend on port 8000. Alternatively, toggle "Demo Mode" in the workstation header to demonstrate isolated Kaggle fixtures (`P101`–`P105`). |
| **Examiner requests raw SQL execution** | Examiner wants direct CLI | Open terminal: `sqlite3 smart_health_local.db` or execute pre-written scripts in [`database/da3_sqlite_demonstration_queries.sql`](database/da3_sqlite_demonstration_queries.sql). |

---

## 4. Key Metrics Quick Reference for Viva Voce

* **Relational Tables:** 18 tables in `smart_health_local.db` (17 production tables + 1 isolated `evaluation_records` fixture table).
* **Compiled Views:** 2 views (`v_latest_patient_vitals`, `v_patient_active_alerts`).
* **Active Triggers:** 1 trigger (`trg_alert_status_history_after_update`).
* **Stored Routines:** 3 procedures (`sp_acknowledge_alert`, `sp_evaluate_patient_alerts`, `sp_safe_patient_discharge`) and 2 functions (`fn_calculate_bmi`, `fn_calculate_fever_category`).
* **MongoDB Documents:** Exactly **2,955 invariant documents** in `smart_health_analytics.telemetry_events`.
* **Kaggle Baseline Data:** 1,500 historical rows across cohorts `P101`–`P105` and `P001`–`P005`.
* **ML Model:** Isolation Forest (unsupervised, 38 engineered physiological features, continuous score $\in [0, 1]$).
* **Automated Test Scorecard:** **74 / 74 assertions PASS (100%)**; **34 / 34 preflight checks PASS (100%)**.
