# DA3 Analytics Audit and Implementation Planning Report

**Project:** AI-Powered Smart Health Monitoring System  
**Milestone:** Part 3A — DA3 Analytics Audit & Implementation Planning  
**Role:** Senior Data Engineer and Backend Architect  
**Status:** Audit & Architecture Planning Complete  
**Date:** 2026-10-14  

---

## Executive Summary

This audit assesses the state of the Smart Health Monitoring System codebase following the completion of Part 1 (Core Relational Architecture, Normalization, and Dataset Ingestion) and Part 2 (Security, Vitals API, Alert Lifecycle, Outbox Synchronization, WebSockets, Messaging, Integration Testing, and Production Packaging).

The primary objective of Part 3 is meeting the advanced Database Coursework (DA3) requirements:
1. **Relational Database Design & Implementation (MySQL):** Normalization (3NF), declarative constraints, transactions, stored procedures, stored functions, triggers, and views.
2. **Document Database Design & Implementation (MongoDB Atlas):** Schema design, embedding vs. referencing, secondary and compound indexes, and aggregation pipelines.
3. **Query Optimization & Execution Plans:** Index usage verification, `EXPLAIN` (MySQL) and `explain("executionStats")` (MongoDB), execution cost analysis, and scan elimination.
4. **Performance Benchmarking:** Rigorous empirical comparisons between SQL and NoSQL for point queries, time-series range scans, and multi-metric aggregations (measuring p50, p95, and p99 latencies).
5. **Interactive Analytics Visualization (Streamlit):** Multi-page clinical and operational dashboard covering patient vitals trajectories, alert triage, physician caseloads, and database benchmark comparisons.
6. **Data Governance, Backup, and Recovery:** Verification of backup procedures, role-based access control (RBAC), patient data isolation, and audit trail fidelity.

This document establishes the verified baseline of existing capabilities, provides an unvarnished audit of existing gaps, details the exact dataset characteristics, and lays out a 6-stage sequential roadmap for implementing and verifying the missing components.

---

## 1. Actual Kaggle Dataset Findings

The physical dataset was verified against both source files on disk:
- Primary file: `E:\DOC-20261013-WA0056.csv` (`CA15CF7776A0A670C834BA2693EDACBF4EB785ACD26D06D1617D3A56425F65A7`)
- Reference duplicate: `E:\kaggle_health_dataset.csv` (`50F391190CD58F87636C0F6AE45731F97791563210275F14E5208C75BE96EC82`)

### 1.1 Structural Properties
- **Total Physical Rows:** Exactly 1,500 data rows (excluding header).
- **Physical Columns:** 5 columns:
  1. `patient_id` (String: domain identifier)
  2. `heart_rate` (Float/Int: pulse in beats per minute, bpm)
  3. `spo2` (Float: peripheral oxygen saturation percentage, %)
  4. `temperature_f` (Float: body temperature in degrees Fahrenheit, °F)
  5. `timestamp` (ISO-8601 string: measurement observation timestamp)
- **Null / Missing Values:** 0 null values across all columns.
- **Unrepresented Metrics:** Blood pressure (`bp_systolic`, `bp_diastolic`) and respiratory rate (`respiratory_rate`) are completely absent from the raw CSV.

### 1.2 Cohort Distribution
The dataset contains observations for exactly 5 distinct patients:
| Patient ID | Record Count | Percentage of Total | Earliest Observation | Latest Observation | Time Span |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **P101** | 293 | 19.53% | 2026-10-10 00:00:00 | 2026-10-12 00:40:00 | ~48.7 hours |
| **P102** | 302 | 20.13% | 2026-10-10 00:00:00 | 2026-10-12 02:10:00 | ~50.2 hours |
| **P103** | 296 | 19.73% | 2026-10-10 00:10:00 | 2026-10-12 01:20:00 | ~49.2 hours |
| **P104** | 325 | 21.67% | 2026-10-10 00:00:00 | 2026-10-12 06:00:00 | ~54.0 hours |
| **P105** | 284 | 18.93% | 2026-10-10 00:00:00 | 2026-10-11 23:10:00 | ~47.2 hours |
| **Total** | **1,500** | **100.00%** | **2026-10-10 00:00:00** | **2026-10-12 06:00:00** | **~54.0 hours** |

### 1.3 Statistical Distributions
- **Heart Rate (`heart_rate`):**
  - Minimum: `60.0 bpm`
  - Maximum: `135.0 bpm`
  - Mean: `82.90 bpm`
  - Standard Deviation: `15.11 bpm`
  - Median: `80.0 bpm`
