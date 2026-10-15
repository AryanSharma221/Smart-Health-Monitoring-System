# DA3 Technical Viva Voce & Oral Defense Preparation Guide

**Project:** AI-Powered Smart Health Monitoring System  
**Academic Milestone:** Digital Assignment 3 (DA3) Comprehensive Technical Defense & Viva Voce  
**Examiner Target:** Academic Committee, Database Systems Professor & Systems Examiners  
**System Version:** `3.0.0-final`  
**Core Technologies:** FastAPI Core Gateway, MySQL 8 InnoDB / SQLite 3, MongoDB Atlas Cloud, Scikit-learn (Isolation Forest), React 19 Workstation, Streamlit Visualizer  

---

## 1. Architectural Defense: Why Polyglot Persistence?

### 1.1 The Fundamental Healthcare Storage Conflict
Healthcare monitoring platforms must simultaneously satisfy two contradictory operational requirements:
1. **High-Integrity Clinical Transactions (Operational EHR):**
   - Patient demographics, medical history, user credentials, role permissions, clinical alert states, and clinician assignments demand strict ACID guarantees, declarative foreign key integrity, non-repudiable audit trails, and deterministic relational schemas.
   - **Solution:** **MySQL 8.0 InnoDB** (and local embedded **SQLite 3**) operating as the authoritative *System of Record*.
2. **High-Velocity Time-Series Analytics (Streaming Telemetry):**
   - Continuous physiological telemetry streams (heart rate, SpO2, blood pressure, temperature at 1 Hz from wearable smartwatches) generate millions of data points requiring flexible indexing, high ingestion throughput, horizontal scaling, and multi-stage analytical aggregations without locking operational EHR tables.
   - **Solution:** **MongoDB Atlas** operating as the analytical *System of Analysis*.

### 1.2 The Transactional Outbox Pattern & Failure Isolation
* **Atomic Ingestion:** When patient telemetry arrives via `POST /api/v1/vitals/`:
  1. Telemetry readings are inserted into `vitals_readings`.
  2. If a clinical threshold is breached, a `clinical_alerts` record is inserted.
  3. An outbox event is enqueued into `analytics_outbox` with status `PENDING` within the **same atomic relational transaction**.
* **Decoupled Synchronization:** A decoupled background worker polls `analytics_outbox` and mirrors batches into MongoDB Atlas using idempotent operations (`replace_one(filter={"source_event_id": id}, replacement=doc, upsert=True)`).
* **Fault Tolerance & Partition Tolerance (CAP Theorem):**
  - If MongoDB Atlas becomes unreachable due to an internet outage or network partition, operational patient care and relational EHR transactions proceed uninterrupted. Events accumulate safely in `analytics_outbox` and sync automatically when connectivity is restored.
  - The system favors **Consistency & Partition Tolerance (CP)** for the EHR, and **Availability & Eventual Consistency (AP)** for the analytical telemetry mirror.

---

## 2. Relational Database Systems Theory & Normalization

### 2.1 Formal Normalization Decomposition & BCNF Proof

Our relational schema comprises 17 authoritative tables designed in **Third Normal Form (3NF)** and **Boyce-Codd Normal Form (BCNF)**.

#### Step 1: Universal Relation ($U$)
$$U = \{\text{patient\_id}, \text{first\_name}, \text{last\_name}, \text{dob}, \text{gender}, \text{blood\_group}, \text{doctor\_id}, \text{doc\_name}, \text{license\_no}, \text{specialty}, \text{reading\_id}, \text{metric\_code}, \text{value}, \text{unit}, \text{measured\_at}, \text{alert\_id}, \text{severity}, \text{status}, \text{alert\_time}\}$$

#### Step 2: First Normal Form (1NF)
* Every column stores strictly atomic, indivisible values. Multi-valued fields (e.g. multiple vital readings or assigned doctors) are decomposed into discrete rows. Units, timestamps, and metric codes are stored in separate attributes.

