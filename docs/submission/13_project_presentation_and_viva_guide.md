# 13. Project Presentation, Viva Voce & Technical Defense Guide

**Document:** Master Technical Viva Voce & Oral Defense Preparation Guide  
**Project:** AI-Powered Smart Health Monitoring System  
**Auditor & Technical Coach:** Senior Software Architect, Database Systems Examiner & Academic Project Auditor  
**Date:** 14 October 2026  
**System Version:** 3.0.0 (FastAPI Core Gateway + Hybrid Polyglot Persistence)  
**Applicable Digital Assignments:** DA1, DA2, and DA3  

---

## 1. Architectural Foundation & Technical Overview

### 1.1 Why Polyglot Persistence?
Healthcare monitoring platforms must simultaneously satisfy two contradictory operational requirements:
1. **High-Integrity Clinical Transactions:** Demographics, medical history, user credentials, role permissions, and clinical alert lifecycles require strict ACID transactions, declarative foreign key integrity, and non-repudiable audit trails. MySQL 8.0 InnoDB provides this authoritative foundation.
2. **High-Velocity Time-Series Analytics:** Physiological telemetry streams (heart rate, SpO2, blood pressure, temperature) generate millions of data points requiring flexible indexing, high ingestion throughput, and multi-stage windowed aggregations across cohorts. MongoDB Atlas provides horizontal scalability and specialized aggregation operators without locking operational tables.

### 1.2 End-to-End Data Flow & Lifecycle
1. **Ingress:** Patient telemetry enters via authenticated REST endpoints (`POST /api/v1/vitals/`) or simulated device streams.
2. **Operational Commit & Outbox Enqueue:** FastAPI invokes clinical rule thresholds. In a single atomic MySQL InnoDB transaction:
   - A `vitals_readings` record is inserted.
   - If a physiological threshold is breached, a `clinical_alerts` record is inserted.
   - An event payload is enqueued into `analytics_outbox` with status `PENDING`.
3. **Asynchronous Outbox Mirroring:** A decoupled background worker polls `analytics_outbox`, extracting batches of pending events. It mirrors records into MongoDB Atlas using idempotent upserts (`replace_one(filter={"source_event_id": id}, replacement=doc, upsert=True)`). Upon acknowledgment, the worker updates the outbox record to `PROCESSED`.
4. **Machine Learning Inference:** When requested by clinicians or triggered by triage workflows, the backend retrieves a patient's historical vitals, extracts a 38-dimensional feature vector, adjusts for personal baseline drift via `BaselineManager`, and queries the serialized Isolation Forest model (`models/iforest_v1/iforest_model.joblib`) to return an anomaly score.
5. **Real-Time Streaming:** Active alerts and live telemetry frames are pushed to connected clinician web workstations over WebSockets authenticated via single-use, 5-minute ephemeral tickets (`POST /api/v1/ws-ticket`).
6. **Failure Isolation:** If MongoDB Atlas becomes unreachable due to a network partition, operational patient care and MySQL transactions proceed normally. Events buffer safely in `analytics_outbox` and sync automatically when connectivity is restored.

---

## 2. Comprehensive Database Systems Viva Questions & Deep Answers

### Q1: Explain the normalization of your relational schema. How do you prove it is in 3NF and BCNF?
**Model Answer:**
"Our MySQL schema comprises 17 tables designed in Third Normal Form (3NF) and Boyce-Codd Normal Form (BCNF). 
- **1NF:** Every column stores atomic, indivisible values. For example, in `vitals_readings`, vital metrics are stored in discrete floating-point columns (`heart_rate`, `spo2`, `systolic_bp`, `diastolic_bp`, `temperature`) rather than a single JSON string or comma-separated list.
- **2NF:** All non-key attributes are fully functionally dependent on the entire primary key. In composite junction tables like `doctor_patient_assignments`, attributes depend on the complete composite candidate key `(doctor_id, patient_id)`, with zero partial dependencies.
- **3NF & BCNF:** Transitive dependencies are eliminated. We decoupled user authentication credentials (`users`) from clinical patient profiles (`patient_profiles`) and doctor profiles (`doctor_profiles`). If a doctor's clinic address or license number changes, it updates exactly one row in `doctor_profiles`; it does not touch the `users` table or historical patient readings. 
- **Mathematical BCNF Proof:** For every non-trivial functional dependency $X \rightarrow Y$ in our schema, the determinant $X$ is a superkey. For instance, in `vitals_readings`:
  $$\text{id} \rightarrow (\text{patient\_id}, \text{recorded\_at}, \text{heart\_rate}, \text{spo2}, \text{systolic\_bp}, \text{diastolic\_bp}, \text{temperature})$$
  Because $\text{id}$ is the primary key and superkey, BCNF is preserved across all relations."

