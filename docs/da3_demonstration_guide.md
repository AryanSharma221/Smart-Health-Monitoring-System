# DA3 Live Demonstration & Viva Defense Guide

**Project:** Smart Health Monitoring System  
**Academic Milestone:** Digital Assignment 3 (DA3) Evaluation  
**Evaluation Scope:** Relational (MySQL/SQLite) and NoSQL (MongoDB Atlas) Database Architectures, ACID Transactions, Indexing, Aggregation, Security, and Empirical Performance  
**Authoritative UI Portal:** `/evaluation` (DA3 Live Database Evaluation Console)  

---

## 1. Environment Verification & Startup

Ensure both backend services are active before presenting to the evaluation committee:

```powershell
# 1. Start FastAPI Gateway & Operational Relational Database (Port 8000)
python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000

# 2. Start Smartwatch Telemetry Simulator (Port 8001)
python -m uvicorn simulator.main:app --host 127.0.0.1 --port 8001

# 3. Start Clinician Workstation Web Application (Port 5173)
cd frontend/apps/doctor_web
npm run dev
```

Navigate to: `http://localhost:5173/evaluation` (or click **DA3 Evaluation** in the sidebar navigation).

---

## 2. Step-by-Step Viva Demonstration Walkthrough

### Station 1: Relational CRUD Operations & EHR Safety Guard
* **Location:** Tab `1. CRUD Operations`
* **Objective:** Prove full ACID CRUD operations without risking genuine clinical data.
* **Demonstration Steps:**
  1. **INSERT:** In "Insert Evaluation Record", select Patient `P101`, Title `Tachycardia Triage Note`, Content `Patient presented with HR 128 bpm following mild physical exertion`, Record Type `consultation_note`. Click **Execute INSERT Transaction**.
     * *Observation:* Notice record `EVAL_NOTE_<id>` appears in the table below, and an audit row is written to `audit_logs`.
  2. **READ:** In the "Evaluation Records" table, verify the new record is displayed with patient ID, timestamp, and metadata.
  3. **CONTROLLED TELEMETRY INGESTION:** Under "Controlled Reading Ingestion & Surveillance Trigger", input:
     * Heart Rate: `128.5` bpm
     * SpO2: `94.0` %
     * Temperature: `38.2` °C
     * Click **Ingest Telemetry Reading**.
     * *Observation:* Telemetry metrics are written to `ingestion_events` and `vitals_readings`. The clinical surveillance rule evaluates the threshold breach (HR > 100) and automatically creates a new `vital_threshold` alert.
  4. **DELETE SAFETY GUARD (Academic Highlight):** Click **Attempt Protected Deletion (P001)**.
     * *Observation:* The backend immediately rejects the operation with **HTTP 403 Forbidden**:
       > `Protected Baseline Record: Cannot delete baseline EHR patient record P001. Only designated evaluation fixtures starting with EVAL_ can be deleted.`
  5. **SAFE DELETE:** In the records table, click **Delete** next to the `EVAL_NOTE_*` created in Step 1.
     * *Observation:* Record is deleted, with non-repudiation audit logging.

---

### Station 2: Named SQL Demonstrations & Query Plans
* **Location:** Tab `2. Named SQL Demos`
* **Objective:** Demonstrate relational queries across 18 MySQL tables with parameterized server-side execution.
* **Demonstration Steps:**
  1. Select query `2. Two-Table Inner Join (patient_profiles + vitals_readings)`. Click **Execute Query**.
     * *Observation:* SQL syntax is displayed, execution time is ~0.4 ms, and patient demographics joined with telemetry observations are rendered.
  2. Select query `3. 5-Table Multi-Table Join`. Click **Execute Query**.
     * *Observation:* Joins `alerts`, `patient_profiles`, `doctor_patient_assignments`, `doctor_profiles`, and `users` to identify assigned clinician, alert severity, and clinical triage status.
  3. Select query `4. Nested Subquery / CTE`. Click **Execute Query**.
     * *Observation:* Executes `ROW_NUMBER() OVER (PARTITION BY metric_code ORDER BY measured_at DESC)` to isolate the single latest reading for each vital metric per patient.
  4. Select query `6. GROUP BY & HAVING`. Click **Execute Query**.
     * *Observation:* Evaluates `HAVING COUNT(*) > 5` across hourly grouped readings.
  5. Select query `7. LEFT OUTER JOIN`. Click **Execute Query**.
     * *Observation:* Demonstrates outer join cohort tally preserving patients with zero active alerts.

---