#### Step 3: Second Normal Form (2NF)
* All non-prime attributes are fully functionally dependent on candidate keys.
* Partial dependencies on composite keys are eliminated:
  - In `doctor_patient_assignments(doctor_id, patient_id, assigned_at, is_active)`, the primary key is `(doctor_id, patient_id)`. Non-prime attributes (`assigned_at`, `is_active`) depend on the complete composite key, not on a subset.

#### Step 4: Third Normal Form (3NF) & BCNF Proof
* Transitive dependencies are eliminated. We decoupled user authentication credentials (`users`) from clinical patient profiles (`patient_profiles`) and doctor profiles (`doctor_profiles`).
* **Formal BCNF Theorem:** A relation $R$ is in BCNF if for every non-trivial functional dependency $X \to Y$ in $F^+$, the determinant $X$ is a superkey of $R$.
* **Proof for `vitals_readings`:**
  - Dependencies:
    $$FD_1: \text{reading\_id} \to \{\text{patient\_id}, \text{metric\_code}, \text{value}, \text{unit}, \text{measured\_at}, \text{quality\_status}\}$$
    $$FD_2: \{\text{patient\_id}, \text{metric\_code}, \text{measured\_at}\} \to \{\text{reading\_id}, \text{value}, \text{unit}, \text{quality\_status}\}$$
  - Candidate Keys: $K_1 = \{\text{reading\_id}\}$, $K_2 = \{\text{patient\_id}, \text{metric\_code}, \text{measured\_at}\}$.
  - For $FD_1$, $X = \{\text{reading\_id}\}$ is a superkey.
  - For $FD_2$, $X = \{\text{patient\_id}, \text{metric\_code}, \text{measured\_at}\}$ is a superkey.
  - Therefore, `vitals_readings` is in strict BCNF.

#### Step 5: Lossless Join & Dependency Preservation
* **Lossless Join Proof:** For any decomposition $R \to (R_1, R_2)$, the join is lossless if and only if:
  $$R_1 \cap R_2 \to R_1 \quad \text{or} \quad R_1 \cap R_2 \to R_2$$
  For `patient_profiles` ($R_1$) and `vitals_readings` ($R_2$):
  $$R_1 \cap R_2 = \{\text{patient\_id}\}$$
  Because $\text{patient\_id}$ is the primary key of $R_1$, $\{\text{patient\_id}\} \to R_1$ holds. The decomposition is mathematically lossless.

---

## 3. Database Objects: Triggers, Procedures & Views

### 3.1 Stored Procedure with Named Savepoints: `sp_safe_patient_discharge`
Healthcare safety demands that a patient cannot be discharged while experiencing critical physiological instability:
```sql
DELIMITER //
CREATE PROCEDURE sp_safe_patient_discharge(
    IN p_patient_id VARCHAR(32),
    OUT p_success BOOLEAN,
    OUT p_message VARCHAR(255)
)
BEGIN
    DECLARE active_critical_count INT DEFAULT 0;
    
    START TRANSACTION;
    SAVEPOINT before_discharge;
    
    -- Safety check: inspect unresolved CRITICAL or HIGH alerts
    SELECT COUNT(*) INTO active_critical_count
    FROM alerts
    WHERE patient_id = p_patient_id
      AND severity IN ('HIGH', 'CRITICAL')
      AND status = 'ACTIVE';
      
    IF active_critical_count > 0 THEN
        -- Abort discharge and rollback to savepoint
        ROLLBACK TO SAVEPOINT before_discharge;
        SET p_success = FALSE;
        SET p_message = CONCAT('Cannot discharge patient with ', active_critical_count, ' active CRITICAL/HIGH alerts.');
    ELSE
        -- Perform discharge transaction
        UPDATE patient_profiles
        SET is_active = 0, discharge_date = NOW()
        WHERE patient_id = p_patient_id;
        
        UPDATE doctor_patient_assignments
        SET is_active = 0
        WHERE patient_id = p_patient_id;
        
        COMMIT;
        SET p_success = TRUE;
        SET p_message = 'Patient discharged successfully.';
    END IF;
END //
DELIMITER ;
```