---

### Q2: How does your database ensure atomic safety during patient discharge? Explain `sp_safe_patient_discharge`.
**Model Answer:**
"In healthcare systems, discharging a patient while they still have active, critical physiological emergencies is a fatal hazard. We implemented the stored procedure `sp_safe_patient_discharge` using **ACID transactions with named savepoints**:
```sql
START TRANSACTION;
SAVEPOINT before_discharge;

-- Check if patient has any unresolved CRITICAL or HIGH alerts
SELECT COUNT(*) INTO active_critical_count FROM alerts 
WHERE patient_id = p_patient_id AND severity IN ('HIGH', 'CRITICAL') AND status = 'ACTIVE';

IF active_critical_count > 0 THEN
    ROLLBACK TO SAVEPOINT before_discharge;
    SET p_success = FALSE;
    SET p_message = 'Cannot discharge patient with active CRITICAL or HIGH alerts.';
    COMMIT;
ELSE
    UPDATE doctor_patient_assignments SET is_active = FALSE WHERE patient_id = p_patient_id;
    UPDATE patient_profiles SET is_active = FALSE WHERE id = p_patient_id;
    SET p_success = TRUE;
    SET p_message = 'Patient discharged safely.';
    COMMIT;
END IF;
```
If an active critical alert exists, the procedure rolls back to `before_discharge`, aborting the deactivation of assignments and patient status, and returns an explanatory rejection message. If no critical alerts exist, all status updates commit atomically."

---

### Q3: How do database triggers maintain an immutable clinical audit trail?
**Model Answer:**
"We implemented the trigger `trg_alert_status_history_after_update` on the `alerts` table. Whenever an alert's status is modified (e.g. from `ACTIVE` to `ACKNOWLEDGED` or `RESOLVED`), the trigger automatically fires:
```sql
CREATE TRIGGER trg_alert_status_history_after_update
AFTER UPDATE ON alerts
FOR EACH ROW
BEGIN
    IF OLD.status != NEW.status THEN
        INSERT INTO alert_status_history (
            alert_id, old_status, new_status, changed_by, changed_at, notes
        ) VALUES (
            NEW.id, OLD.status, NEW.status, NEW.acknowledged_by, NOW(), 'Trigger recorded status transition'
        );
    END IF;
END;
```
This guarantees an immutable, non-repudiable audit trail directly inside the database engine. Even if an administrator or backend service executes a raw SQL `UPDATE`, the audit entry is created automatically without relying on application-level logging code."

---

### Q4: Explain the difference between your two relational views: `v_latest_patient_vitals` and `v_patient_active_alerts`.
**Model Answer:**
"Both views eliminate query complexity for our application layer:
1. **`v_latest_patient_vitals`:** Resolves the most recent vital sign reading for every active patient. It joins `patient_profiles` with `vitals_readings` using an inner join against a grouped subquery on `MAX(recorded_at)`. This allows our clinician directory to display current vital status without running expensive window functions on every page load.
2. **`v_patient_active_alerts`:** Serves as a live clinical triage board. It joins `alerts` where `status = 'ACTIVE'` with `patient_profiles`, `users`, and active `doctor_patient_assignments`. This gives emergency room doctors an instant, denormalized view of who the patient is, what vital breached threshold, and which physician is currently assigned."

---