### Station 3: Relational Database Objects (Views, Stored Procs & Functions, Triggers)
* **Location:** Tab `3. Database Objects`
* **Objective:** Demonstrate encapsulation of business logic inside database objects.
* **Demonstration Steps:**
  1. **Relational Views:** Select `v_latest_patient_vitals` and click **Query View**.
     * *Observation:* Shows the compiled View DDL and live row values from the view.
  2. **Stored Functions:**
     * `calculate_bmi`: Enter Weight `78.5` kg, Height `1.75` m. Click **Execute calculate_bmi**.
       * *Result:* `25.63` — *Overweight (Pre-obese, Grade 1)* according to WHO classification.
     * `fever_category`: Enter Temp `38.6` °C. Click **Execute fever_category**.
       * *Result:* `High-Grade Pyrexia` with triage staging.
  3. **Stored Procedures & ACID Rollback:**
     * In "Procedure: safe_discharge", select Patient `P101` (who currently has an active tachycardia alert). Click **Execute Safe Discharge Procedure**.
       * *Result:* **ROLLED_BACK**:
         > `Safe discharge validation failed: patient P101 has 1 unresolved active alerts. Transaction rolled back.`
  4. **Database Triggers & Audit Log:**
     * Enter Alert ID `ALT_EVAL_01`. Click **Fire Trigger Test Update**.
     * Click **Inspect Audit Table**.
     * *Result:* Table displays rows written automatically by `trg_alert_status_history_after_update` recording Old Status (`NEW`), New Status (`ACKNOWLEDGED`), Actor ID, and Timestamp.

---

### Station 4: Indexing & Query Execution Plans (EXPLAIN)
* **Location:** Tab `4. Indexing & EXPLAIN Plans`
* **Objective:** Contrast index lookup complexity vs sequential table scanning in both relational and NoSQL engines.
* **Demonstration Steps:**
  1. **MySQL Covering B-Tree Index Scan:**
     * Select `Covering Index Scan (idx_vitals_patient_metric_time)`. Click **Generate SQL EXPLAIN**.
     * *Metrics:* 10 rows examined, 0.3 ms latency. B-Tree index scan.
  2. **MySQL Full Table Scan:**
     * Select `Full Table Scan`. Click **Generate SQL EXPLAIN**.
     * *Metrics:* Sequential scan examining all rows in table.
  3. **MongoDB Atlas Compound B-Tree Index Scan:**
     * Select `Indexed IXSCAN (idx_telemetry_patient_measured)`. Click **Execute collection.explain()**.
     * *Metrics:* Stage: `IXSCAN`, Index: `idx_telemetry_patient_measured`, Docs Examined: `10`, Keys Examined: `10`, Latency: `0.4 ms`.
  4. **MongoDB Atlas Full Collection Scan:**
     * Select `Unindexed COLLSCAN (Nested metrics.heart_rate)`. Click **Execute collection.explain()**.
     * *Metrics:* Stage: `COLLSCAN`, Docs Examined: `2,955` (every document in collection), Latency: `14.8 ms`.

---

### Station 5: MongoDB Atlas Read-Only Analytics & Non-Negotiable Safety
* **Location:** Tab `5. MongoDB Read-Only Analytics`
* **Objective:** Demonstrate cloud NoSQL aggregation pipelines while proving the strictly read-only security invariant.
* **Demonstration Steps:**
  1. **Strictly Read-Only Guarantee:** Point out the warning banner:
     * Gateway enforces `_assert_read_only_pipeline` which rejects `$out`, `$merge`, `$collMod`, etc. with HTTP 403 Forbidden.
     * Background sync is gated by `MONGODB_SYNC_ENABLED=false`.
  2. **Cloud Connectivity:** Verify Atlas endpoint (`cluster0.offnaie.mongodb.net`), latency, and 2,955 real documents.
  3. **Document Browser:** Select `telemetry_events` and click **Browse Documents**. Use pagination buttons (`Next 10`) to browse real nested JSON documents.
  4. **Composable Aggregation Pipelines:**
     * Select `1. Dataset Overview ($facet)`. Click **Run Pipeline**.
       * *Result:* Returns multi-faceted summary: total documents (2,955), date boundaries, patient distribution, and source breakdown (Kaggle CSV vs Smartwatch).
     * Select `2. Patient Statistical Moments ($group)`. Click **Run Pipeline**.
       * *Result:* Computes min, max, avg for heart rate, SpO2, and temperature with explicit `$isNumber` guards.
     * Select `4. Source Provenance Breakdown ($group)`. Click **Run Pipeline**.
       * *Result:* Groups 1,500 Kaggle CSV records vs 1,453 smartwatch simulator records.

---

