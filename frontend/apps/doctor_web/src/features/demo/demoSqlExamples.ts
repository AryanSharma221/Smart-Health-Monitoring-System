export interface ExampleQuery {
  id: string;
  name: string;
  description: string;
  sql: string;
  category: 'INSERT' | 'SELECT' | 'UPDATE' | 'DELETE' | 'JOIN' | 'AGGREGATE' | 'VIEW';
  isDestructive?: boolean;
}

export const EXAMPLE_QUERIES: ExampleQuery[] = [
  {
    id: 'insert_abnormal_triad',
    name: '1. INSERT Abnormal Vitals Triad (Triggers Anomaly & Rule Alerts)',
    category: 'INSERT',
    description: 'Inserts HR (145 bpm), SpO2 (86%), and Temp (103.5°F) for P101. Provenance: self_added. Model triggers anomaly score >= 0.50 and clinical alerts.',
    sql: `INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES 
  ('P101', 'heart_rate', 145.0, 'bpm'), 
  ('P101', 'spo2', 86.0, '%'), 
  ('P101', 'temperature', 103.5, 'degF')`,
  },
  {
    id: 'insert_normal_triad',
    name: '2. INSERT Normal Vitals Triad (Healthy Baseline -> Normal ML Result)',
    category: 'INSERT',
    description: 'Inserts normal resting vitals (HR: 72 bpm, SpO2: 98.5%, Temp: 98.6°F) for P101. Results in normal ML classification with 0 alerts.',
    sql: `INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES 
  ('P101', 'heart_rate', 72.0, 'bpm'), 
  ('P101', 'spo2', 98.5, '%'), 
  ('P101', 'temperature', 98.6, 'degF')`,
  },
  {
    id: 'insert_single_metric',
    name: '3. INSERT Single Metric (HR Only -> Inconclusive ML Assessment)',
    category: 'INSERT',
    description: 'Inserts heart rate only without SpO2 and Temp. Missing features map to inconclusive (score 0.0) without fabricating values.',
    sql: `INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES 
  ('P102', 'heart_rate', 76.0, 'bpm')`,
  },
  {
    id: 'select_recent_readings',
    name: '4. SELECT Recent Readings (ORDER BY measured_at DESC LIMIT 10)',
    category: 'SELECT',
    description: 'Retrieves the 10 most recent normalized vital sign measurements across all patients.',
    sql: `SELECT reading_id, event_id, patient_id, metric_code, value, unit, quality_status, measured_at 
FROM vitals_readings 
ORDER BY measured_at DESC 
LIMIT 10`,
  },
  {
    id: 'filter_by_patient',
    name: '5. SELECT Filter by Patient (WHERE patient_id = \'P101\')',
    category: 'SELECT',
    description: 'Queries historical measurements specifically filtered for demo patient P101.',
    sql: `SELECT reading_id, event_id, metric_code, value, unit, raw_value, raw_unit, quality_status, measured_at 
FROM vitals_readings 
WHERE patient_id = 'P101' 
ORDER BY measured_at DESC 
LIMIT 10`,
  },
  {
    id: 'join_readings_patient',
    name: '6. SELECT Multi-Table JOIN (Patient Demographics + Vitals)',
    category: 'JOIN',
    description: 'Joins patient_profiles with vitals_readings to correlate demographic data with telemetry.',
    sql: `SELECT p.patient_id, p.first_name, p.last_name, v.metric_code, v.value, v.unit, v.measured_at 
FROM patient_profiles p 
INNER JOIN vitals_readings v ON p.patient_id = v.patient_id 
WHERE p.patient_id = 'P101' 
ORDER BY v.measured_at DESC 
LIMIT 10`,
  },
  {
    id: 'aggregate_by_patient',
    name: '7. SELECT Aggregates & GROUP BY (COUNT, AVG, MIN, MAX)',
    category: 'AGGREGATE',
    description: 'Calculates vital statistics across demo patients P101–P103 grouped by patient and metric code.',
    sql: `SELECT patient_id, metric_code, COUNT(*) AS sample_count, ROUND(AVG(value), 2) AS avg_value, MIN(value) AS min_value, MAX(value) AS max_value 
FROM vitals_readings 
WHERE patient_id IN ('P101', 'P102', 'P103') 
GROUP BY patient_id, metric_code`,
  },
  {
    id: 'update_demo_reading',
    name: '8. UPDATE Demo Reading (Re-evaluates Clinical Rules & ML)',
    category: 'UPDATE',
    description: 'Modifies vitals on self_added readings. Triggers server-side re-evaluation of clinical threshold rules.',
    sql: `UPDATE vitals_readings 
SET value = 148.0 
WHERE patient_id = 'P101' AND metric_code = 'heart_rate'`,
    isDestructive: true,
  },
  {
    id: 'delete_demo_reading',
    name: '9. DELETE Demo Reading (Cascade Cleans Orphaned Records)',
    category: 'DELETE',
    description: 'Removes self_added demo readings and automatically cascades cleanup of orphaned alerts, status history, and events.',
    sql: `DELETE FROM vitals_readings 
WHERE patient_id = 'P101' AND metric_code = 'heart_rate'`,
    isDestructive: true,
  },
  {
    id: 'create_view',
    name: '10. CREATE VIEW (v_p101_high_hr)',
    category: 'VIEW',
    description: 'Compiles an analytical relational view filtering high heart rate events (> 100 bpm) for P101.',
    sql: `CREATE VIEW IF NOT EXISTS v_p101_high_hr AS 
SELECT reading_id, event_id, patient_id, value AS heart_rate, unit, measured_at 
FROM vitals_readings 
WHERE patient_id = 'P101' AND metric_code = 'heart_rate' AND value > 100`,
  },
  {
    id: 'query_view',
    name: '11. SELECT from Compiled View (v_p101_high_hr)',
    category: 'VIEW',
    description: 'Executes a query directly against the previously compiled relational view.',
    sql: `SELECT * FROM v_p101_high_hr ORDER BY measured_at DESC LIMIT 10`,
  },
];