### Q5: Explain the 7 MongoDB aggregation pipelines. Which stages were used and why?
**Model Answer:**
"Our 7 production pipelines in `database/mongodb/analytics/pipelines.py` execute complex analytical transformations directly on the database cluster:
1. **Pipeline A (Dataset Overview):** Uses the `$facet` stage to run parallel sub-pipelines computing total counts, distinct patient sets (`$addToSet`), and abnormal ratios in a single database round-trip.
2. **Pipeline B (Patient Vitals Summary):** Uses `$match` on `patient_id` followed by `$group` with accumulators (`$avg`, `$min`, `$max`, and `$stdDevSamp`) to calculate comprehensive statistical moments.
3. **Pipeline C (Time-Window Filter):** Uses `$match` with `$gte` and `$lte` on the indexed `recorded_at` field to perform efficient temporal range queries.
4. **Pipeline D (Time-Bucket Analytics):** Uses `$match`, `$project` with date truncation expressions, `$group` on the bucket identifier, and `$sort` to produce chronological hourly vital trends.
5. **Pipeline E (Filtered Patient History):** Combines `$match`, `$sort: {recorded_at: -1}`, `$skip`, and `$limit` to provide deterministic, indexed pagination for clinician web clients.
6. **Pipeline F (Source Provenance):** Uses `$group: {_id: "$data_source"}` to compute ingestion counts and temporal boundaries per data provider.
7. **Pipeline G (Alert Summary):** Uses `$group: {_id: {severity: "$severity", status: "$status"}}` to summarize open emergency queues."

---

### Q6: How does the Transactional Outbox Pattern guarantee eventual consistency between MySQL and MongoDB?
**Model Answer:**
"Dual writes—where an application attempts to write sequentially to MySQL and then to MongoDB—inevitably fail when network partitions occur, leading to data drift.
To prevent this, we use the **Transactional Outbox Pattern**:
1. When vital telemetry arrives, the vital reading and an outbox event are inserted into MySQL within the **exact same ACID transaction**. If the transaction commits, the event is guaranteed to reside in `analytics_outbox`.
2. An asynchronous worker polls `analytics_outbox` for `PENDING` events.
3. The worker replicates documents into MongoDB Atlas using **idempotent upserts**:
   `db.telemetry_readings.replace_one({"source_event_id": event.id}, doc, upsert=True)`.
4. If the worker crashes or network fails after writing to MongoDB but before updating MySQL, the worker will re-read the event and re-execute the upsert. Because the operation is keyed on `source_event_id`, it simply overwrites the identical document without creating duplicates.
5. Once MongoDB confirms write acknowledgment, the worker marks the outbox row as `PROCESSED`. This guarantees at-least-once delivery with idempotent processing, achieving robust Eventual Consistency."

---

### Q7: Explain your database backup and disaster recovery strategy. What is the role of MySQL Binary Logs?
**Model Answer:**
"Our backup strategy is defined in `scripts/backup_and_recovery.py` and documented in runbook `10_backup_and_recovery_runbook.md`:
- **Consistent Snapshots:** We take logical backups of MySQL using `mysqldump --single-transaction --routines --triggers`. The `--single-transaction` flag uses InnoDB's Multi-Version Concurrency Control (MVCC) to take a snapshot at a consistent transaction ID without acquiring table write locks, ensuring incoming sensor writes are never blocked.
- **Point-in-Time Recovery (PITR):** If database corruption occurs at 14:35:00, restoring a daily midnight snapshot would lose 14 hours of patient telemetry. By replaying MySQL **Binary Logs** (`mysqlbinlog --start-datetime ... --stop-datetime="2026-10-14 14:34:59"`), we replay all committed transactions up to the exact second prior to corruption.
- **Automated Restore Drills:** Our test suite executes a non-destructive restore drill: it imports the backup snapshot into a temporary database (`smart_health_restore_test`), validates row counts across all 17 tables, audits stored procedures, and tears down the test database cleanly."

---

## 3. Machine Learning Viva Questions & Deep Answers

### Q1: Why did you choose Isolation Forest over supervised machine learning models?
**Model Answer:**
"In physiological telemetry monitoring, supervised classifiers (such as Random Forest or XGBoost) suffer from three fatal flaws:
1. **Severe Class Imbalance:** In real clinical monitoring, 99% of telemetry represents normal physiological equilibrium. Confirmed clinical emergencies are rare.
2. **Unpredictable Anomaly Profiles:** Medical crises take diverse, unpredictable forms (e.g., tachycardic arrhythmia, hypothermia, septic shock). Supervised models only recognize anomalies that closely resemble their labeled training examples.
3. **Unavailability of Massive Labeled Datasets:** Accurate clinical labels require exhaustive annotations by licensed physicians, which are scarce.
**Isolation Forest** operates **unsupervised**. It exploits the fundamental property that anomalies are few in number and physiologically divergent, meaning they are isolated at significantly shallower tree depths when partitioning random features."

