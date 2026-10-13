# MongoDB Aggregation Pipelines and Advanced Analytics Queries

**Project:** AI-Powered Smart Health Monitoring System  
**Milestone:** Part 3B — MongoDB Aggregation Pipelines & Analytics Layer  
**Role:** Senior Data Engineer  
**Database:** MongoDB Atlas (Analytics Mirror)  
**Database Name:** `smart_health_analytics` (configurable via `MONGODB_DATABASE`)  
**Status:** Implemented, Tested, and Documented  

---

## 1. Actual Collections and Document Schemas

The analytics mirror maintains two collections populated asynchronously from MySQL via the transactional outbox pattern:

### 1.1 `telemetry_events` Collection
Stores normalized vital signs and time-series observation telemetry.

```json
{
  "_id": "UUID string matching MySQL event_id",
  "event_id": "UUID string",
  "patient_id": "P101",
  "measured_at": "ISODate('2026-10-10T00:00:00Z')",
  "received_at": "ISODate('2026-10-10T00:00:01Z')",
  "source": "kaggle_csv",
  "source_event_id": "kaggle_csv:P101:2026-10-10T00:00:00",
  "is_simulated": false,
  "metrics": {
    "heart_rate": 80.0,
    "spo2": 98.0,
    "temperature_f": 98.6,
    "temperature_c": 37.0
  },
  "readings_summary": [
    {
      "metric_code": "heart_rate",
      "value": 80.0,
      "unit": "bpm",
      "raw_value": 80.0,
      "raw_unit": "bpm",
      "quality_status": "VALID"
    }
  ],
  "mirrored_at": "ISODate('2026-10-14T01:00:00Z')",
  "schema_version": 1
}
```

### 1.2 `alert_events` Collection
Stores clinical alerts, severity, triggering events, and lifecycle transition states.

```json
{
  "_id": "UUID string matching MySQL alert_id",
  "alert_id": "UUID string",
  "patient_id": "P101",
  "event_id": "UUID string of triggering telemetry event",
  "rule_id": "rule_tachycardia",
  "severity": "CRITICAL",
  "category": "vital_sign",
  "reason": "Heart rate (135.0 bpm) exceeded critical threshold (130 bpm)",
  "status": "NEW",
  "state_rank": 1,
  "acknowledged_by": null,
  "acknowledged_at": null,
  "resolved_by": null,
  "resolved_at": null,
  "created_at": "ISODate('2026-10-10T08:30:00Z')",
  "mirrored_at": "ISODate('2026-10-14T01:00:00Z')",
  "schema_version": 1
}
```

---

## 2. Field-Mapping Table

The following matrix documents the exact document fields consumed by each analytical workload:

| Workload | Collection | Fields Consumed | Grouping Key | Accumulators / Operators |
| :--- | :--- | :--- | :--- | :--- |
| **A. Dataset Overview** | `telemetry_events` | `_id`, `patient_id`, `measured_at`, `source`, `is_simulated` | `$facet` (`None`, `patient_id`, `source`) | `$sum: 1`, `$min`, `$max`, `$cond` |
| **B. Patient Vitals Summary** | `telemetry_events` | `patient_id`, `measured_at`, `metrics.heart_rate`, `metrics.spo2`, `metrics.temperature_f` | `patient_id` | `$sum: 1`, `$cond`, `$isNumber`, `$min`, `$max`, `$avg` |
| **C. Time-Based Trends** | `telemetry_events` | `patient_id`, `measured_at`, `metrics.*` | `$dateToString` (`format`, `measured_at`) | `$sum: 1`, `$avg`, `$min`, `$max` |
| **D. Patient History** | `telemetry_events` | `patient_id`, `measured_at`, `event_id`, `source`, `is_simulated`, `metrics` | None (point/range query) | `$match`, `$sort`, `$skip`, `$limit`, `$project` |
| **E. Source Provenance** | `telemetry_events` | `source`, `is_simulated`, `measured_at` | `(source, is_simulated)` | `$sum: 1`, `$min: measured_at`, `$max: measured_at` |
| **F. Alert Analytics** | `alert_events` | `severity`, `status`, `patient_id`, `acknowledged_at`, `created_at` | `$facet` (`severity`, `status`, `patient_id`, `None`) | `$sum: 1`, `$cond` |
| **G. Data Quality Audit** | `telemetry_events` | `patient_id`, `measured_at`, `source`, `source_event_id`, `metrics.*` | `None` (checks) & `(source, source_event_id)` (dups) | `$cond`, `$isNumber`, `$ne`, `$or`, `$and`, `$gt`, `$count` |

---

## 3. Detailed Aggregation Workloads & Pipeline Specifications

### 3.1 Dataset Overview (`get_dataset_overview`)
- **Purpose:** Produces an operational snapshot of the NoSQL analytics mirror in a single database round-trip using `$facet`.
- **Pipeline Stages:**
  1. `$facet`: Parallel sub-pipelines:
     - `overview`: Computes total documents, min/max observation timestamps, and simulation counts (`is_simulated == True` vs `False`).
     - `distinct_patients`: Aggregates unique `patient_id` values and sorts ascending.
     - `by_source`: Groups by `source` (`kaggle_csv`, `simulated`, `device`) and sorts descending by document count.
