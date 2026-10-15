# DEMO SQL WORKBENCH DESIGN SPECIFICATION
**Environment:** Demo Mode Only  
**Target Database:** Isolated Local SQLite (`smart_health_local.db`) / MySQL 8.0 Dual-Compatible Schema  
**Status:** Design & Safety Specification (Pre-Implementation)  
**Security Level:** Read-Only MongoDB / Isolated Real-Time Engine  

---

## 1. Demo Data Boundary & Provenance

### 1.1 Data Boundary Taxonomy
The system maintains strict isolation between three data classifications:

| Classification | Provenance Source | Simulated Flag | Allowed Cohort | Storage Tables | Mutability via SQL Workbench |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Real-Time Streaming** | `smartwatch_simulator` | `is_simulated = 1` | `P001`–`P005` (or live) | `ingestion_events`, `vitals_readings` | **STRICTLY BLOCKED** (Read-Only via SELECT) |
| **Historical Baseline / Demo Seed** | `historical_import`, `manual_entry` | `is_simulated = 0` | `P001`–`P005`, `P101`–`P105` | `ingestion_events`, `vitals_readings` | **READ-ONLY** (`P001`–`P005`), Demo `P101`–`P105` guarded |
| **User-Created Demo Readings** | `self_added` | `is_simulated = 0` | `P101`–`P105` | `ingestion_events`, `vitals_readings` | **FULL CRUD** (Insert, Select, Update, Delete) |

### 1.2 Durable Identification & Schema Parity
- **Provenance Field:** `ingestion_events.source` (`VARCHAR(32)`).
- **Hardcoded Value:** `self_added`.
- **Primary & Foreign Keys:**
  - `ingestion_events.event_id`: Unique `VARCHAR(64)` UUIDv4 (e.g. `evt_demo_self_added_<uuid>`).
  - `ingestion_events.created_at`: Server timestamp (`DATETIME`, `CURRENT_TIMESTAMP`).
  - `vitals_readings.reading_id`: Autoincrement `INTEGER` primary key.
  - `vitals_readings.event_id`: Foreign key linked to `ingestion_events.event_id` with `ON DELETE CASCADE`.
- **Database Migration Assessment:**
  - **Verified Fact:** `ingestion_events.source` is currently defined as `VARCHAR(32) NOT NULL` in both [database/mysql/schema.sql](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/database/mysql/schema.sql) and [database/mysql/models.py](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/database/mysql/models.py). It has no restrictive ENUM constraint.
  - **Conclusion:** **No DDL table alteration or migration is required.** The existing schema natively supports `self_added` readings.
  - **Optional Index Migration:** An index on `(patient_id, source)` may be applied optionally to `smart_health_local.db` to accelerate filtering of `self_added` readings without altering production schemas.

---

## 2. SQL Interface Design

### 2.1 Interface Overview (Demo Mode Only)
The SQL Workbench will be mounted as a dedicated sub-view or tab within the existing Demo / Evaluation dashboard ([frontend/apps/doctor_web/src/pages/DA3EvaluationPage.tsx](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/frontend/apps/doctor_web/src/pages/DA3EvaluationPage.tsx)). It is accessible only when `isDemoMode === true` in [DevModeContext.tsx](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/frontend/apps/doctor_web/src/context/DevModeContext.tsx).

### 2.2 UI Components & Capabilities
1. **Environment Warning Banner:**
   `[DEMO MODE ONLY] Isolated SQL Workbench — Queries execute strictly against local demo database. MongoDB sync is disabled.`
2. **Multiline SQL Editor:**
   - Monospace font, line numbers, automatic indentation.
   - Shortcut: `Ctrl+Enter` / `Cmd+Enter` to execute.
3. **Control Actions:**
   - **Execute Button:** Submits query payload to backend.
   - **Clear Button:** Resets the editor and clears result state.
   - **Template Dropdown:** Instant pre-fills for standard demo operations:
     - `INSERT self_added Vital Reading`
     - `SELECT Recent Self-Added Readings`
     - `JOIN Vitals with Model Assessments & Alerts`
     - `AGGREGATE Average Heart Rate by Metric & Source`
     - `CREATE VIEW Demo Vitals Trajectory`
4. **Session Command History:**
   - Tracks executed queries in session memory.
   - Clickable history chips to restore previous queries.
5. **Execution Status & Telemetry:**
   - Badges: `SUCCESS (200 OK)` or `ERROR (400 Bad Request)`.
   - Execution timer: e.g. `12.4 ms`.
   - Rows affected: e.g. `1 row inserted (event_id: evt_...)`.
