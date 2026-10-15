-- ============================================================================
-- SMART HEALTH MONITORING SYSTEM — AUTHORITATIVE MYSQL 8 DEMONSTRATION SCRIPT
-- Digital Assignment 3 (DA3) Live Evaluation & Database Systems Defense
-- Target Database Engine: MySQL 8.0+ (InnoDB Storage Engine)
-- Target Database: smart_health
-- Invariant Safety: All write operations isolated to designated EVAL_* records.
-- ============================================================================

USE smart_health;

-- ============================================================================
-- 1. SELECT WITH FILTERING, PROJECTION & SORTING
-- ============================================================================
-- Objective: Retrieve physiological telemetry for patient P101 ordered chronologically descending.
SELECT 
    reading_id,
    patient_id,
    metric_code,
    value,
    unit,
    measured_at,
    quality_status
FROM vitals_readings
WHERE patient_id = 'P101'
  AND metric_code = 'heart_rate'
ORDER BY measured_at DESC
LIMIT 10;

-- ============================================================================
-- 2. SAFE CRUD LIFECYCLE (DESIGNATED EVALUATION RECORDS)
-- ============================================================================
-- Objective: Demonstrate non-destructive INSERT, RETRIEVE, UPDATE, DELETE with verification.
-- Safety: Operations confined strictly to EVAL_* records; genuine patients (P101-P105) untouched.

-- Step 2A: Verify non-existence before creation
SELECT COUNT(*) AS pre_insert_count 
FROM evaluation_records 
WHERE record_id = 'EVAL_MYSQL_DEMO_01';

-- Step 2B: Explicit Transaction INSERT
START TRANSACTION;
INSERT INTO evaluation_records (
    record_id,
    patient_id,
    record_type,
    title,
    content_text,
    status,
    created_by,
    created_at,
    updated_at
) VALUES (
    'EVAL_MYSQL_DEMO_01',
    'P101',
    'clinical_note',
    'DA3 MySQL Demonstration Clinical Triage Note',
    'Patient recovering satisfactorily; baseline physiological parameters within tolerance.',
    'ACTIVE',
    'eval_doctor',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);
COMMIT;

-- Step 2C: Verify Insertion
SELECT record_id, patient_id, title, status, created_at 
FROM evaluation_records 
WHERE record_id = 'EVAL_MYSQL_DEMO_01';

-- Step 2D: UPDATE Allowed Field
START TRANSACTION;
UPDATE evaluation_records 
SET title = 'DA3 MySQL Demonstration Clinical Triage Note - UPDATED & VERIFIED',
    status = 'VERIFIED',
    updated_at = CURRENT_TIMESTAMP
WHERE record_id = 'EVAL_MYSQL_DEMO_01';
COMMIT;

-- Step 2E: Verify Update
SELECT record_id, title, status, updated_at 
FROM evaluation_records 
WHERE record_id = 'EVAL_MYSQL_DEMO_01';

-- Step 2F: DELETE Designated Evaluation Record
START TRANSACTION;
DELETE FROM evaluation_records 
WHERE record_id = 'EVAL_MYSQL_DEMO_01';
COMMIT;

-- Step 2G: Verify Deletion (Must return 0 rows)
SELECT record_id FROM evaluation_records WHERE record_id = 'EVAL_MYSQL_DEMO_01';

-- Step 2H: Confirm Baseline Patient Data Invariant (Must return 5)
SELECT COUNT(*) AS baseline_patient_count 
FROM patient_profiles 
WHERE patient_id IN ('P101', 'P102', 'P103', 'P104', 'P105');

-- ============================================================================
-- 3. INNER JOIN & MULTI-TABLE JOINS
-- ============================================================================
-- Objective: Join patient master records with normalized vitals and clinical alerts.

-- 3A: Two-Table Inner Join (Profiles ⋈ Vitals)
SELECT 
    p.patient_id,
    p.first_name,
    p.last_name,
    p.gender,
    v.metric_code,
    v.value,
    v.unit,
    v.measured_at
FROM patient_profiles p
INNER JOIN vitals_readings v ON p.patient_id = v.patient_id
WHERE p.patient_id = 'P101'
  AND v.metric_code = 'heart_rate'
ORDER BY v.measured_at DESC
LIMIT 5;

-- 3B: Multi-Table Join (Alerts ⋈ Profiles ⟕ Assignments ⟕ Doctors ⟕ Users)
SELECT 
    a.alert_id,
    a.patient_id,
    p.first_name AS patient_first_name,
    p.last_name AS patient_last_name,
    dpa.doctor_id,
    dp.first_name AS doctor_first_name,
    dp.last_name AS doctor_last_name,
    u.email AS doctor_email,
    a.severity,
    a.status,
    a.category,
    a.reason,
    a.created_at
FROM alerts a
INNER JOIN patient_profiles p ON a.patient_id = p.patient_id
LEFT JOIN doctor_patient_assignments dpa ON p.patient_id = dpa.patient_id AND dpa.is_active = 1
LEFT JOIN doctor_profiles dp ON dpa.doctor_id = dp.doctor_id
LEFT JOIN users u ON dp.user_id = u.user_id
WHERE a.patient_id = 'P101'
ORDER BY a.created_at DESC
LIMIT 5;

-- ============================================================================
-- 4. NESTED SUBQUERIES & COMMON TABLE EXPRESSIONS (CTEs)
-- ============================================================================