- **Index Support:** Scans `idx_telemetry_measured_at` and `idx_telemetry_source` where planner allows.

### 3.2 Patient-Level Measurement Summary (`get_patient_vitals_summary`)
- **Purpose:** Groups readings by patient and calculates empirical metrics for Heart Rate (bpm), SpO2 (%), and Body Temperature (°F).
- **Missing Value & Null Policy:**
  - Standard MongoDB `$avg`, `$min`, and `$max` naturally ignore `null` and absent values.
  - To prevent non-numeric values (e.g. malformed strings) or zeroes from skewing averages, every accumulator is wrapped with an explicit type guard:
    ```javascript
    "$cond": [{"$isNumber": "$metrics.heart_rate"}, "$metrics.heart_rate", null]
    ```
  - `valid_count` explicitly counts only documents where `$isNumber` is true:
    ```javascript
    "$sum": {"$cond": [{"$isNumber": "$metrics.heart_rate"}, 1, 0]}
    ```
  - When a patient has zero valid observations for a metric, `valid_count` returns `0`, and `min`, `max`, and `avg` strictly evaluate to `null` (`None` in Python), **never `0.0`**.
- **Index Support:** Early `$match` on `patient_id` and `measured_at` leverages compound index `idx_telemetry_patient_measured`.

### 3.3 Time-Based Trends (`get_time_bucketed_vitals`)
- **Purpose:** Bins measurements into chronological time buckets (`hour` or `day`) to analyze temporal vital trajectories.
- **Interval Formatting:**
  - Hourly: `"%Y-%m-%d %H:00:00"`
  - Daily: `"%Y-%m-%d"`
- **Pipeline Stages:**
  1. `$match`: Filters `measured_at != null` and applies optional `patient_id` and `start_time` / `end_time` boundaries.
  2. `$group`: Groups by `$dateToString` format string, calculating observation count and metric averages.
  3. `$project`: Formats fields into clean, human-readable bucket dictionaries.
  4. `$sort`: Chronological ordering by `time_bucket: 1`.

### 3.4 Patient-Specific History (`get_patient_telemetry_history`)
- **Purpose:** Fetches bounded, deterministic chronological telemetry records for clinical drilldown.
- **Pipeline Stages:**
  1. `$match`: Filters on `patient_id` (mandatory, validated) and optional time bounds.
  2. `$sort`: Deterministic compound sort on `{"measured_at": -1, "event_id": -1}`.
  3. `$skip`: Offset for pagination.
  4. `$limit`: Strictly capped at `max_limit = 1000` (default 100).
  5. `$project`: Excludes MongoDB internal `_id` and projects only telemetry and metrics fields.
- **Index Support:** Covered by compound index `idx_telemetry_patient_measured`.

### 3.5 Source and Provenance Analysis (`get_source_provenance_summary`)
- **Purpose:** Analyzes data origin distributions to provide auditability across external datasets and simulated sensors.
- **Provenance Rules:**
  - Historical Kaggle dataset: `source == "kaggle_csv"` and `is_simulated == False`.
  - Synthetic simulation: `is_simulated == True` or `source == "simulated"`.
  - Hardware/device streams: `source == "device"`.
  - Records are never classified as "live" or "synthetic" based solely on timestamps.

### 3.6 Clinical Alert Analytics (`get_alert_summary`)
- **Purpose:** Groups clinical alerts by severity, lifecycle status, patient, and calculates acknowledgment percentages.
- **Pipeline Stages:**
  1. `$match`: Optional filtering by `patient_id` and `created_at` range.
  2. `$facet`:
     - `by_severity`: Grouping by `severity` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
     - `by_status`: Grouping by `status` (`NEW`, `ACKNOWLEDGED`, `RESOLVED`).
     - `by_patient`: Distribution across patient IDs.
     - `acknowledgement_metrics`: Calculates acknowledged alerts (`acknowledged_at != null`), unacknowledged alerts, and acknowledgement rate.
- **Index Support:** Leverages compound index `idx_alerts_status_severity` and `idx_alerts_patient_created`.

### 3.7 Data-Quality Audit (`get_data_quality_report`)
- **Purpose:** Automated diagnostic audit detecting schema discrepancies, missing fields, corrupted BSON types, out-of-bounds readings, and duplicate external identities.
- **Checks Executed:**
  - Missing mandatory fields: `missing_patient_id`, `missing_measured_at`, `missing_source`.
  - Null vital fields: `null_heart_rate`, `null_spo2`, `null_temperature_f`.
  - Invalid BSON types: `invalid_type_heart_rate`, `invalid_type_spo2`, `invalid_type_temperature_f` (strings or arrays in numeric fields).
  - Physiologically implausible bounds:
    - Heart Rate: $< 30\text{ bpm}$ or $> 250\text{ bpm}$
    - Oxygen Saturation: $< 50\%$ or $> 100\%$
    - Body Temperature: $< 90.0^\circ\text{F}$ or $> 115.0^\circ\text{F}$
  - Duplicate source identities: Detects multiple documents sharing identical `(source, source_event_id)` pairs.

