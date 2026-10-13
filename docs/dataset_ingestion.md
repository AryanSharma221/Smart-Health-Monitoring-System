# Smart Health Monitoring System — Dataset Ingestion Specification

**Document Version:** 1.0  
**Phase:** Part 2C — Kaggle CSV Validation & Idempotent Ingestion Pipeline  
**Module:** `services/ingestion`

---

## 1. Verified Dataset Discovery & Inventory

Two identical historical dataset files are available on the evaluation host:
1. **Primary Dataset File:** `E:\DOC-20261013-WA0056.csv`
   - **Byte Size:** 57,549 bytes
   - **SHA-256 Checksum:** `ca15cf7776a0a670c834ba2693edacbf4eb785acd26d06d1617d3a56425f65a7`
   - **Total Lines:** 1,501 (1 header row + 1,500 data records)
   - **Distinct Patients:** 5 (`P101`, `P102`, `P103`, `P104`, `P105`)
   - **Missing / Null Values:** 0
   - **Exact Duplicate Rows:** 0
2. **Normalized Mirror File:** `E:\kaggle_health_dataset.csv`
   - **Byte Size:** 58,751 bytes
   - **SHA-256 Checksum:** `50f391190cd58f87636c0f6ae45731f97791563210275f14e5208c75be96ec82`
   - **Total Lines:** 1,501 (1 header row + 1,500 data records)
   - **Distinct Patients:** 5 (`P101`, `P102`, `P103`, `P104`, `P105`)
   - **Difference:** File 2 contains standard zero-padded 2-digit hours (e.g. `08:13:00` vs `8:13:00`) and standard float formats (`99.0` vs `99`). Both files parse identically under the ingestion engine.

### Patient Distribution Across 1,500 Records:
| Patient ID | Record Count | Percentage |
| :--- | :--- | :--- |
| `P101` | 293 | 19.53% |
| `P102` | 302 | 20.13% |
| `P103` | 296 | 19.73% |
| `P104` | 325 | 21.67% |
| `P105` | 284 | 18.93% |
| **Total** | **1,500** | **100.0%** |

### Vital Measurement Ranges:
- **Heart Rate (`heart_rate`):** `60.0` to `135.0` bpm
- **Oxygen Saturation (`spo2`):** `88.1%` to `99.9%`
- **Temperature Fahrenheit (`temperature_f`):** `97.5°F` to `103.0°F`
- **Observation Window:** `2023-10-01 08:13:00` to `2023-10-11 13:35:00`

---

## 2. Source-to-Destination Field Mapping

The ingestion engine maps each CSV row into one `ingestion_events` packet and three normalized `vitals_readings` rows:

| Source CSV Field | Target Table | Target Column | Data Type | Transformation & Handling Policy |
| :--- | :--- | :--- | :--- | :--- |
| `patient_id` | `ingestion_events` | `patient_id` | `VARCHAR(32)` | Validated against `patient_profiles`. If unmapped, auto-provisioned or skipped based on `--no-auto-seed`. |
| `timestamp` | `ingestion_events` | `measured_at` | `TIMESTAMP` | Parsed with format `%Y-%m-%d %H:%M:%S`. Assigned explicit timezone from configuration (`DATASET_SOURCE_TIMEZONE`). |
| (computed) | `ingestion_events` | `source_event_id` | `VARCHAR(128)` | `kaggle_<sha12>_row_<ordinal>_<patient>`. Deterministic unique key. |
| (computed) | `ingestion_events` | `event_id` | `VARCHAR(64)` | Deterministic UUID v5 derived from `source_event_id`. |
| (system) | `ingestion_events` | `source` | `VARCHAR(32)` | Constant `'kaggle_csv'`. |
| (system) | `ingestion_events` | `is_simulated` | `BOOLEAN` | Constant `FALSE` (distinguishes historical records from live simulator events). |
| (system) | `ingestion_events` | `mirror_status` | `VARCHAR(16)` | Constant `'pending'` (awaits DA3 MongoDB Atlas replication). |
| `heart_rate` | `vitals_readings` | `value` / `raw_value` | `DECIMAL(8,2)` | Stored as `72.00`, unit `'bpm'`, `quality_status='valid'`. |
| `spo2` | `vitals_readings` | `value` / `raw_value` | `DECIMAL(8,2)` | Stored as `98.50`, unit `'%'`, `quality_status='valid'`. |
| `temperature_f` | `vitals_readings` | `raw_value` / `raw_unit` | `DECIMAL(8,2)` | Raw source preserved: `raw_value = 98.60`, `raw_unit = 'degF'`. |
| `temperature_f` | `vitals_readings` | `value` / `unit` | `DECIMAL(8,2)` | Canonical Celsius computed: `(temp_f - 32) * 5 / 9` rounded to 2 decimal places (`37.00 degC`). |