### 3.2 Automated Audit Trigger: `trg_alert_status_history_after_update`
Ensures regulatory compliance (HIPAA / FDA CFR Part 11 non-repudiation) by recording every alert state transition:
```sql
CREATE TRIGGER trg_alert_status_history_after_update
AFTER UPDATE ON alerts
FOR EACH ROW
BEGIN
    IF OLD.status != NEW.status THEN
        INSERT INTO alert_status_history (
            history_id, alert_id, old_status, new_status,
            changed_by, changed_at, reason
        ) VALUES (
            UUID(), NEW.alert_id, OLD.status, NEW.status,
            COALESCE(NEW.assigned_to, 'system'), NOW(), NEW.reason
        );
    END IF;
END;
```

### 3.3 Compiled Relational Views
* `v_latest_patient_vitals`: Pre-compiles correlated subqueries to retrieve the single latest reading per metric code for each patient, reducing application-side query complexity from $O(N \cdot M)$ to a single indexed lookup.
* `v_patient_active_alerts`: Joins `alerts`, `patient_profiles`, and `doctor_patient_assignments` to provide real-time triage queues for hospital staff.

---

## 4. B-Tree Indexes & Execution Plan Optimization

### 4.1 Covering B-Tree Index Design
* **Composite Index:** `idx_vitals_patient_metric_time` on `(patient_id, metric_code, measured_at DESC)`
* **Why B-Tree?** B-Tree indexes provide $O(\log N)$ search complexity and support efficient range queries (`measured_at >= :start_time AND measured_at <= :end_time`) and ordered scans (`ORDER BY measured_at DESC`).
* **Covering Index Advantage:** Because the index contains `patient_id`, `metric_code`, and `measured_at`, point lookups and temporal boundary checks are satisfied directly from the B-Tree leaf pages without performing secondary page reads against the base table data.

### 4.2 Empirical Execution Plan Comparison
```
EXPLAIN QUERY PLAN
SELECT value, unit, measured_at 
FROM vitals_readings 
WHERE patient_id = 'P101' AND metric_code = 'heart_rate' 
ORDER BY measured_at DESC LIMIT 5;
```
* **Indexed Execution Plan:** `SEARCH TABLE vitals_readings USING INDEX idx_vitals_patient_metric_time (patient_id=? AND metric_code=?)` $\to$ **Execution Time: 0.03 ms** (5 rows scanned).
* **Unindexed Execution Plan:** `SCAN TABLE vitals_readings` with temporary B-Tree sort $\to$ **Execution Time: 4.75 ms** (1,500 rows scanned).
* **Speedup:** **~158x acceleration** via index coverage.

---

## 5. MongoDB Atlas Document Design & Aggregation Pipelines

### 5.1 Document Model & Indexing
* **Collection:** `telemetry_events` in database `smart_health_analytics`.
* **Document Structure:**
  ```json
  {
    "_id": {"$oid": "..."},
    "event_id": "evt_p101_1729000000",
    "patient_id": "P101",
    "measured_at": {"$date": "2026-10-15T05:28:27Z"},
    "event_type": "telemetry_frame",
    "source": "smartwatch_v2",
    "metrics": {
      "heart_rate": 72.5,
      "spo2": 98.0,
      "temperature_c": 36.8
    }
  }
  ```
* **Compound Index:** `{ patient_id: 1, measured_at: -1 }`.
* **Index Plan:** Query explain shows `IXSCAN` utilizing the composite index, scanning only targeted index keys rather than `COLLSCAN` full-collection scans.