### Station 6: Empirical Performance Benchmarks & Test Scorecard
* **Location:** Tab `6. Benchmarks & Scorecard`
* **Objective:** Present reproducible benchmark measurements from safe development test fixtures.
* **Demonstration Steps:**
  1. **Scorecard Review:**
     * Backend Test Suite: **381 / 381 Passing (100.0% Pass Rate)**
     * Frontend Client Test Suite: **28 / 28 Passing (100.0% Pass Rate)**
     * Consistency & Recovery Verdict: **ACID Invariants Verified**
  2. **7 Workload Latency Comparison:**
     * Workload A (Relational Index Read): 0.28 ms
     * Workload B (5-Table Join): 1.12 ms
     * Workload C (Transactional Write): 1.84 ms
     * Workload D (MongoDB B-Tree IXSCAN): 0.42 ms
     * Workload E (MongoDB Aggregation Pipeline): 4.25 ms
     * Workload F (MongoDB Unindexed COLLSCAN): 14.80 ms
     * Workload G (Outbox Queue Drain): 3.10 ms

---

### Station 7: Security Controls, Role-Based Access & Sanitized Errors
* **Location:** Tab `7. Security & Access Control`
* **Objective:** Prove role-based privilege boundaries, input range validation, and sanitized error responses without leaking credentials or stack traces.
* **Demonstration Steps:**
  1. **RBAC Privilege Matrix Review:**
     * Inspect the multi-tiered matrix showing access boundaries across `Doctor`, `Patient`, `Admin Operator`, and `Unauthenticated Guest`.
  2. **Reproducible Security Probes:**
     * Scenario 1: Select `1. Authorized Health Record Access (HTTP 200)` and click **Execute Security Scenario**.
       * *Result:* Returns patient demographics and telemetry summary with `outcome: PERMITTED` (HTTP 200).
     * Scenario 2: Select `2. RBAC Unauthorized Patient Access Denial (HTTP 403)` and click **Execute Security Scenario**.
       * *Result:* Returns `outcome: DENIED` (HTTP 403 Forbidden) demonstrating row-level assignment authorization protection.
     * Scenario 3: Select `3. Core EHR Immutability Guard (HTTP 403)` and click **Execute Security Scenario**.
       * *Result:* Returns `outcome: DENIED` (HTTP 403) proving genuine EHR records (`P001`) cannot be deleted via evaluation routes.
     * Scenario 4: Select `4. Telemetry Input Boundary Validation (HTTP 422)` and click **Execute Security Scenario**.
       * *Result:* Returns `outcome: VALIDATION_FAILED` (HTTP 422) showing Pydantic schema validation blocking invalid physiological telemetry (e.g. HR < 20 bpm).
     * Scenario 5: Select `5. Idempotency & Duplicate Prevention (HTTP 409)` and click **Execute Security Scenario**.
       * *Result:* Returns `outcome: CONFLICT_HANDLED` (HTTP 409) verifying duplicate event deduplication.
     * Scenario 6: Select `6. Sanitized Resource Lookup Error (HTTP 404)` and click **Execute Security Scenario**.
       * *Result:* Returns `outcome: NOT_FOUND` (HTTP 404) with clean JSON error payload and zero server stack trace leakage.
     * Scenario 7: Select `7. Unauthenticated Request Rejection (HTTP 401)` and click **Execute Security Scenario**.
       * *Result:* Returns `outcome: DENIED` (HTTP 401) verifying OAuth2 Bearer token enforcement.

---

### Station 8: 10-Point Live System Preflight Diagnostics
* **Location:** Tab `8. Preflight Diagnostics`
* **Objective:** Execute automated health audit across all databases and gateway routes.
* **Demonstration Steps:**
  1. Click **Re-run Diagnostics**.
  2. Observe the automated test table verify:
     1. Relational Database Connection (MySQL / SQLite)
     2. Relational Schema Integrity (18 tables present)
     3. Relational Views (`v_latest_patient_vitals`)
     4. Database Stored Objects & Triggers
     5. MongoDB Atlas Connectivity & Latency
     6. MongoDB Telemetry Events Document Count (2,955 docs)
     7. Outbox Synchronization Policy (Read-Only Safety Enforced)
     8. Machine Learning Isolation Forest Model
     9. Smartwatch Telemetry Simulator Port (8001)
     10. Clinician RBAC Security & Token Verification

---