---

## 3. Patient Identity Resolution Policy

In clinical systems, medical observations must never be attached to arbitrary patients.
1. **Existing Profiles:** If `P101`–`P105` already exist in `patient_profiles`, observations attach directly.
2. **Auto-Provisioning Mode (Default: `--auto-seed`):**  
   If patient profiles do not exist, baseline `users` (`role='patient'`) and `patient_profiles` records are automatically provisioned with synthetic non-login credentials to ensure referential integrity.
3. **Strict Rejection Mode (`--no-auto-seed`):**  
   Observations for unmapped patient IDs are rejected and recorded in `unmapped_patient_records`. They are never inserted into the database.

---

## 4. Timezone & Measurement Unit Policies

- **Timezone Assumption:** The Kaggle CSV timestamps are timezone-naive (e.g. `2023-10-01 08:13:00`). To prevent silent timezone drift or inconsistent local server interpretation, the importer explicitly binds timestamps to `DATASET_SOURCE_TIMEZONE` (default: `UTC`).
- **Temperature Preservation:** `temperature_f` is preserved intact in `raw_value` (`degF`). To satisfy scientific and normalized healthcare queries, canonical Celsius is stored in `value` (`degC`).
- **Non-Existent Vitals:** Historical Kaggle records contain exactly 3 vitals (`heart_rate`, `spo2`, `temperature`). No artificial blood pressure or respiratory rate values are created.

---

## 5. Idempotency & Provenance Architecture

To prevent duplicate records upon re-running the importer:
1. **File Fingerprint:** The SHA-256 of the CSV file is computed.
2. **Deterministic Source Event ID:** Each row generates:
   $$\text{source\_event\_id} = \text{"kaggle\_"} + \text{SHA256}[:12] + \text{"\_row\_"} + \text{ordinal} + \text{"\_"} + \text{patient\_id}$$
3. **Database Unique Constraint:** `ingestion_events` enforces `UNIQUE(source, source_event_id)`.
4. **Pre-Query Filtering:** Before persisting a batch, the importer checks for existing `source_event_id` values in the database. Existing records are skipped, and the report increments `events_skipped_existing`.
5. **Partial Batch Resume:** If an import process terminates abruptly at row 500, rerunning the import safely skips rows 1–500 and inserts rows 501–1500 without duplicate primary keys or orphan vitals.

---

## 6. CLI Execution & Commands

### Dry-Run Validation (Zero Database Mutation):
```bash
python -m services.ingestion.cli --dry-run
```

### Dry-Run with Explicit CSV Path:
```bash
python -m services.ingestion.cli --csv-path "E:\DOC-20261013-WA0056.csv" --dry-run
```

### Actual Database Ingestion:
```bash
python -m services.ingestion.cli --csv-path "E:\DOC-20261013-WA0056.csv" --batch-size 250
```

### Strict Mode (No Auto-Provisioning):
```bash
python -m services.ingestion.cli --no-auto-seed --dry-run
```

---

## 7. Automated Testing

Run the isolated test suite covering all 17 ingestion scenarios:
```bash
python -m pytest tests/unit/test_ingestion.py -v
```
All tests execute against an in-memory SQLite database (`sqlite:///:memory:`) with `PRAGMA foreign_keys=ON` and require no network access or external credentials.

---

## 8. Source Data Immutability Guarantee

The ingestion pipeline treats all source CSV files as strictly read-only. Source files (`E:\DOC-20261013-WA0056.csv` and `E:\kaggle_health_dataset.csv`) are opened exclusively in mode `"r"` / `"rb"` and are verified by unit test `test_source_csv_remains_unchanged` to guarantee zero bit mutations.