-- 4A: Common Table Expression with Window Function (ROW_NUMBER)
-- Retrieves the single latest vital measurement per metric code for patient P101
WITH ranked_vitals AS (
    SELECT 
        reading_id,
        patient_id,
        metric_code,
        value,
        unit,
        measured_at,
        ROW_NUMBER() OVER (
            PARTITION BY metric_code 
            ORDER BY measured_at DESC
        ) AS rn
    FROM vitals_readings
    WHERE patient_id = 'P101'
)
SELECT 
    reading_id,
    patient_id,
    metric_code,
    value,
    unit,
    measured_at
FROM ranked_vitals
WHERE rn = 1
ORDER BY metric_code;

-- 4B: Scalar Nested Subquery (Correlated Filtering)
-- Retrieves vital observations that exceed the patient's individual mean heart rate
SELECT 
    reading_id,
    patient_id,
    metric_code,
    value,
    unit,
    measured_at
FROM vitals_readings
WHERE patient_id = 'P101' 
  AND metric_code = 'heart_rate'
  AND value > (
      SELECT AVG(value) 
      FROM vitals_readings 
      WHERE patient_id = 'P101' AND metric_code = 'heart_rate'
  )
ORDER BY value DESC
LIMIT 5;

-- ============================================================================
-- 5. AGGREGATE FUNCTIONS & GROUP BY / HAVING
-- ============================================================================

-- 5A: Statistical Moments per Physiological Metric (COUNT, AVG, MIN, MAX)
SELECT 
    metric_code,
    COUNT(*) AS total_samples,
    ROUND(AVG(value), 2) AS mean_value,
    ROUND(MIN(value), 2) AS min_value,
    ROUND(MAX(value), 2) AS max_value,
    ROUND(STDDEV(value), 2) AS std_deviation
FROM vitals_readings
WHERE patient_id = 'P101'
GROUP BY metric_code
ORDER BY metric_code;

-- 5B: Cohort Group By with HAVING Clause
-- Aggregates heart rate across all cohort patients and filters for patients with > 5 observations
SELECT 
    patient_id,
    COUNT(*) AS sample_count,
    ROUND(AVG(value), 2) AS avg_heart_rate,
    MIN(value) AS min_hr,
    MAX(value) AS max_hr
FROM vitals_readings
WHERE metric_code = 'heart_rate'
GROUP BY patient_id
HAVING COUNT(*) > 5
ORDER BY avg_heart_rate DESC;

-- ============================================================================
-- 6. RELATIONAL VIEWS
-- ============================================================================

-- 6A: Query Compiled View: v_latest_patient_vitals
SELECT 
    reading_id,
    patient_id,
    metric_code,
    value,
    unit,
    quality_status,
    measured_at
FROM v_latest_patient_vitals
WHERE patient_id = 'P101';

-- 6B: Query Compiled View: v_patient_active_alerts
SELECT 
    alert_id,
    patient_id,
    patient_first_name,
    patient_last_name,
    severity,
    category,
    status,
    created_at
FROM v_patient_active_alerts
WHERE patient_id = 'P101';

-- ============================================================================
-- 7. STORED FUNCTIONS & STORED PROCEDURES
-- ============================================================================

-- 7A: Stored Function Execution: fn_calculate_bmi
SELECT 
    patient_id,
    height_cm,
    weight_kg,
    fn_calculate_bmi(weight_kg, height_cm) AS computed_bmi
FROM patient_profiles
WHERE patient_id = 'P101';

-- 7B: Stored Function Execution: fn_calculate_fever_category
SELECT 
    reading_id,
    value AS temp_f,
    fn_calculate_fever_category(value) AS fever_classification
FROM vitals_readings
WHERE metric_code = 'temperature'
LIMIT 5;

-- 7C: Stored Procedure Execution: sp_acknowledge_alert (ACID Transaction)
-- Finds an active alert and performs transactional state change
SET @target_alert_id = (SELECT alert_id FROM alerts WHERE status = 'NEW' LIMIT 1);
CALL sp_acknowledge_alert(@target_alert_id, 'DOC_001', 'Clinical acknowledgement via DA3 demo');

-- Verify Alert Status Updated
SELECT alert_id, status, acknowledged_by, acknowledged_at 
FROM alerts 
WHERE alert_id = @target_alert_id;

-- ============================================================================
-- 8. DATABASE TRIGGERS & AUDIT INSPECTION
-- ============================================================================
-- Objective: Demonstrate automatic execution of trg_alert_status_history_after_update.

-- Verify that the trigger created a history entry from procedure execution
SELECT 
    history_id,
    alert_id,
    old_status,
    new_status,
    actor_id,
    note,
    changed_at
FROM alert_status_history
WHERE alert_id = @target_alert_id
ORDER BY changed_at DESC
LIMIT 1;

-- ============================================================================
-- 9. INDEX INSPECTION & QUERY EXECUTION PLANS (EXPLAIN)
-- ============================================================================

-- 9A: Index Metadata Inspection
SHOW INDEX FROM vitals_readings;

-- 9B: EXPLAIN Execution Plan Comparison
-- Query 1: Indexed Composite B-Tree Query (patient_id + metric_code + measured_at)
EXPLAIN 
SELECT reading_id, value, measured_at
FROM vitals_readings
WHERE patient_id = 'P101' AND metric_code = 'heart_rate'
ORDER BY measured_at DESC;

-- Query 2: Unindexed Non-Key Query (Force Full Table Scan)
EXPLAIN 
SELECT reading_id, value, measured_at
FROM vitals_readings
WHERE raw_value > 100.0;