6. **Formatted Results Grid:**
   - Tabular presentation with column headers extracted dynamically from cursor metadata.
   - Visual highlighting: Rows where `source == 'self_added'` receive an emerald badge.
7. **ML Analysis Feedback Card:**
   - Appears immediately upon an `INSERT` statement into vitals readings.
   - Displays:
     - Extraction of 38 rolling statistical vitals features.
     - ML Model assessment: `normal` vs `anomaly` (with anomaly score, e.g. `0.842`).
     - Generated Alert status: `HIGH SEVERITY ALERT TRIGGERED` (if anomaly detected).
     - Direct button: `[View in Patient History Chart ->]` deep-linking to `/patients/P101`.

---

## 3. Strict Execution Restrictions & Security Policy

### 3.1 Architecture of Isolation
- **Connection Isolation:** The Workbench backend endpoint interacts strictly with the SQLite session factory in [database/mysql/session.py](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/database/mysql/session.py), pointing to `DATABASE_URL=sqlite:///./smart_health_local.db`.
- **MongoDB Airgap:** MongoDB client routes are bypassed entirely. Background sync is disabled via `MONGODB_SYNC_ENABLED=false`.

### 3.2 SQL Parser & AST Validation Policy
Arbitrary regex-only matching is insufficient. Validation uses structured tokenization and parsing (via Python's `sqlite3.complete_statement` and AST token decomposition):

```
                        User SQL Query
                              |
                              v
             +----------------------------------+
             |  Multi-Statement Guard: Reject   |
             |  if payload contains >1 statement|
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             |   Disallowed Command Blacklist   |
             |   - DROP DATABASE / DROP TABLE   |
             |   - ATTACH / DETACH DATABASE     |
             |   - LOAD_FILE / INTO OUTFILE     |
             |   - ALTER SYSTEM / SHUTDOWN      |
             |   - PRAGMA writable_schema / ... |
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             |    Protected Table Blacklist     |
             |    Reject writes to:             |
             |    - users, audit_log, alembic   |
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             |     Cohort Boundary Guard        |
             |  UPDATE/DELETE restricted to     |
             |  patient_id LIKE 'P10%'          |
             |  and source = 'self_added'       |
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             |    Enforce source='self_added'   |
             |    on INSERT into vitals         |
             +----------------------------------+
                              |
                              v
                 Execute in transaction_scope()
```

### 3.3 Statement Rules & Matrix
| Statement Type | Allowed? | Restrictions / Enforcements |
| :--- | :--- | :--- |
| `SELECT` | **Yes** | Permitted on all medical tables and views. Blocked on `users` (credential isolation). |
| `JOIN`, `GROUP BY`, `ORDER BY` | **Yes** | Fully permitted for analytics and reporting queries. |
| `CREATE VIEW` | **Yes** | Permitted if view name begins with `v_demo_` or does not conflict with core views. |
| `INSERT` | **Yes** | Mandatory rewrite/enforcement: `source='self_added'`, `is_simulated=0`. Cohort must be `P101`–`P105`. Triggers ML pipeline. |
| `UPDATE` | **Guarded** | Allowed ONLY where `source='self_added'` and `patient_id LIKE 'P10%'`. Modifying real-time records (`source='smartwatch_simulator'`) is strictly blocked. |
| `DELETE` | **Guarded** | Allowed ONLY where `source='self_added'` and `patient_id LIKE 'P10%'`. Real-time records and baseline cohorts (`P001`–`P005`) are protected. |
| `ATTACH` / `DETACH` | **NO** | Blocked (prevents external file leakage). |
| `DROP DATABASE` | **NO** | Blocked. |
| Multi-Statement `;` | **NO** | Payload must contain exactly 1 statement to eliminate SQL injection chaining. |

### 3.4 Broad Mutation Confirmation
For `UPDATE` or `DELETE` statements where the `WHERE` clause is absent or targets multiple records, the backend estimates rows affected before execution; the frontend renders a confirmation dialogue:
`"Warning: This statement will modify/delete multiple self_added records. Do you wish to proceed?"`

---

## 4. Health-Reading Validation Rules

When an `INSERT` statement targets `vitals_readings` (or composite `ingestion_events`), it must satisfy strict clinical domain rules before committing:

1. **Patient ID Validation:**
   - Must be present in `patient_profiles`.
   - Must belong to the demo cohort: `patient_id IN ('P101', 'P102', 'P103', 'P104', 'P105')`.
   - Inserting readings for real-time baseline cohorts (`P001`–`P005`) via SQL Workbench is rejected.
2. **Metric Code & Physiological Bounds:**
   - `heart_rate`: Range $[30.0, 250.0]$ bpm.
   - `spo2`: Range $[50.0, 100.0]$ %.
   - `temperature`: Range $[30.0, 45.0]^\circ\text{C}$ (or $[86.0, 113.0]^\circ\text{F}$).
   - `respiratory_rate`: Range $[6.0, 60.0]$ breaths/min.
   - `bp_systolic`: Range $[60.0, 260.0]$ mmHg.
   - `bp_diastolic`: Range $[40.0, 150.0]$ mmHg.
3. **Unit Preservation & Canonical Transformation:**
   - Ingested Fahrenheit temperatures (`unit='degF'`) are converted to Celsius for canonical `value` while preserving `raw_value` and `raw_unit='degF'` using [`VitalsService.convert_temperature`](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/services/vitals_service.py#L32).
4. **Timestamp Validation:**
   - `measured_at` must be valid ISO 8601 or standard SQL datetime format.
   - Must not exceed current server time by more than 5 minutes (prevents future timestamp poisoning).
5. **Durable Source Classification:**
   - The backend explicitly overrides or injects `source = 'self_added'` into `ingestion_events`.
   - Never trusts user-supplied `source` values that attempt to impersonate `'smartwatch_simulator'`.

---

## 5. ML Pipeline & History Integration

### 5.1 Trigger Invariants
- **Only successful `INSERT` statements** trigger the ML analysis workflow.
- `SELECT`, `JOIN`, aggregate queries, `CREATE VIEW`, and metadata queries **never** trigger ML inference.
- An `UPDATE` that modifies vital measurements (`value`, `measured_at`) on existing `self_added` readings will trigger reanalysis via [`MLService.assess_and_persist`](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/services/ml_service.py#L48).

### 5.2 Reusing the Existing Pipeline Components
The workbench directly invokes the established pipeline without duplicating inference logic:
1. **Extraction:** Queries 30-minute historical rolling window for the patient from `vitals_readings`.
2. **Feature Engineering:** Calls [`extract_vitals_features`](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/packages/health_analysis/features.py) to compute 38 rolling statistical features.
3. **Model Inference:** Passes feature vector to `models/iforest_v1/model.joblib` (Isolation Forest) via [`HealthAnalysisService.assess_reading`](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/packages/health_analysis/service.py#L51).
4. **Assessment Persistence:**
   - Inserts record into `model_assessments` (`assessment_id`, `event_id`, `patient_id`, `anomaly_score`, `result`).
5. **Alert Evaluation:**
   - If `result == 'anomaly'` or critical threshold breached, creates record in `alerts` (`category='anomaly'`, `severity='high'|'critical'`).

### 5.3 History Retrieval Integration
- The newly inserted `self_added` readings and their associated `model_assessments` are immediately returned by existing history endpoints:
  - `GET /api/v1/patients/{patient_id}/vitals`
  - `GET /api/v1/patients/{patient_id}/readings`
- When the clinician opens [PatientDetailPage.tsx](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/frontend/apps/doctor_web/src/pages/PatientDetailPage.tsx), the trajectory chart renders the `self_added` points seamlessly along with their anomaly badges.

---

## 6. Comprehensive Test Plan

| ID | Test Scenario | Execution Method | Expected Result |
| :--- | :--- | :--- | :--- |
| **T01** | `source='self_added'` tagging | Submit `INSERT INTO vitals_readings ...` omitting source or specifying `source='other'`. | `ingestion_events.source` is stored as `self_added`. `is_simulated` is 0. |
| **T02** | Valid vitals insertion | Insert valid HR (78), SpO2 (98), Temp (36.8) for `P101`. | Status 200, row inserted, `reading_id` returned. |
| **T03** | Invalid metric bounds rejection | Insert HR (350 bpm) or SpO2 (120%). | Status 400/422, clear validation error message, 0 rows inserted. |
| **T04** | Invalid cohort rejection | Insert reading for `P999` (non-existent) or `P001` (baseline). | Statement rejected, error indicating cohort boundary restriction. |
| **T05** | Standard SELECT & Filtering | `SELECT * FROM vitals_readings WHERE patient_id='P101' ORDER BY measured_at DESC LIMIT 5`. | Returns formatted JSON columns and rows array. |
| **T06** | UPDATE of `self_added` reading | `UPDATE vitals_readings SET value = 82 WHERE reading_id = <demo_id>`. | 1 row affected; re-triggers ML reanalysis. |
| **T07** | Blocked UPDATE on real-time data | `UPDATE vitals_readings SET value = 100 WHERE patient_id = 'P001'`. | Statement rejected with permission error; 0 rows modified. |
| **T08** | DELETE of `self_added` reading | `DELETE FROM vitals_readings WHERE reading_id = <demo_id>`. | 1 row deleted; cascade cleans up assessment if event removed. |
| **T09** | JOIN Query | `SELECT r.metric_code, r.value, a.result FROM vitals_readings r JOIN model_assessments a ON r.event_id = a.event_id`. | Successfully joins and outputs combined tabular result. |
| **T10** | Aggregates & GROUP BY | `SELECT metric_code, AVG(value), COUNT(*) FROM vitals_readings GROUP BY metric_code`. | Returns aggregate rows with computed metrics. |
| **T11** | CREATE VIEW & Query View | `CREATE VIEW v_demo_spo2 AS SELECT * FROM vitals_readings WHERE metric_code='spo2'`. Then `SELECT * FROM v_demo_spo2`. | View created and query returns filtered view rows. |
| **T12** | SQL Syntax Error Handling | `SELEC * FORM vitals_readings`. | Status 400, readable syntax error detailing token `SELEC`, backend remains healthy. |
| **T13** | Blocked Destructive DDL | `DROP DATABASE smart_health_local;` or `DROP TABLE users;`. | Blocked by SQL policy before execution; audit security log entry created. |
| **T14** | Blocked SQLite PRAGMA / ATTACH | `ATTACH DATABASE 'malicious.db' AS mal;` | Blocked by execution policy. |
| **T15** | Multi-Statement Injection | `SELECT 1; DELETE FROM vitals_readings;` | Blocked by multi-statement guard; neither statement executes. |
| **T16** | ML Execution Exactly Once | Insert 1 reading payload via SQL. | Verify in `model_assessments` that exactly 1 assessment row is created for the new `event_id`. |
| **T17** | ML Non-Invocation on SELECT | Execute 10 consecutive `SELECT` queries. | ML inference counter remains unchanged; no new assessments or alerts created. |
| **T18** | Persistence in History UI | Insert reading via Workbench, navigate to `/patients/P101`. | Reading appears in Vital-Sign Trajectory chart and vitals card; persists upon page refresh. |
| **T19** | Real-Time Mode Isolation Proof | Run smartwatch simulator streaming simultaneously while executing queries in Workbench. | Simulator stream maintains 1.0s interval on port 8001; `/ws/v1/updates` frames continue uninterrupted. |
| **T20** | Transaction Rollback on Error | Multi-row insert where 2nd row violates check constraint. | Entire transaction rolls back; 0 rows inserted from the batch. |

---

## 7. Implementation Deliverables & Architecture Plan

### 7.1 Files to Modify or Create

```
Smart-Health-Monitoring-System/
├── docs/
│   └── demo_sql_workbench_design.md           <-- THIS DESIGN DOCUMENT
├── services/
│   └── api/
│       └── routes/
│           └── evaluation.py                  <-- ADD POST /evaluation/workbench/execute
├── frontend/
│   └── apps/
│       └── doctor_web/
│           └── src/
│               ├── api/
│               │   └── client.ts              <-- ADD executeWorkbenchSql()
│               ├── features/
│               │   └── evaluation/
│               │       └── SqlWorkbenchTab.tsx <-- NEW: Interactive Workbench UI Component
│               └── pages/
│                   └── DA3EvaluationPage.tsx  <-- MOUNT SqlWorkbenchTab
```

### 7.2 Backend API Contract
**Endpoint:** `POST /api/v1/evaluation/workbench/execute`  
**Tags:** `["Evaluation & Demo"]`

#### Request Payload Schema:
```json
{
  "sql": "INSERT INTO vitals_readings (patient_id, metric_code, value, unit, measured_at) VALUES ('P101', 'heart_rate', 145.0, 'bpm', '2026-10-16 10:00:00')",
  "patient_id": "P101"
}
```

#### Response Payload Schema (Success):
```json
{
  "status": "success",
  "statement_type": "INSERT",
  "execution_time_ms": 14.8,
  "rows_affected": 1,
  "columns": ["event_id", "reading_id", "patient_id", "metric_code", "value", "unit", "source"],
  "rows": [
    ["evt_self_added_a1b2c3d4", 1501, "P101", "heart_rate", 145.0, "bpm", "self_added"]
  ],
  "ml_assessment": {
    "assessed": true,
    "event_id": "evt_self_added_a1b2c3d4",
    "anomaly_score": 0.892,
    "result": "anomaly",
    "alert_created": true,
    "alert_severity": "high",
    "message": "Elevated heart rate anomaly detected (145 bpm)"
  }
}
```

#### Response Payload Schema (Validation / Security Error):
```json
{
  "status": "error",
  "error_code": "SQL_SECURITY_VIOLATION",
  "detail": "Statement rejected: ATTACH DATABASE is prohibited in the Demo SQL Workbench."
}
```

---

## 8. Explicit Safety Guarantees & Proof of Isolation

### Guarantee 1: Real-Time Telemetry Path Invariant
- **Proof:**
  - Files `services/simulator/worker.py`, `services/simulator/ingestion_service.py`, `services/websocket/dispatcher.py`, and `frontend/.../LiveTelemetryPanel.tsx` will remain untouched.
  - The simulator microservice on port 8001 will run without interruption.
  - All real-time telemetry frames on `/ws/v1/updates` will continue carrying `source: "smartwatch_simulator"` and will not be mixed with `self_added` events.

### Guarantee 2: MongoDB Atlas Zero-Mutation Invariant
- **Proof:**
  - `MONGODB_SYNC_ENABLED=false` remains strictly enforced in `.env`.
  - The `outbox_service.py` worker process is idle and will not sync SQL Workbench operations to MongoDB Atlas.
  - Zero MongoDB write calls (`insert_one`, `update_one`, `bulk_write`) will exist in any evaluation route.
  - Verification via `python -c "from database.mongodb.client import get_mongo_database; ..."` will confirm document count invariance before and after SQL Workbench operations.

### Guarantee 3: Baseline Clinical Cohort Protection
- **Proof:**
  - Records for patients `P001`–`P005` in `patient_profiles` and historical records in `vitals_readings` are read-only to the Workbench.
  - The SQL validator rejects any `UPDATE` or `DELETE` where `patient_id NOT LIKE 'P10%'`.
  - All Workbench transactions are scoped to `smart_health_local.db` with automated rollback on constraint violations.

---

## 9. Implementation Status & Verification Evidence (Prompt 3 Backend Complete)

### 9.1 Backend Implementation Manifest
- **Execution Service:** [services/demo_sql_service.py](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/services/demo_sql_service.py) (Created)
- **API Schemas:** [services/api/schemas/evaluation.py](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/services/api/schemas/evaluation.py) (Updated with `SQLWorkbenchExecuteRequest`, `SQLWorkbenchExecuteResponse`, `MLAssessmentSummary`)
- **API Endpoint:** [services/api/routes/evaluation.py](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/services/api/routes/evaluation.py) (Mounted `POST /api/v1/evaluation/workbench/execute`)
- **Dependencies:** [requirements.txt](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/requirements.txt) (Added `sqlparse>=0.5.0`)
- **Backend Test Suite:** [tests/unit/test_demo_sql_service.py](file:///C:/Users/HARNOOR%20KANT/.gemini/antigravity/scratch/Smart-Health-Monitoring-System/tests/unit/test_demo_sql_service.py) (Created 17 test cases, 100% passing)

### 9.2 Verification Evidence Matrix
| Verification Target | Command / Probe | Outcome / Output | Status |
| :--- | :--- | :--- | :--- |
| **Unit Test Suite** | `pytest tests/unit/test_demo_sql_service.py` | 17 passed, 0 failed in 4.07s | **PASS** |
| **Workbench SELECT** | `POST /api/v1/evaluation/workbench/execute` | HTTP 200 OK — columns, rows returned | **PASS** |
| **Workbench INSERT** | `POST /api/v1/evaluation/workbench/execute` | HTTP 200 OK — assigned `self_added`, `is_simulated=False`, invoked ML assessment | **PASS** |
| **Clinical History Retrieval** | `GET /api/v1/patients/P101/readings` | HTTP 200 OK — newly inserted `self_added` reading returned at top of history | **PASS** |
| **Preflight Health Checks** | `python scripts/preflight_check.py` | 33 / 34 checks PASSED (1 non-blocking MongoDB disabled warning) | **PASS** |
| **MongoDB Invariant** | Probe `check_mongo_connectivity()` | `not_configured`, `MONGODB_SYNC_ENABLED=false`, 0 writes | **PASS** |
| **Real-Time Mode Invariant** | Simulator health check & controls | Simulator on port 8001 STOPPED baseline, controls intact | **PASS** |
