-- ============================================================================
-- SMART HEALTH MONITORING SYSTEM — SQLITE 3 DEMONSTRATION SCRIPT
-- Digital Assignment 3 (DA3) Live Evaluation & Local Database Defense
-- Target Database: smart_health_local.db
-- Invariant Safety: All write operations isolated to designated EVAL_* records.
-- ============================================================================

.headers on
.mode column
.timer on

-- 1. SELECT WITH FILTERING AND SORTING
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
LIMIT 5;

-- 2. SAFE EVALUATION CRUD LIFECYCLE
-- 2A: Verify pre-insert state
SELECT COUNT(*) AS pre_insert_count FROM evaluation_records WHERE record_id = 'EVAL_SQLITE_DEMO_01';

-- 2B: Explicit Transaction INSERT
BEGIN TRANSACTION;
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
    'EVAL_SQLITE_DEMO_01',
    'P101',
    'clinical_note',
    'DA3 SQLite Demonstration Clinical Triage Note',
    'Patient recovering satisfactorily; baseline physiological parameters within tolerance.',
    'ACTIVE',
    'eval_doctor',
    datetime('now'),
    datetime('now')
);
COMMIT;

-- 2C: Verify Insertion
SELECT record_id, patient_id, title, status, created_at 
FROM evaluation_records 
WHERE record_id = 'EVAL_SQLITE_DEMO_01';

-- 2D: UPDATE Allowed Field
BEGIN TRANSACTION;
UPDATE evaluation_records 
SET title = 'DA3 SQLite Demonstration Clinical Triage Note - UPDATED & VERIFIED',
    status = 'VERIFIED',
    updated_at = datetime('now')
WHERE record_id = 'EVAL_SQLITE_DEMO_01';
COMMIT;

-- 2E: Verify Update
SELECT record_id, title, status, updated_at 
FROM evaluation_records 
WHERE record_id = 'EVAL_SQLITE_DEMO_01';

-- 2F: DELETE Designated Evaluation Record
BEGIN TRANSACTION;
DELETE FROM evaluation_records 
WHERE record_id = 'EVAL_SQLITE_DEMO_01';
COMMIT;

-- 2G: Verify Deletion (0 rows)
SELECT record_id FROM evaluation_records WHERE record_id = 'EVAL_SQLITE_DEMO_01';

-- 2H: Confirm Baseline EHR Invariant (Must be 5)
SELECT COUNT(*) AS baseline_patient_count 
FROM patient_profiles 
WHERE patient_id IN ('P101', 'P102', 'P103', 'P104', 'P105');

-- 3. INNER JOIN & MULTI-TABLE JOINS
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

SELECT 
    a.alert_id,
    a.patient_id,
    p.first_name AS patient_first_name,
    p.last_name AS patient_last_name,
    dpa.doctor_id,
    a.severity,
    a.status,
    a.reason,
    a.created_at
FROM alerts a
INNER JOIN patient_profiles p ON a.patient_id = p.patient_id
LEFT JOIN doctor_patient_assignments dpa ON p.patient_id = dpa.patient_id AND dpa.is_active = 1
WHERE a.patient_id = 'P101'
ORDER BY a.created_at DESC
LIMIT 5;

-- 4. NESTED SUBQUERIES & COMMON TABLE EXPRESSIONS (CTEs)
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

-- 5. AGGREGATE FUNCTIONS & GROUP BY / HAVING
SELECT 
    metric_code,
    COUNT(*) AS total_samples,
    ROUND(AVG(value), 2) AS mean_value,
    ROUND(MIN(value), 2) AS min_value,
    ROUND(MAX(value), 2) AS max_value
FROM vitals_readings
WHERE patient_id = 'P101'
GROUP BY metric_code
ORDER BY metric_code;

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

-- 6. RELATIONAL VIEWS
SELECT * FROM v_latest_patient_vitals WHERE patient_id = 'P101';
SELECT * FROM v_patient_active_alerts WHERE patient_id = 'P101' LIMIT 5;

-- 7. DATABASE TRIGGER INSPECTION
SELECT history_id, alert_id, old_status, new_status, changed_at, note 
FROM alert_status_history 
ORDER BY changed_at DESC 
LIMIT 3;

-- 8. INDEX INSPECTION & EXPLAIN QUERY PLAN
PRAGMA index_list('vitals_readings');

EXPLAIN QUERY PLAN
SELECT reading_id, value, measured_at
FROM vitals_readings
WHERE patient_id = 'P101' AND metric_code = 'heart_rate'
ORDER BY measured_at DESC;
