-- =====================================================================
-- SMART HEALTH MONITORING SYSTEM — AUTHORITATIVE MYSQL 8 RELATIONAL DDL
-- Engine: InnoDB | Character Set: utf8mb4 | Collation: utf8mb4_unicode_ci
-- =====================================================================

-- ---------------------------------------------------------------------
-- Database Initialization (Optional: adjust if using pre-created DB)
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS smart_health 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

USE smart_health;

-- =====================================================================
-- 1. DATASET IMPORT PROVENANCE & MANIFEST
-- =====================================================================

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id VARCHAR(64) NOT NULL,
    source_name VARCHAR(64) NOT NULL COMMENT 'Origin (e.g. kaggle_csv, ehr_export)',
    filename VARCHAR(255) NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    row_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL DEFAULT NULL,
    metadata_json TEXT NULL,
    CONSTRAINT pk_import_batches PRIMARY KEY (batch_id),
    CONSTRAINT ck_import_batches_status CHECK (status IN ('pending', 'completed', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
-- 2. IDENTITY AND ACCESS CONTROL
-- =====================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT pk_users PRIMARY KEY (user_id),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_role CHECK (role IN ('patient', 'doctor', 'admin_operator'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS patient_profiles (
    patient_id VARCHAR(32) NOT NULL COMMENT 'Domain ID (e.g. P101-P105 in Kaggle dataset)',
    user_id VARCHAR(64) NOT NULL,
    first_name VARCHAR(64) NOT NULL,
    last_name VARCHAR(64) NOT NULL,
    date_of_birth DATE NULL,
    gender VARCHAR(16) NULL,
    height_cm DECIMAL(5, 2) NULL,
    weight_kg DECIMAL(5, 2) NULL,
    contact_phone VARCHAR(32) NULL,
    emergency_contact VARCHAR(64) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT pk_patient_profiles PRIMARY KEY (patient_id),
    CONSTRAINT uq_patient_user UNIQUE (user_id),
    CONSTRAINT fk_patient_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT ck_patient_gender CHECK (gender IS NULL OR gender IN ('male', 'female', 'other', 'unknown')),
    CONSTRAINT ck_patient_height_positive CHECK (height_cm IS NULL OR height_cm > 0),
    CONSTRAINT ck_patient_weight_positive CHECK (weight_kg IS NULL OR weight_kg > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS doctor_profiles (
    doctor_id VARCHAR(32) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    first_name VARCHAR(64) NOT NULL,
    last_name VARCHAR(64) NOT NULL,
    specialization VARCHAR(100) NOT NULL DEFAULT 'General Practice',
    license_number VARCHAR(64) NOT NULL,
    contact_phone VARCHAR(32) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT pk_doctor_profiles PRIMARY KEY (doctor_id),
    CONSTRAINT uq_doctor_user UNIQUE (user_id),
    CONSTRAINT uq_doctor_license UNIQUE (license_number),
    CONSTRAINT fk_doctor_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS doctor_patient_assignments (
    doctor_id VARCHAR(32) NOT NULL,
    patient_id VARCHAR(32) NOT NULL,
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NULL,
    CONSTRAINT pk_doctor_patient_assignments PRIMARY KEY (doctor_id, patient_id),
    CONSTRAINT fk_dpa_doctor FOREIGN KEY (doctor_id) REFERENCES doctor_profiles (doctor_id) ON DELETE CASCADE,
    CONSTRAINT fk_dpa_patient FOREIGN KEY (patient_id) REFERENCES patient_profiles (patient_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_assignments_patient ON doctor_patient_assignments (patient_id);
CREATE INDEX idx_assignments_doctor_active ON doctor_patient_assignments (doctor_id, is_active);

-- =====================================================================
-- 3. INGESTION EVENTS & CANONICAL VITALS READINGS
-- =====================================================================

CREATE TABLE IF NOT EXISTS ingestion_events (
    event_id VARCHAR(64) NOT NULL,
    patient_id VARCHAR(32) NOT NULL,
    source VARCHAR(32) NOT NULL COMMENT 'e.g. kaggle_csv, demo_simulator',
    source_event_id VARCHAR(128) NOT NULL COMMENT 'Idempotency and deduplication key',
    batch_id VARCHAR(64) NULL,
    measured_at TIMESTAMP NOT NULL,
    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_simulated BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'FALSE for historical Kaggle dataset, TRUE for live simulator',
    mirror_status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'DA3 MongoDB Atlas telemetry mirror state',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_ingestion_events PRIMARY KEY (event_id),
    CONSTRAINT fk_events_patient FOREIGN KEY (patient_id) REFERENCES patient_profiles (patient_id) ON DELETE CASCADE,
    CONSTRAINT fk_events_batch FOREIGN KEY (batch_id) REFERENCES import_batches (batch_id) ON DELETE SET NULL,
    CONSTRAINT uq_events_source_source_event_id UNIQUE (source, source_event_id),
    CONSTRAINT ck_events_mirror_status CHECK (mirror_status IN ('pending', 'mirrored', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_events_patient_measured ON ingestion_events (patient_id, measured_at);
CREATE INDEX idx_events_mirror_status ON ingestion_events (mirror_status);

CREATE TABLE IF NOT EXISTS vitals_readings (
    reading_id BIGINT AUTO_INCREMENT,
    event_id VARCHAR(64) NOT NULL,
    patient_id VARCHAR(32) NOT NULL,
    metric_code VARCHAR(32) NOT NULL COMMENT 'heart_rate, spo2, temperature, respiratory_rate, bp_systolic, bp_diastolic',
    value DECIMAL(8, 2) NOT NULL COMMENT 'Canonical value (e.g. Celsius for temp)',
    unit VARCHAR(16) NOT NULL COMMENT 'Canonical unit (bpm, %, degC, breaths/min, mmHg)',
    raw_value DECIMAL(8, 2) NOT NULL COMMENT 'Exact source value as ingested (e.g. Fahrenheit)',
    raw_unit VARCHAR(16) NOT NULL COMMENT 'Exact source unit (e.g. degF)',
    quality_status VARCHAR(16) NOT NULL DEFAULT 'valid',
    measured_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_vitals_readings PRIMARY KEY (reading_id),
    CONSTRAINT fk_vitals_event FOREIGN KEY (event_id) REFERENCES ingestion_events (event_id) ON DELETE CASCADE,
    CONSTRAINT fk_vitals_patient FOREIGN KEY (patient_id) REFERENCES patient_profiles (patient_id) ON DELETE CASCADE,
    CONSTRAINT uq_vitals_event_metric UNIQUE (event_id, metric_code),
    CONSTRAINT ck_vitals_metric_code CHECK (metric_code IN ('heart_rate', 'spo2', 'temperature', 'respiratory_rate', 'bp_systolic', 'bp_diastolic')),
    CONSTRAINT ck_vitals_quality_status CHECK (quality_status IN ('valid', 'out_of_range', 'stale', 'suspect'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Core timeseries query index supporting patient history and chart views
CREATE INDEX idx_vitals_patient_metric_time ON vitals_readings (patient_id, metric_code, measured_at);
CREATE INDEX idx_vitals_measured_at ON vitals_readings (measured_at);

-- =====================================================================
-- 4. CLINICAL THRESHOLD RULES & BASELINES
-- =====================================================================

CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id VARCHAR(32) NOT NULL,
    metric_code VARCHAR(32) NOT NULL,
    operator VARCHAR(8) NOT NULL,
    configured_value DECIMAL(8, 2) NOT NULL,
    duration_seconds INT NOT NULL DEFAULT 0,
    severity VARCHAR(16) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_demo_only BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_alert_rules PRIMARY KEY (rule_id),
    CONSTRAINT ck_alert_rules_operator CHECK (operator IN ('<', '>', '<=', '>=', '==', '!=')),
    CONSTRAINT ck_alert_rules_severity CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS patient_baselines (
    baseline_id VARCHAR(64) NOT NULL,
    patient_id VARCHAR(32) NOT NULL,
    metric_code VARCHAR(32) NOT NULL,
    window_hours INT NOT NULL DEFAULT 24,
    median_value DECIMAL(8, 2) NOT NULL,
    mad_value DECIMAL(8, 2) NOT NULL,
    sample_count INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT pk_patient_baselines PRIMARY KEY (baseline_id),
    CONSTRAINT fk_baselines_patient FOREIGN KEY (patient_id) REFERENCES patient_profiles (patient_id) ON DELETE CASCADE,
    CONSTRAINT uq_patient_metric_window UNIQUE (patient_id, metric_code, window_hours)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
-- 5. MACHINE LEARNING ASSESSMENTS & CLINICAL ALERTS
-- =====================================================================

CREATE TABLE IF NOT EXISTS model_assessments (
    assessment_id VARCHAR(64) NOT NULL,
    patient_id VARCHAR(32) NOT NULL,
    event_id VARCHAR(64) NULL,
    model_version VARCHAR(64) NOT NULL,
    score DECIMAL(6, 4) NOT NULL,
    result VARCHAR(32) NOT NULL,
    features_json TEXT NULL,
    time_window_start TIMESTAMP NULL DEFAULT NULL,
    time_window_end TIMESTAMP NULL DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_model_assessments PRIMARY KEY (assessment_id),
    CONSTRAINT fk_assessments_patient FOREIGN KEY (patient_id) REFERENCES patient_profiles (patient_id) ON DELETE CASCADE,
    CONSTRAINT fk_assessments_event FOREIGN KEY (event_id) REFERENCES ingestion_events (event_id) ON DELETE SET NULL,
    CONSTRAINT ck_assessments_result CHECK (result IN ('normal', 'anomaly', 'inconclusive'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_assessments_patient_time ON model_assessments (patient_id, created_at);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id VARCHAR(64) NOT NULL,
    patient_id VARCHAR(32) NOT NULL,
    event_id VARCHAR(64) NULL,
    assessment_id VARCHAR(64) NULL,
    rule_id VARCHAR(32) NULL,
    severity VARCHAR(16) NOT NULL,
    category VARCHAR(32) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'NEW',
    acknowledged_by VARCHAR(64) NULL,
    acknowledged_at TIMESTAMP NULL DEFAULT NULL,
    resolved_by VARCHAR(64) NULL,
    resolved_at TIMESTAMP NULL DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_alerts PRIMARY KEY (alert_id),
    CONSTRAINT fk_alerts_patient FOREIGN KEY (patient_id) REFERENCES patient_profiles (patient_id) ON DELETE CASCADE,
    CONSTRAINT fk_alerts_event FOREIGN KEY (event_id) REFERENCES ingestion_events (event_id) ON DELETE SET NULL,
    CONSTRAINT fk_alerts_assessment FOREIGN KEY (assessment_id) REFERENCES model_assessments (assessment_id) ON DELETE SET NULL,
    CONSTRAINT fk_alerts_rule FOREIGN KEY (rule_id) REFERENCES alert_rules (rule_id) ON DELETE SET NULL,
    CONSTRAINT fk_alerts_acknowledged_by FOREIGN KEY (acknowledged_by) REFERENCES users (user_id) ON DELETE SET NULL,
    CONSTRAINT fk_alerts_resolved_by FOREIGN KEY (resolved_by) REFERENCES users (user_id) ON DELETE SET NULL,
    CONSTRAINT ck_alerts_severity CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    CONSTRAINT ck_alerts_category CHECK (category IN ('vital_threshold', 'ml_anomaly', 'composite', 'stale_data')),
    CONSTRAINT ck_alerts_status CHECK (status IN ('NEW', 'ACKNOWLEDGED', 'RESOLVED')),
    CONSTRAINT uq_alerts_event_rule UNIQUE (event_id, rule_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_alerts_patient_status_time ON alerts (patient_id, status, created_at);
CREATE INDEX idx_alerts_status_created ON alerts (status, created_at);

CREATE TABLE IF NOT EXISTS alert_status_history (
    history_id BIGINT AUTO_INCREMENT,
    alert_id VARCHAR(64) NOT NULL,
    old_status VARCHAR(16) NULL,
    new_status VARCHAR(16) NOT NULL,
    actor_id VARCHAR(64) NULL,
    note TEXT NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_alert_status_history PRIMARY KEY (history_id),
    CONSTRAINT fk_ash_alert FOREIGN KEY (alert_id) REFERENCES alerts (alert_id) ON DELETE CASCADE,
    CONSTRAINT fk_ash_actor FOREIGN KEY (actor_id) REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_alert_history_alert_time ON alert_status_history (alert_id, changed_at);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    delivery_id VARCHAR(64) NOT NULL,
    alert_id VARCHAR(64) NOT NULL,
    recipient_id VARCHAR(64) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    sent_at TIMESTAMP NULL DEFAULT NULL,
    error_code VARCHAR(64) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_notification_deliveries PRIMARY KEY (delivery_id),
    CONSTRAINT fk_notif_alert FOREIGN KEY (alert_id) REFERENCES alerts (alert_id) ON DELETE CASCADE,
    CONSTRAINT fk_notif_recipient FOREIGN KEY (recipient_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT ck_deliveries_channel CHECK (channel IN ('in_app', 'websocket', 'email', 'sms')),
    CONSTRAINT ck_deliveries_status CHECK (status IN ('pending', 'delivered', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_deliveries_recipient_status ON notification_deliveries (recipient_id, status);

-- =====================================================================
-- 6. DIRECT MESSAGING & SYSTEM AUDIT TRAIL
-- =====================================================================

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id VARCHAR(64) NOT NULL,
    patient_id VARCHAR(32) NOT NULL,
    doctor_id VARCHAR(32) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT pk_conversations PRIMARY KEY (conversation_id),
    CONSTRAINT fk_conversations_patient FOREIGN KEY (patient_id) REFERENCES patient_profiles (patient_id) ON DELETE CASCADE,
    CONSTRAINT fk_conversations_doctor FOREIGN KEY (doctor_id) REFERENCES doctor_profiles (doctor_id) ON DELETE CASCADE,
    CONSTRAINT uq_conversations_patient_doctor UNIQUE (patient_id, doctor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_conversations_patient ON conversations (patient_id);
CREATE INDEX idx_conversations_doctor ON conversations (doctor_id);
CREATE INDEX idx_conversations_updated ON conversations (updated_at);

CREATE TABLE IF NOT EXISTS messages (
    message_id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64) NULL,
    sender_id VARCHAR(64) NOT NULL,
    receiver_id VARCHAR(64) NOT NULL,
    patient_context_id VARCHAR(32) NULL,
    content TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    idempotency_key VARCHAR(64) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP NULL DEFAULT NULL,
    CONSTRAINT pk_messages PRIMARY KEY (message_id),
    CONSTRAINT fk_messages_conversation FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE,
    CONSTRAINT fk_messages_sender FOREIGN KEY (sender_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_messages_receiver FOREIGN KEY (receiver_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_messages_patient_context FOREIGN KEY (patient_context_id) REFERENCES patient_profiles (patient_id) ON DELETE SET NULL,
    CONSTRAINT uq_messages_sender_idempotency UNIQUE (sender_id, idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_messages_receiver_read_time ON messages (receiver_id, is_read, created_at);
CREATE INDEX idx_messages_sender_time ON messages (sender_id, created_at);
CREATE INDEX idx_messages_conversation_time ON messages (conversation_id, created_at);
CREATE INDEX idx_messages_conversation_unread ON messages (conversation_id, is_read, receiver_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id BIGINT AUTO_INCREMENT,
    actor_id VARCHAR(64) NULL,
    action VARCHAR(64) NOT NULL,
    target_type VARCHAR(32) NOT NULL,
    target_id VARCHAR(64) NOT NULL,
    ip_address VARCHAR(45) NULL,
    metadata_json TEXT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_audit_logs PRIMARY KEY (audit_id),
    CONSTRAINT fk_audit_actor FOREIGN KEY (actor_id) REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_audit_actor_time ON audit_logs (actor_id, timestamp);
CREATE INDEX idx_audit_target ON audit_logs (target_type, target_id);
CREATE INDEX idx_audit_timestamp ON audit_logs (timestamp);

-- Table 14: analytics_outbox
-- Transactional outbox for reliable asynchronous mirroring to MongoDB Atlas
CREATE TABLE IF NOT EXISTS analytics_outbox (
    outbox_id BIGINT AUTO_INCREMENT,
    event_type VARCHAR(32) NOT NULL,
    aggregate_id VARCHAR(64) NOT NULL,
    payload_json TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    last_error TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_attempt_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    CONSTRAINT pk_analytics_outbox PRIMARY KEY (outbox_id),
    CONSTRAINT ck_outbox_status CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT ck_outbox_event_type CHECK (event_type IN ('telemetry_event', 'alert_event'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_outbox_status_created ON analytics_outbox (status, created_at);
CREATE INDEX idx_outbox_aggregate ON analytics_outbox (event_type, aggregate_id);

-- =====================================================================
-- 7. DA1/DA2 DATABASE OBJECTS: VIEWS, FUNCTIONS, PROCEDURES & TRIGGERS
-- =====================================================================

-- View: v_latest_patient_vitals
-- Retrieves the single latest vital measurement for each patient and metric code
CREATE OR REPLACE VIEW v_latest_patient_vitals AS
WITH ranked_vitals AS (
    SELECT 
        reading_id,
        event_id,
        patient_id,
        metric_code,
        value,
        unit,
        raw_value,
        raw_unit,
        quality_status,
        measured_at,
        ROW_NUMBER() OVER (
            PARTITION BY patient_id, metric_code 
            ORDER BY measured_at DESC, reading_id DESC
        ) AS rn
    FROM vitals_readings
)
SELECT 
    reading_id,
    event_id,
    patient_id,
    metric_code,
    value,
    unit,
    raw_value,
    raw_unit,
    quality_status,
    measured_at
FROM ranked_vitals
WHERE rn = 1;

-- View: v_patient_active_alerts
-- Retrieves active alerts with patient and assigned clinician context
CREATE OR REPLACE VIEW v_patient_active_alerts AS
SELECT 
    a.alert_id,
    a.patient_id,
    p.first_name AS patient_first_name,
    p.last_name AS patient_last_name,
    dpa.doctor_id,
    a.severity,
    a.category,
    a.reason,
    a.status,
    a.created_at
FROM alerts a
JOIN patient_profiles p ON a.patient_id = p.patient_id
LEFT JOIN doctor_patient_assignments dpa ON p.patient_id = dpa.patient_id AND dpa.is_active = TRUE
WHERE a.status IN ('NEW', 'ACKNOWLEDGED');

-- Function: fn_calculate_bmi
-- Calculates Body Mass Index = weight_kg / (height_cm / 100)^2, safely returning NULL for non-positive inputs
DELIMITER $$
CREATE FUNCTION IF NOT EXISTS fn_calculate_bmi(
    p_weight_kg DECIMAL(5, 2),
    p_height_cm DECIMAL(5, 2)
) RETURNS DECIMAL(5, 2)
DETERMINISTIC
NO SQL
BEGIN
    IF p_weight_kg IS NULL OR p_height_cm IS NULL OR p_weight_kg <= 0 OR p_height_cm <= 0 THEN
        RETURN NULL;
    END IF;
    RETURN ROUND(p_weight_kg / POWER(p_height_cm / 100.0, 2), 2);
END$$
DELIMITER ;

-- Stored Procedure: sp_acknowledge_alert
-- Performs atomic state transition for alerts with audit trail update
DELIMITER $$
CREATE PROCEDURE IF NOT EXISTS sp_acknowledge_alert(
    IN p_alert_id VARCHAR(64),
    IN p_actor_id VARCHAR(64),
    IN p_note TEXT
)
BEGIN
    DECLARE v_current_status VARCHAR(16);
    
    -- Check current alert status
    SELECT status INTO v_current_status FROM alerts WHERE alert_id = p_alert_id;
    
    IF v_current_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Alert not found';
    ELSEIF v_current_status = 'RESOLVED' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot acknowledge an already resolved alert';
    ELSE
        START TRANSACTION;
        UPDATE alerts
        SET status = 'ACKNOWLEDGED',
            acknowledged_by = p_actor_id,
            acknowledged_at = CURRENT_TIMESTAMP
        WHERE alert_id = p_alert_id;
        
        INSERT INTO alert_status_history (alert_id, old_status, new_status, actor_id, note, changed_at)
        VALUES (p_alert_id, v_current_status, 'ACKNOWLEDGED', p_actor_id, p_note, CURRENT_TIMESTAMP);
        
        COMMIT;
    END IF;
END$$
DELIMITER ;

-- Trigger: trg_alert_status_history_after_update
-- Automatically records status transition history when alerts table status column changes
DELIMITER $$
CREATE TRIGGER IF NOT EXISTS trg_alert_status_history_after_update
AFTER UPDATE ON alerts
FOR EACH ROW
BEGIN
    IF OLD.status <> NEW.status THEN
        INSERT INTO alert_status_history (
            alert_id,
            old_status,
            new_status,
            actor_id,
            note,
            changed_at
        ) VALUES (
            NEW.alert_id,
            OLD.status,
            NEW.status,
            COALESCE(NEW.acknowledged_by, NEW.resolved_by),
            'Automated status change trigger',
            CURRENT_TIMESTAMP
        );
    END IF;
END$$
DELIMITER ;