### 5.2 Multi-Stage Aggregation Pipeline: Hourly Population Vitals
```javascript
db.telemetry_events.aggregate([
  // Stage 1: Filter to target cohort and valid event types
  { $match: { patient_id: "P101", event_type: "telemetry_frame" } },
  
  // Stage 2: Extract date trunc and physiological values
  { $project: {
      hour_bucket: { $dateTrunc: { date: "$measured_at", unit: "hour" } },
      heart_rate: "$metrics.heart_rate",
      spo2: "$metrics.spo2"
  }},
  
  // Stage 3: Compute statistical moments grouped by hourly bucket
  { $group: {
      _id: "$hour_bucket",
      sample_count: { $sum: 1 },
      avg_heart_rate: { $avg: "$heart_rate" },
      min_heart_rate: { $min: "$heart_rate" },
      max_heart_rate: { $max: "$heart_rate" },
      avg_spo2: { $avg: "$spo2" }
  }},
  
  // Stage 4: Sort chronologically
  { $sort: { _id: -1 } }
]);
```
* **Execution Time on Live Atlas Cluster:** **52.72 ms** across 2,955 documents.
* **Safety Restriction:** Stages `$out` and `$merge` are strictly forbidden to enforce the read-only invariant.

---

## 6. Top 25 Rigorous Viva Voce Examination Questions & Model Answers

### Q1: Why did you choose a hybrid relational + NoSQL architecture instead of pure MySQL or pure MongoDB?
**Model Answer:**  
"A hospital monitoring platform has two conflicting access patterns: transactional EHR records (patients, clinicians, alerts, role permissions) require strict ACID guarantees, declarative foreign keys, and non-repudiation audit trails—which MySQL InnoDB provides. However, wearable devices produce high-velocity timeseries telemetry (1 Hz continuous readings) that would bloat relational tables and cause lock contention during reporting aggregations. By streaming raw timeseries into MongoDB Atlas and maintaining transactional state in MySQL, we achieve the best of both worlds: ACID compliance for care decisions, and horizontal scalability for analytical telemetry."

---

### Q2: How does your database prevent the loss of data if the MongoDB cloud cluster goes down?
**Model Answer:**  
"We implemented the **Transactional Outbox Pattern**. When a vital reading is ingested, it is committed to MySQL alongside a record in the `analytics_outbox` table within the same atomic ACID transaction. A decoupled worker processes the outbox and mirrors data to MongoDB Atlas. If Atlas becomes unreachable, MySQL transactions continue normally; pending events buffer safely in `analytics_outbox` and sync automatically when connectivity is restored."

---

### Q3: What is the difference between 3NF and BCNF? Give an example from your schema.
**Model Answer:**  
"A relation is in 3NF if for every functional dependency $X \to Y$, either $X$ is a superkey or $Y$ is a prime attribute (part of a candidate key). BCNF is stricter: it requires $X$ to be a superkey *without exception*, eliminating dependencies where non-prime attributes determine parts of candidate keys. In our `vitals_readings` table, candidate keys are `reading_id` and `(patient_id, metric_code, measured_at)`. Every determinant in the relation is a superkey, satisfying strict BCNF."

---

### Q4: Explain how your application enforces the Core EHR Immutability Guard during deletion.
**Model Answer:**  
"To protect baseline Kaggle patient records (`P001`–`P005` and `P101`–`P105`) from accidental deletion during professor evaluation, our backend API intercepts all DELETE requests. If the target record belongs to a baseline patient or does not carry the designated evaluation prefix (`EVAL_*`), the service rejects the request with **HTTP 403 Forbidden**. Deletions are permitted only on isolated test fixtures in the `evaluation_records` table."

---

### Q5: How does `sp_safe_patient_discharge` use ACID transactions and savepoints?
**Model Answer:**  
"Discharging a patient who still has active critical emergencies is a fatal hazard. `sp_safe_patient_discharge` initiates a transaction with a named savepoint `before_discharge`. It queries `alerts` for unresolved CRITICAL or HIGH alerts. If any are found, it executes `ROLLBACK TO SAVEPOINT before_discharge` and returns an error message. If none exist, it marks the patient inactive, releases doctor assignments, and commits the transaction atomically."

---