- **Oxygen Saturation (`spo2`):**
  - Minimum: `88.1%` (Hypoxemic trigger range < 90%)
  - Maximum: `99.9%`
  - Mean: `96.49%`
  - Standard Deviation: `2.37%`
  - Median: `97.0%`
- **Body Temperature (`temperature_f`):**
  - Minimum: `97.5°F` (~36.39°C)
  - Maximum: `103.0°F` (~39.44°C, Fever threshold > 100.4°F)
  - Mean: `98.69°F` (~37.05°C)
  - Standard Deviation: `0.94°F`
  - Median: `98.6°F` (~37.00°C)

---

## 2. Verified Relational Database Capabilities (MySQL 8)

The relational schema is fully normalized into Third Normal Form (3NF) across 15 tables with explicit InnoDB foreign keys, cascades, unique constraints, and check constraints.

### 2.1 Table Inventory & Foreign Key Graph
1. `import_batches`: Batch-level provenance, SHA-256 hashes, status check constraints (`pending`, `completed`, `failed`).
2. `users`: Core identity table with unique email, bcrypt password hashes, and role check constraint (`patient`, `doctor`, `admin_operator`).
3. `patient_profiles`: Patient demographic and physical data (`height_cm`, `weight_kg`), 1-to-1 FK to `users` with `ON DELETE CASCADE`.
4. `doctor_profiles`: Clinician credentials, license numbers, specialization, 1-to-1 FK to `users` with `ON DELETE CASCADE`.
5. `doctor_patient_assignments`: M-to-N clinician-patient relationship with composite PK `(doctor_id, patient_id)` and active status flag.
6. `ingestion_events`: Telemetry parent event with source provenance, duplicate suppression keys (`source_event_id`), and observation timestamp.
7. `vitals_readings`: Canonical EAV/normalized vital measurements with composite index `(patient_id, metric_code, measured_at)`.
8. `alert_rules`: Deterministic evaluation threshold configuration with severity check constraints (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
9. `patient_baselines`: Individualized patient physiological baseline ranges.
10. `model_assessments`: Machine learning risk inference scoring and assessment notes.
11. `alerts`: Clinical alerts with triggering foreign keys to `ingestion_events` and `alert_rules`, status lifecycle (`NEW`, `ACKNOWLEDGED`, `RESOLVED`).
12. `alert_status_history`: Immutable transition audit log recording `(old_status, new_status, actor_id, note)`.
13. `notification_deliveries`: Multi-channel notification delivery tracker (WebSocket, SMS, Email).
14. `conversations`: Secure patient-clinician messaging channels linked to `doctor_patient_assignments`.
15. `messages`: Individual conversation messages with sender FK, payload, and read timestamps.
16. `audit_logs`: Authoritative immutable access and modification trail.
17. `analytics_outbox`: Transactional outbox table for dual-write consistency between MySQL and MongoDB.

### 2.2 Relational Programmatic Constructs
Implemented and verified in `database/mysql/schema.sql`:
- **View (`vw_active_critical_alerts`):** Joins `alerts`, `patient_profiles`, and `doctor_patient_assignments` to expose unacknowledged critical alerts for immediate physician dispatch.
- **Stored Function (`fn_calculate_bmi`):** Deterministic stored function calculating Body Mass Index from height and weight:
  $$\text{BMI} = \text{ROUND}\left(\frac{\text{weight\_kg}}{(\text{height\_cm} / 100)^2}, 2\right)$$
  Safely returns `NULL` for invalid, non-positive, or missing inputs.
- **Stored Procedure (`sp_acknowledge_alert`):** Performs an atomic, transactional state transition for clinical alerts from `NEW` to `ACKNOWLEDGED`, asserting that resolved alerts cannot be acknowledged and inserting an immutable record into `alert_status_history`.
- **Trigger (`trg_alert_status_history_after_update`):** Fires after updates on `alerts` whenever `OLD.status <> NEW.status`, automatically appending the transition audit entry to `alert_status_history`.

---

## 3. Verified Document Database Capabilities (MongoDB Atlas)

MongoDB Atlas functions as an analytics-oriented mirror driven by the transactional outbox pattern.

### 3.1 Collections and Indexes
- **`telemetry_events` Collection:**
  - `_id`: Stable String ID matching MySQL `event_id`.
  - Compound Index: `(patient_id: 1, measured_at: -1)` for fast chronological patient retrieval.
  - Time Index: `(measured_at: -1)` for global time-range queries.
  - Filtering Indexes: `(source: 1)` and `(is_simulated: 1)`.
- **`alert_events` Collection:**
  - `_id`: Stable String ID matching MySQL `alert_id`.
  - Compound Index: `(patient_id: 1, created_at: -1)` for patient alert feeds.
  - Compound Index: `(status: 1, severity: 1)` for alert triage and severity cross-tabulation.
  - Correlation Indexes: `(rule_id: 1)` and `(event_id: 1)`.

### 3.2 Idempotency and State Synchronization
- **Monotonic Rank Protection:** Implemented in `AlertMirrorRepository`. In-flight alert updates are assigned state ranks: `NEW (1) < ACKNOWLEDGED (2) < RESOLVED (3)`. If a delayed or out-of-order event arrives with a lower rank than an existing document, the higher lifecycle status and audit timestamps are strictly preserved.
- **Outbox Worker (`OutboxSyncService`):** Polling mechanism with exponential backoff and retry tracking. Batches pending records from `analytics_outbox`, serializes telemetry and alert payloads, performs atomic upserts to MongoDB, and marks outbox items as `PROCESSED` or `FAILED` without data loss.

---

## 4. Existing Aggregation and Indexing Evidence vs. Gaps

### 4.1 Existing Implementation
- **Point and Range Queries:** Both `VitalsRepository` (MySQL) and `TelemetryMirrorRepository` (MongoDB) provide indexed lookups by patient ID and date ranges.
- **Eager Loading:** `VitalsRepository.get_patient_events_paginated` uses SQLAlchemy `joinedload` to prevent N+1 query overhead.
- **Index Definitions:** All primary relational foreign keys and composite indexes are defined in `database/mysql/schema.sql` and `alembic/versions/`. All MongoDB mirror indexes are specified in `database/mongodb/collections.py`.

### 4.2 Gaps Identified
- **Zero MongoDB Aggregation Pipelines:** Neither `TelemetryMirrorRepository` nor `AlertMirrorRepository` contains any `collection.aggregate([])` pipelines.
  - Missing: Multi-metric statistical summaries (`$group` with `$min`, `$max`, `$avg`, `$stdDevPop`).
  - Missing: Time-bucketed rollups (`$dateTrunc` or `$dateToString` hourly/daily rollups).
  - Missing: Severity cross-tabulations and alert triage analytics.
  - Missing: Multi-faceted dashboard aggregates using `$facet`.
- **Zero Automated Explain Plan Harness:**
  - Missing: Automated PyMongo `.explain("executionStats")` harness to verify index hit (`IXSCAN`) vs table scan (`COLLSCAN`), keys examined, and documents examined.
  - Missing: Automated MySQL `EXPLAIN` / `EXPLAIN ANALYZE` harness to verify index seek vs table scan and actual execution timing.

---

## 5. Existing Benchmarking Evidence vs. Gaps

### 5.1 Existing Implementation
- **Zero Benchmarks Exist:** There are currently no benchmark scripts, latency harnesses, or benchmark result data files in the codebase.
- **Honesty Mandate:** No latency numbers, throughput metrics, or performance figures have been fabricated.

### 5.2 Gaps Identified
- Missing: Automated benchmark script comparing SQL vs. NoSQL across identical queries:
  1. Single-patient latest vitals fetch.
  2. Multi-day chronological range scan for a single patient.
  3. Aggregate statistical computation (min, max, avg across vitals).
  4. Global alert status and severity aggregation.
- Missing: Statistical latency evaluation over multiple iterations ($N \ge 100$): p50, p95, p99, and standard deviation.
- Missing: Automated export of benchmark artifacts to structured JSON and Markdown for academic reporting.

---

## 6. Existing Dashboard Status vs. Gaps

### 6.1 Existing Implementation
- Dependencies: `streamlit>=1.35.0` is installed and pinned in `requirements.txt`.
- Core APIs: Fully functional FastAPI backend endpoints exist for auth, vitals readings, alerts, and messaging.

### 6.2 Gaps Identified
- **Zero Dashboard Files Exist:** No files matching `dashboard/app.py`, `dashboard/pages/`, or similar exist in the repository.
- Missing: Interactive Streamlit UI components:
  1. Patient Vitals Explorer (time-series trendlines, threshold violation highlights).
  2. Clinical Alert Management (triage table, severity breakdown, acknowledgment tracking).
  3. Clinician Caseload View (doctor-patient assignments, latest vitals cards).
  4. SQL vs. NoSQL Performance Benchmark Visualizer (latency bar charts, explain plan inspector).
- Missing: Strict read-only database session isolation for dashboard components to guarantee safety.

---

## 7. Backup, Recovery, and Access-Control Verification Status

### 7.1 Existing Implementation
- Comprehensive operational runbooks already exist:
  - `docs/backup_and_recovery.md`: Full disaster recovery runbook covering logical `mysqldump`, physical percona xtrabackup, MongoDB Atlas continuous cloud backups, and point-in-time recovery (PITR) procedures.
  - `docs/deployment_guide.md`: Containerization, security posture, TLS termination, and readiness/liveness health probes.
- Automated Test Suite: 211 automated tests covering RBAC, role enforcement, patient data isolation, clinician assignment validation, and token revocation pass with a 100% pass rate.

### 7.2 Gaps Identified
- Missing: Automated test script or verification utility that validates mock backup file creation, checksum validation, and schema restoration in an isolated sandbox.
- Missing: Coursework-specific documentation linking the operational backup runbook to academic database syllabus rubrics.

---

## 8. Actionable Implementation Matrix

The following implementation matrix covers all 6 sequential stages required to fulfill the DA3 coursework objectives:

| Requirement | Existing implementation | Evidence | Gap | Proposed next step | Verification method |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 1: MongoDB Aggregation Pipelines** | Basic point queries (`find`, `count_documents`) in `TelemetryMirrorRepository` and `AlertMirrorRepository`. | `database/mongodb/repositories/*.py` | Zero `aggregate()` pipelines exist for statistical rollups, time buckets, or multi-faceted summaries. | Implement `MongoAnalyticsRepository` with 4 dedicated pipelines: (1) Vitals summary stats ($min, $max, $avg, $stdDevPop), (2) Hourly/daily time rollups, (3) Alert severity cross-tabs, (4) Dashboard `$facet`. | Unit tests using `mongomock` verifying correct aggregation math and facet output structures. |
| **Stage 1: SQL Statistical Aggregation Parity** | Basic point filtering and joined loading in `VitalsRepository`. | `database/mysql/repositories/vitals_repository.py` | No dedicated statistical summary or time-bucket aggregation methods in MySQL repository. | Implement `SqlAnalyticsRepository` providing exact mathematical parity with MongoDB aggregation queries using SQL `AVG()`, `MIN()`, `MAX()`, `STDDEV_POP()`, and `DATE_FORMAT()`. | Integration test verifying identical mathematical results between SQL and NoSQL aggregations on the same dataset. |
| **Stage 2: MongoDB Explain-Plan Evidence** | Index specifications defined in `TELEMETRY_INDEXES` and `ALERT_INDEXES`. | `database/mongodb/collections.py` | No programmatic harness to extract and assert execution stats from `.explain("executionStats")`. | Implement `explain_analyzer.py` executing explain plans on aggregation and point queries, extracting `stage` (`IXSCAN` vs `COLLSCAN`), `totalKeysExamined`, and `totalDocsExamined`. | Automated test asserting `stage == "IXSCAN"` and `totalDocsExamined <= n_returned` for indexed queries. |
| **Stage 2: MySQL Explain-Plan Evidence** | Schema indexes defined on primary keys, foreign keys, and vitals composite keys. | `database/mysql/schema.sql` | No programmatic harness to capture `EXPLAIN ANALYZE` or JSON execution plan trees in MySQL. | Add MySQL explain plan runner executing `EXPLAIN FORMAT=JSON` across corresponding queries, capturing cost, key used, and rows examined. | Automated script verifying key usage (`idx_vitals_patient_metric_time`, `idx_alerts_patient_status_created`). |
| **Stage 3: SQL vs NoSQL Benchmark Suite** | None. | Repository search confirms 0 benchmark scripts exist. | Complete absence of empirical latency comparisons, percentiles, throughput, and size benchmarks. | Develop `benchmarks/run_benchmarks.py` running $N \ge 100$ iterations of identical queries against SQL and NoSQL, computing p50, p95, p99, and export to JSON/Markdown. | Benchmark test verifying script execution and valid statistical distribution outputs. |
| **Stage 4: Streamlit Dashboard Core App** | Streamlit package installed in environment. | `requirements.txt` (`streamlit>=1.35.0`) | No dashboard application files exist in `dashboard/`. | Create `dashboard/app.py` with multi-page navigation, theme config, and read-only database connections. | Manual/automated launch test ensuring Streamlit app imports and initializes without errors. |
| **Stage 4: Streamlit Vitals & Alert Pages** | Vitals and Alert REST APIs and repositories exist in backend. | `services/vitals_service.py`, `services/alert_service.py` | No UI visualization for vitals trajectories or alert triage. | Create `dashboard/pages/1_Patient_Vitals.py` and `dashboard/pages/2_Alert_Triage.py` using Altair charts for time-series and alert breakdown metrics. | Render verification ensuring charts display proper ranges (60–135 bpm, 88–100% SpO2, 97.5–103°F). |
| **Stage 4: Streamlit Benchmark Viewer** | None. | No benchmark explorer exists. | No interactive UI to inspect query plans and latency distributions. | Create `dashboard/pages/3_Database_Benchmarks.py` displaying latency comparison bar charts, p95 comparisons, and explain plan tree views. | UI verification confirming interactive visualization of benchmark results. |
| **Stage 5: Backup & Security Verification** | Backup runbook documented; RBAC enforced in FastAPI. | `docs/backup_and_recovery.md`, `tests/integration/test_security_regressions.py` | No automated test script verifying backup file generation and mock restore round-trip. | Create `scripts/verify_backup_restore.py` running mock mysqldump/mongodump routines and asserting schema integrity on restore. | Execution of verification script verifying non-destructive backup artifact creation and syntax validation. |
| **Stage 6: Coursework Documentation & Report** | Partial architecture documentation in `docs/`. | `docs/operational_architecture.md`, `docs/dataset_ingestion.md` | Coursework report missing comprehensive synthesis of normalization proofs, execution plans, and benchmark analysis. | Compile comprehensive academic report `docs/coursework_da3_final_report.md` synthesizing all theoretical proofs, benchmark charts, and design decisions. | Peer audit against academic grading rubrics. |

---

## 9. Prioritized Implementation Sequence

To ensure rigorous execution without regressions, the missing components will be developed sequentially:

```
┌────────────────────────────────────────────────────────┐
│ Stage 1: Aggregation Pipelines (MongoDB & MySQL Parity)│
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Stage 2: Query Indexing & Explain-Plan Evidence Harness │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Stage 3: Empirical SQL vs. NoSQL Benchmarking Suite    │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Stage 4: Streamlit Analytics & Benchmark Dashboard     │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Stage 5: Backup, Recovery, and Access-Control Audit    │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Stage 6: Final Integration Verification & Documentation│
└────────────────────────────────────────────────────────┘
```

1. **Stage 1 (Next Step — Part 3B):** Implement `MongoAnalyticsRepository` and `SqlAnalyticsRepository` providing aggregation pipelines for statistical rollups, time buckets, and multi-faceted summaries with mathematical parity.
2. **Stage 2:** Build automated explain-plan extractors verifying index utilization (`IXSCAN` vs `COLLSCAN` and MySQL key usage).
3. **Stage 3:** Build the statistical benchmark runner measuring p50, p95, and p99 query latencies across SQL and NoSQL.
4. **Stage 4:** Implement the multi-page Streamlit application connecting to the analytics layer in read-only mode.
5. **Stage 5:** Execute automated backup/restore verification and compile RBAC security audit evidence.
6. **Stage 6:** Final end-to-end integration test execution and compilation of the comprehensive coursework submission report.

---

## 10. Recommended Next Implementation Prompt

### Recommended Next Milestone: **PART 3B — MongoDB Aggregation Pipelines and SQL Analytics Parity**

**Prompt Scope:**
1. Create `database/mongodb/repositories/analytics_repository.py` implementing:
   - `get_patient_vitals_summary(patient_id, start_time, end_time)` using `$match`, `$unwind`, and `$group` ($min, $max, $avg, $stdDevPop).
   - `get_time_bucketed_vitals(patient_id, interval="hour")` using `$dateTrunc` / `$dateToString` bucketing.
   - `get_alert_distribution(start_time, end_time)` grouping by `status` and `severity`.
   - `get_clinical_dashboard_facets(patient_id)` using `$facet` to return vitals summaries, recent alerts, and anomaly indicators in a single database round-trip.
2. Create `database/mysql/repositories/analytics_repository.py` implementing the exact mathematical equivalent in SQL for parity and benchmarking.
3. Add comprehensive automated tests in `tests/unit/test_analytics_repositories.py` verifying aggregation correctness against both `mongomock` and SQLite/MySQL.