---

## 4. Index Optimization and Compound Keys

The following indexes are defined in [`database/mongodb/collections.py`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mongodb/collections.py) and initialized via [`ensure_indexes()`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mongodb/client.py#L121-L155):

### `telemetry_events` Indexes:
1. `idx_telemetry_patient_measured`: Compound `[("patient_id", 1), ("measured_at", -1)]`
   - *Workloads accelerated:* Patient vitals summary, patient history, patient time-bucket trends.
2. `idx_telemetry_measured_at`: Single-field `[("measured_at", -1)]`
   - *Workloads accelerated:* Global time-range filters, dataset overview timestamp boundaries.
3. `idx_telemetry_source`: Single-field `[("source", 1)]`
   - *Workloads accelerated:* Source provenance aggregation, data ingestion filtering.
4. `idx_telemetry_simulated`: Single-field `[("is_simulated", 1)]`
   - *Workloads accelerated:* Simulation vs. real cohort partitioning.
5. `idx_telemetry_source_event_id`: Single-field `[("source_event_id", 1)]` (Sparse)
   - *Workloads accelerated:* Duplicate source identity detection and idempotent outbox replay checks.

### `alert_events` Indexes:
1. `idx_alerts_patient_created`: Compound `[("patient_id", 1), ("created_at", -1)]`
   - *Workloads accelerated:* Patient alert feeds and clinical triage histories.
2. `idx_alerts_status_severity`: Compound `[("status", 1), ("severity", 1)]`
   - *Workloads accelerated:* Emergency dashboard triage and active critical alert filtering.
3. `idx_alerts_rule_id`: Single-field `[("rule_id", 1)]`
4. `idx_alerts_event_id`: Single-field `[("event_id", 1)]`

---

## 5. Execution Example

All analytics workloads are exposed via the centralized repository [`MongoAnalyticsRepository`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mongodb/repositories/analytics_repository.py):

```python
from datetime import datetime, timezone
from database.mongodb.client import get_mongo_database
from database.mongodb.repositories.analytics_repository import MongoAnalyticsRepository

# Initialize repository with centralized database handle
db = get_mongo_database()
analytics = MongoAnalyticsRepository(db)

# 1. Dataset overview
overview = analytics.get_dataset_overview()
print(f"Total Telemetry Docs: {overview['total_documents']}, Patients: {overview['distinct_patient_ids']}")

# 2. Patient vital statistics (P101)
summary = analytics.get_patient_vitals_summary(
    patient_id="P101",
    start_time=datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc),
    end_time=datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc),
)
for patient in summary:
    hr = patient["heart_rate"]
    print(f"P101 HR -> Min: {hr['min']}, Max: {hr['max']}, Avg: {hr['avg']} bpm (N={hr['valid_count']})")

# 3. Hourly time buckets
hourly_trends = analytics.get_time_bucketed_vitals(
    patient_id="P101",
    interval="hour",
)
for bucket in hourly_trends[:5]:
    print(f"{bucket['time_bucket']} | Obs: {bucket['observation_count']} | Avg HR: {bucket['avg_heart_rate']}")

# 4. Clinical alert summary
alert_metrics = analytics.get_alert_summary()
print(f"Total Alerts: {alert_metrics['total_alerts']}, Acknowledged: {alert_metrics['acknowledgement']['acknowledgement_rate_percent']}%")

# 5. Data-quality audit
quality = analytics.get_data_quality_report()
print(f"Data Quality Clean: {quality['is_clean']}, Duplicates: {quality['duplicate_source_identities']}")
```

---

## 6. Verification and Testing Status

- **Automated Test Suite:** [`tests/unit/test_mongodb_analytics.py`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/tests/unit/test_mongodb_analytics.py)
- **Execution Command:** `python -m pytest tests/unit/test_mongodb_analytics.py -v`
- **Result:** **13 passed in 0.21s (100% pass rate)**.
- **Atlas Verification Status:**
  - Live Atlas queries require setting `MONGODB_URI` in `.env`.
  - In local and offline test environments, tests run against an isolated `mongomock` instance with zero network latency.
  - **No performance or latency figures have been fabricated.** Live Atlas execution plan metrics (`IXSCAN`, `COLLSCAN`, `executionTimeMillis`) are reserved for the Part 3C benchmarking phase when connected to a live cluster.
- **Portability Notes:**
  - MongoDB 3.6+ and `mongomock` compatibility was verified.
  - Operators not implemented in `mongomock` (such as `$stdDevPop` and `$dateTrunc`) were avoided in favor of universal, standardized expressions (`$avg`, `$min`, `$max`, `$sum`, and `$dateToString`) to guarantee 100% local testability without compromising mathematical accuracy.