---

### Q2: What is the mathematical formulation behind Isolation Forest anomaly scoring?
**Model Answer:**
"Isolation Forest constructs an ensemble of randomized isolation trees. In each tree, partitions are created by recursively selecting a random feature and a random split point.
Because anomalies have atypical values, they require far fewer splits to be isolated. The anomaly score $s(x, n)$ for an observation $x$ over a sample size of $n$ is defined as:
$$s(x, n) = 2^{-\frac{\mathbb{E}(h(x))}{c(n)}}$$
Where:
- $h(x)$ is the path length (the number of edges traversed from root to leaf node).
- $\mathbb{E}(h(x))$ is the average path length across all isolation trees in the ensemble.
- $c(n)$ is the average path length of an unsuccessful search in a Binary Search Tree (BST), computed as:
  $$c(n) = 2 \ln(n - 1) + 0.5772156649 \text{ (Euler's constant)} - \frac{2(n - 1)}{n}$$
When $\mathbb{E}(h(x)) \to 0$, $s \to 1$ (high anomaly likelihood). When $\mathbb{E}(h(x)) \to n - 1$, $s \to 0$ (normal equilibrium)."

---

### Q3: What features did your team engineer? Why not feed raw sensor numbers directly to the model?
**Model Answer:**
"Raw sensor numbers represent single instantaneous snapshots that fail to capture physiological dynamics. In `packages/health_analysis/features.py`, we transform the 5 raw vitals into a **38-dimensional feature vector**:
1. **Raw Vitals (5):** Instantaneous Heart Rate, SpO2, Systolic BP, Diastolic BP, and Temperature.
2. **Rolling Means ($\mu_5, \mu_{10}$ — 10 features):** Short-term and medium-term physiological equilibrium baselines.
3. **Rolling Volatility ($\sigma_5, \sigma_{10}$ — 10 features):** Standard deviation across windows, capturing arrhythmia and autonomic instability.
4. **Rolling Peak-to-Peak Ranges ($\max_{10} - \min_{10}$ — 5 features):** Physiological excursion bounds.
5. **Temporal Rates of Change ($\Delta x_t = x_t - x_{t-1}$ — 4 features):** Captures acute crashes (e.g. rapid blood pressure drop).
6. **Patient Z-Scores ($Z_{\text{base}}$ — 4 features):** $Z_i = \frac{x_i - \mu_{\text{patient}}}{\sigma_{\text{patient}}}$, standardizing readings against the patient's personal history."

---

### Q4: How does the `BaselineManager` prevent alarm fatigue?
**Model Answer:**
"Alarm fatigue is a severe clinical hazard where medical staff become desensitized to alarms due to high false-positive rates. Traditional static thresholds flag any resting heart rate below 60 bpm as bradycardia. However, for a healthy athlete, a resting heart rate of 48 bpm is completely normal.
Our `BaselineManager` resolves this:
1. When a patient is admitted, the system aggregates their stable telemetry and computes an individual baseline profile stored in `patient_baselines`.
2. During feature engineering, vital readings are normalized against the patient's individual mean and standard deviation.
3. If an individual has naturally elevated resting heart rates, the model evaluates deviations relative to their personal baseline rather than population averages, eliminating spurious alarms."

---

### Q5: How do machine learning predictions interact with your deterministic clinical rule engine?
**Model Answer:**
"They operate as a **Defense-in-Depth Hybrid Architecture**:
- **Tier 1 (Deterministic Rule Engine):** Acts as our uncompromising safety net. If a patient's SpO2 drops below 90% or heart rate exceeds 150 bpm, a `CRITICAL` alert is generated immediately with zero model latency and zero probabilistic uncertainty.
- **Tier 2 (Isolation Forest ML Engine):** Acts as an early-warning radar. It identifies multi-variate correlations and subtle physiological drift (e.g. rising heart rate accompanied by dropping diastolic blood pressure) before any individual vital sign breaches a hard threshold.
- **Regulatory Clarification:** The ML engine is strictly an educational decision-support triage tool, not a diagnostic medical device. It flags statistical anomaly probabilities, not medical disease diagnoses."

---

## 4. Backend & Security Viva Questions & Deep Answers

### Q1: Why did you choose FastAPI over Flask or Django?
**Model Answer:**
"FastAPI was selected for three architectural reasons:
1. **Native Asynchronous I/O (`async`/`await`):** In a healthcare system handling concurrent telemetry streams and WebSocket pushes, FastAPI's asynchronous ASGI architecture handles thousands of concurrent connections per process without thread-starvation bottlenecks.
2. **Pydantic v2 Type Safety & Schema Validation:** Telemetry data is validated at the application boundary via Pydantic models. Malformed sensor payloads are rejected with clear HTTP 422 errors before reaching database layers.
3. **Automatic OpenAPI/Swagger Generation:** FastAPI automatically generates interactive documentation (`/docs`), ensuring that our frontend team (Aditya) had an exact, self-documenting API contract."

---

### Q2: Explain the security architecture: Authentication vs. Authorization.
**Model Answer:**
"We implement a strict separation between authentication and authorization:
- **Authentication (Who are you?):** Handled via OAuth2 Password Bearer flow issuing HMAC-SHA256 signed JSON Web Tokens (JWT). The token carries the user's ID, username, and role, protected by a cryptographic signature.
- **Authorization (What are you permitted to do?):** Enforced via four-tier Role-Based Access Control (RBAC) dependencies:
  - `ADMIN`: User provisioning, benchmark execution, database backup/restore.
  - `DOCTOR`: Patient diagnosis, telemetry inspection, alert triage, and discharge authorization.
  - `NURSE`: Telemetry recording, vital sign monitoring, alert acknowledgment.
  - `PATIENT`: Strictly restricted to viewing their own records.
- **Patient Isolation:** To prevent Insecure Direct Object References (IDOR), endpoints inspecting patient telemetry assert that if the caller is a `PATIENT`, the requested `{id}` must match the caller's linked profile ID, otherwise returning an immediate 403 Forbidden."

---

### Q3: Explain the Single-Use WebSocket Ticket Protocol. Why not pass the JWT token in the WebSocket URL?
**Model Answer:**
"In browser JavaScript, the native `WebSocket` API does not support setting custom HTTP headers like `Authorization: Bearer <token>`. Developers often take the dangerous shortcut of passing the JWT in the query string: `wss://host/ws?token=eyJh...`.
This is a critical security vulnerability: query parameters are logged in plain text in proxy logs, browser histories, and server access logs, exposing long-lived credentials.
We resolved this using an **Ephemeral Ticket Exchange Protocol**:
1. The authenticated frontend client makes an HTTPS POST request to `/api/v1/ws-ticket` with its standard Bearer JWT header.
2. The server verifies the token and generates a cryptographically random, single-use ticket string with a 5-minute time-to-live (TTL).
3. The client opens the WebSocket connection using the ticket: `wss://host/api/v1/ws/clinician?ticket=ws_ticket_...`.
4. The server validates and immediately consumes the ticket. Even if an attacker captures the URL from a log file, the ticket has already expired and cannot be reused."

---

## 5. Performance Benchmarking Viva Questions & Deep Answers

### Q1: What was the primary objective of your SQL vs. NoSQL benchmark? What does "Correctness Before Speed" mean?
**Model Answer:**
"The primary objective was conducting an empirically rigorous comparison between MySQL 8 InnoDB and MongoDB Atlas across standardized healthcare workloads.
Most database benchmarks are fundamentally flawed because they compare queries that return different data structures or row counts, rendering latency comparisons meaningless.
**'Correctness Before Speed'** means our benchmarking harness (`benchmarks/harness.py`) executes a pre-flight semantic equivalence validation across all seven workloads. It compares row counts and asserts that aggregated numerical values (averages, standard deviations, sums) match within a strict tolerance ($\epsilon \le 0.05$). Only after all 7 workloads pass equivalence does the harness measure execution latency."

---

### Q2: Walk us through your actual benchmark results (`bench_1791921481`). Why did MySQL win in Workloads A–F, while MongoDB won in Workload G?
**Model Answer:**
"In persistent benchmark run `bench_1791921481`:
- **Workloads A through F:** MySQL demonstrated lower median latencies (0.58 ms to 9.54 ms) compared to MongoDB (46.70 ms to 75.93 ms). The reason is that our MySQL schema utilizes **composite B-tree covering indexes** (such as `(patient_id, recorded_at DESC)`). In our test harness, MySQL satisfied the queries directly from cached memory pages without reading row blocks, and MySQL's compiled C++ storage engine has near-zero overhead for single-node indexed scans.
- **Workload G (Clinical Alert Triage):** MongoDB defeated MySQL decisively, executing in **0.06 ms** versus MySQL's **0.84 ms**—a **14.5x speedup**. In Workload G, MongoDB queried a pre-aggregated, denormalized collection (`clinical_alerts`) where alert statuses and severities were indexed in a single BSON document structure. MongoDB performed an in-memory index group without checking foreign keys or joining relational tables."

---

### Q3: What did the MySQL query execution plan (`EXPLAIN`) reveal about Workload E (Patient History)?
**Model Answer:**
"When we ran `EXPLAIN FORMAT=TREE` on Workload E:
```
-> Limit: 20 row(s) (cost=1.25 rows=20)
    -> Filter: (vitals_readings.is_abnormal = true) (cost=1.25 rows=20)
        -> Index scan on vitals_readings using idx_vitals_patient_recorded (reverse)
```
The execution plan revealed that MySQL's optimizer utilized the composite index `(patient_id, recorded_at DESC)` in reverse. Because the B-tree leaf nodes were already pre-sorted on disk by recording timestamp, MySQL completely bypassed the need for an in-memory or disk `filesort` buffer. The query scanned only the required leaf pages and terminated immediately upon satisfying the `LIMIT 20` boundary."

---

## 6. Live Demonstration Script & Verification Protocol

The live demonstration follows an 8-step verified workflow designed to run seamlessly in 5 minutes:

| Step | Action to Perform | Component Involved | Expected Output | Verification Status | Fallback if Service Fails |
|:---:|---|---|---|:---:|---|
| **1** | Execute `GET /health/ready` | FastAPI Gateway & MySQL | HTTP 200 OK: `{"status": "ready", "database": "connected"}` | **Verified** | Show terminal output from `scratch/e2e_verification_harness.py`. |
| **2** | Login as Dr. Sarah Chen (`POST /api/v1/auth/login`) | Auth Router & JWT | HTTP 200 OK with Bearer access token and role `DOCTOR` | **Verified** | Use pre-generated JWT token from environment. |
| **3** | Navigate to `/patients` on React Dashboard | React Workstation (`doctor_web`) | Table displaying 5 patient cohorts imported from Kaggle dataset | **Verified** | Toggle `VITE_USE_MOCK_DATA=true` for demo mode. |
| **4** | Open Patient 1 Telemetry View | React UI & FastAPI `/vitals` | Interactive Plotly multi-parameter vital charts (HR, SpO2, BP) | **Verified** | Show Streamlit Patient Telemetry view on port 8501. |
| **5** | Ingest Critical Telemetry (SpO2 88%) & Acknowledge | Ingestion API & MySQL Stored Proc | Real-time alert triggers; doctor clicks "Acknowledge"; trigger records audit log | **Verified** | Query `alert_status_history` directly via MySQL CLI. |
| **6** | Trigger ML Assessment for Patient 1 | ML Engine (`health_analysis`) | Anomaly score computed (e.g. 0.74), top contributing features rendered | **Verified** | Display output of `test_predictions.py`. |
| **7** | Demonstrate Outbox Event Sync | MySQL & MongoDB Sync Worker | `analytics_outbox` row transitions to `PROCESSED`; document appears in Mongo | **Verified** | Show MongoDB Compass or mongomock test log. |
| **8** | Open Streamlit Benchmark Explorer | Streamlit Dashboard (Port 8501) | Renders 7/7 equivalence pass and 14.5x MongoDB alert triage speedup chart | **Verified** | Open `benchmarks/results/bench_1791921481_summary.md`. |

---

## 7. Individual Team Responsibilities & Ownership Summary

| Team Member | Official Academic Responsibilities | Specific Code Modules & Deliverables Owned | Viva Focus & Primary Questions |
|---|---|---|---|
| **Aryan Sharma** | **Backend Architecture & Database Reliability Lead** | • FastAPI core gateway (`app/`)<br>• MySQL 17-table schema, stored procedures, triggers, views (`database/mysql/`)<br>• MongoDB mirror & 7 aggregation pipelines (`database/mongodb/`)<br>• Transactional outbox sync worker (`mirror/worker.py`)<br>• SQL vs. NoSQL benchmark suite (`benchmarks/`)<br>• Database backup & disaster recovery runbooks (`scripts/`) | Normalization (3NF/BCNF), ACID transactions with savepoints, database triggers, outbox eventual consistency, aggregation pipelines, benchmark methodology, and backup/PITR procedures. |
| **Aditya Dhakad** | **Frontend & Clinician UI/UX Lead** | • React 19 clinician web workstation (`apps/doctor_web`)<br>• Axios REST API client & Bearer token interceptor (`api/`)<br>• WebSocket ticket stream adapter (`wsService.ts`)<br>• Dual Live/Demo mode architecture<br>• Patient directory, vitals charts, and alert triage desk<br>• Frontend automated test suite (`tests/`) | React architecture, JWT lifecycle, token auto-refresh on 401, WebSocket ticket handshake, UI state management, and error handling. |
| **Harnoor Kant** | **Machine Learning & Analytics Lead** | • `health_analysis` machine learning package<br>• Isolation Forest v1.0.0 model artifact (`models/iforest_v1/`)<br>• 38-feature engineering & extraction pipeline (`features.py`)<br>• Personalized `BaselineManager` (`baselines.py`)<br>• Model evaluation scripts & Kaggle dataset preprocessing | Isolation Forest algorithm, 38 feature derivations, baseline personalization, cold-start handling, synthetic evaluation, and ML vs. rule engine clinical defense. |

---

## 8. Challenging Examiner Questions & Defensible Answers

### Q1: "Why did you use two databases? Isn't polyglot persistence unnecessary complexity for a student project?"
**Defensible Answer:**
"In production healthcare systems, attempting to force both transactional integrity and high-volume time-series telemetry into a single database creates fatal operational trade-offs:
- If you use only MySQL, high-frequency telemetry ingestion causes write amplification, table locking, and buffer pool churn, degrading transactional responsiveness.
- If you use only MongoDB, you lose declarative foreign key integrity, domain CHECK constraints, and native ACID procedural safety needed for patient admission, discharge, and clinical auditing.
Our polyglot architecture demonstrates real-world software engineering: we decoupled the operational System of Record from the analytical System of Engagement using the Transactional Outbox pattern, proving that both consistency and velocity can be achieved simultaneously."

---

### Q2: "Where is the Flutter mobile patient application mentioned in some requirements?"
**Defensible Answer:**
"To maintain strict academic and professional integrity, we explicitly declare that the Flutter mobile application is a **planned external integration component** and is not packaged within the current repository workspace. 
All patient telemetry ingestion and historical viewing capabilities are fully implemented, verified, and demonstrated through our RESTful ingestion endpoints (`POST /api/v1/vitals/`) and real Kaggle healthcare dataset bulk replay scripts. We have documented this scope boundary transparently across our compliance matrix."

---

### Q3: "What happens if an attacker tampers with a doctor's JWT token?"
**Defensible Answer:**
"FastAPI uses HMAC-SHA256 cryptographic signatures. When a JWT is received, the gateway recalculates the signature using our secret `JWT_SECRET_KEY`. If even a single character in the payload (such as altering the role from `PATIENT` to `DOCTOR`) is modified, the signature validation fails immediately, and FastAPI aborts the request with an HTTP 401 Unauthorized before any route handler executes."

---

### Q4: "Why did you use an unsupervised anomaly detector instead of a neural network or LSTM?"
**Defensible Answer:**
"Recurrent neural networks (LSTMs) require tens of thousands of continuous, labeled multi-channel sequences to converge, are prone to overfitting on small patient cohorts, and operate as uninterpretable black boxes. 
Isolation Forest has a linear time complexity $\mathcal{O}(n)$, requires low memory, runs inference in sub-millisecond time, and provides transparent feature contribution rankings. In clinical decision support, explainability and low computational latency are paramount."