### Station 9: Automated Live Test Runner & Academic Viva Verification Walkthrough
* **Location:** Tab `9. Test Runner & Evidence`
* **Objective:** Present empirical, live-executed test suite evidence directly within the evaluation console to substantiate that every system layer passes rigorous automated verification.
* **Demonstration Steps:**
  1. **Review Safety Invariants Status:**
     * Observe the top safety banner confirming:
       * **Atlas Status:** `Read-Only Guaranteed` — Telemetry events document count verified strictly invariant at **2,955 documents** (0 mutations).
       * **Core Cohort Guard:** `Active & Intact` — Verified baseline patients `P101`–`P105` and Kaggle cohort `P001`–`P005` present and protected.
  2. **Execute Test Suite from UI:**
     * Select **Quick Smoke Suite** (or **Backend Integration** / **Frontend UI**).
     * Click **Run Test Suite**.
     * *Observation:* The frontend triggers `POST /api/v1/evaluation/test-runner/run`. The backend executes the targeted test runner with safety pre/post assertions, streaming execution metrics into the console.
     * *Result:* Status displays `PASSED`, showing 100% pass rate, duration, and individual test cases.
  3. **Interactive Test Exploration & Filtering:**
     * Use the category chips to filter tests: **All**, **Backend Unit**, **Backend Integration**, **Frontend UI**, **Live Microservices**.
     * Type in the search box (e.g. `crud`, `join`, `rule`, `auth`) to instantly filter test cases.
     * Click on any individual test row (e.g. `test_demonstration_sql_named_queries`) to expand and inspect its test file path, execution parameters, and status.
  4. **CLI Test Execution (Command Prompt / PowerShell Verification):**
     * Switch to terminal to demonstrate the standalone CLI runner if requested:
       ```powershell
       powershell -ExecutionPolicy Bypass -File scripts\run_da3_tests.ps1 -Suite quick
       ```
       * *Result:* Validates pre-run invariants, executes 73 automated tests, validates post-run invariants, and generates `da3_test_evidence_report.json` with exit code 0.
  5. **12-Point Live Demonstration Workflow Acceptance Verification:**
     * Run the comprehensive live workflow acceptance validator:
       ```powershell
       python scripts\validate_da3_demo_workflow.py
       ```
       * *Result:* Passes all 12 live demonstration points across Gateway, React, Streamlit, Relational CRUD, SQL Queries, MongoDB Inspection, Security Denial, ML Alert Ingestion, and Simulator Lifecycle in ~2.7s.

---

## 3. Frequently Asked Viva Questions & Authoritative Answers

**Q1: Why does the system use both MySQL and MongoDB (Polyglot Persistence)?**  
*Answer:* Relational MySQL is the authoritative operational data store for strict ACID transactions, clinical foreign-key integrity, clinician assignment, and non-repudiation audit trails. MongoDB Atlas serves as a read-only historical analytics mirror, storing high-volume semi-structured telemetry documents without causing read lock contention on the relational OLTP engine.

**Q2: How is data consistency maintained between MySQL and MongoDB?**  
*Answer:* Via the Transactional Outbox Pattern. Telemetry readings are first committed to the relational database in an atomic transaction alongside an outbox event. The background synchronizer reads unpublished outbox records and idempotently mirrors them to MongoDB Atlas. Under our evaluation policy, writes to MongoDB are disabled (`MONGODB_SYNC_ENABLED=false`) to ensure strictly read-only evaluation.

**Q3: How do you prevent accidental deletion of patient health records during live evaluations?**  
*Answer:* The gateway implements an explicit evaluation safety guard: `DELETE /api/v1/evaluation/crud/records/{record_id}` strictly asserts `record_id.startswith("EVAL_")`. Attempting to delete any genuine patient record (e.g., `P001`–`P005` or `P101`–`P105`) is intercepted before database dispatch and rejected with `HTTP 403 Forbidden`.

**Q4: How do you prove that your test suite does not mutate production or cloud evaluation data?**  
*Answer:* Our custom DA3 test runner (`scripts/run_da3_tests.py`) runs invariant validation checks before and after every test suite execution. It asserts that MongoDB Atlas `telemetry_events` count remains unchanged at exactly 2,955, and queries the relational engine to verify the baseline patient cohorts `P001`–`P005` and `P101`–`P105` are intact. Furthermore, unit and integration suites run against in-memory or isolated test fixtures with strict mock wrappers around external mutation calls.

**Q5: How does the system handle secrets and credentials in automated test reports?**  
*Answer:* The test runner and evaluation endpoints pipe all logs, exception strings, and output messages through a rigorous secret-redaction filter (`sanitize_message`). It replaces MongoDB Atlas connection strings with masked URIs (`mongodb+srv://***:***@cluster0...`), strips authorization Bearer tokens, and masks database passwords. No plaintext credentials are ever written to JSON reports, UI responses, or terminal logs.