### Q6: How does the database trigger `trg_alert_status_history_after_update` work?
**Model Answer:**  
"The trigger fires `AFTER UPDATE` on the `alerts` table. It compares `OLD.status` with `NEW.status`. If the status has changed (e.g. from `ACTIVE` to `ACKNOWLEDGED`), it automatically inserts an audit row into `alert_status_history` containing the alert ID, previous status, new status, modifier user ID, and a server-side timestamp. This guarantees HIPAA compliance even if an update is executed directly via SQL."

---

### Q7: What is a covering index and why is `idx_vitals_patient_metric_time` considered covering?
**Model Answer:**  
"A covering index is a secondary B-Tree index that contains all columns required by a query, allowing the database engine to satisfy the request directly from the index tree without performing a second lookup against the primary clustered table pages. In our query:
```sql
SELECT value, unit, measured_at FROM vitals_readings WHERE patient_id='P101' AND metric_code='heart_rate' ORDER BY measured_at DESC LIMIT 5;
```
`idx_vitals_patient_metric_time` covers `patient_id`, `metric_code`, and `measured_at`, reducing query execution time from 4.75 ms to 0.03 ms—a 158x acceleration."

---

### Q8: What is the read-only invariant on MongoDB Atlas and how is it verified?
**Model Answer:**  
"The MongoDB Atlas cluster `cluster0.offnaie.mongodb.net` contains exactly **2,955 documents** in `smart_health_analytics.telemetry_events`. We enforce a strict read-only restriction by setting `MONGODB_SYNC_ENABLED=false` in configuration and restricting API routes to read-only operations (`find`, `aggregate`, `list_indexes`, `explain`). Our test runners and preflight checks verify that the document count remains strictly 2,955 before, during, and after all live demonstrations."

---

### Q9: How does your Isolation Forest ML model detect anomalies in patient vitals?
**Model Answer:**  
"Isolation Forest is an unsupervised tree-based ensemble algorithm that isolates anomalies by randomly selecting a feature and a split value. Because anomalous physiological readings (e.g. sudden tachycardia with SpO2 drop) deviate significantly from normal distributions, they require fewer random splits to isolate and appear at shorter path lengths in the trees. Our model evaluates a 38-dimensional feature vector, adjusts for personal baseline drift via `BaselineManager`, and outputs a continuous score $\in [0, 1]$, where scores $> 0.65$ trigger clinical alerts."

---

### Q10: How do you prevent SQL injection in your API gateway?
**Model Answer:**  
"All database interactions use parameterized queries through SQLAlchemy and typed Pydantic models. Input parameters (such as `patient_id` and `metric_code`) are bound as typed query parameters rather than concatenated into SQL strings. In addition, the DA3 Evaluation Console uses a strictly whitelisted catalog of named queries, preventing execution of arbitrary user-supplied SQL text."

---

## 7. Viva Voce Quick-Reference Fact Sheet

* **Relational Database Engine:** MySQL 8.0 InnoDB (production DDL) / SQLite 3 (local standalone demonstration).
* **Relational Schema:** 17 production tables + 1 isolated evaluation table (`evaluation_records`).
* **Relational Views:** 2 pre-compiled views (`v_latest_patient_vitals`, `v_patient_active_alerts`).
* **Triggers:** 1 active audit trigger (`trg_alert_status_history_after_update`).
* **Stored Routines:** 3 procedures (`sp_acknowledge_alert`, `sp_evaluate_patient_alerts`, `sp_safe_patient_discharge`) and 2 functions (`fn_calculate_bmi`, `fn_calculate_fever_category`).
* **NoSQL Database:** MongoDB Atlas (`cluster0.offnaie.mongodb.net`, 2,955 invariant documents).
* **Baseline Cohort:** 1,500 historical Kaggle records across `P101`–`P105` and `P001`–`P005`.
* **ML Model:** Isolation Forest (v1.0.0, 38 physiological features, continuous score $\in [0, 1]$).
* **Test Verification:** **74 / 74 assertions PASS (100%)**; **34 / 34 preflight checks PASS (100%)**.
