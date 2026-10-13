# Database Backup, Disaster Recovery, and Operational Readiness Runbook

> [!IMPORTANT]
> **DISASTER RECOVERY RUNBOOK — CRITICAL OPERATIONAL PROCEDURES**  
> This runbook defines the authoritative backup, recovery, verification, and access control strategy for the **Smart Health Monitoring System**. All recovery operations must be performed first in an isolated recovery environment (e.g., `smart_health_recovery`, `smart_health_analytics_recovery`) before promoting to production.

---

## 1. Operational Evidence Table

| Procedure | Tool / Script | Status | Verification Evidence | Notes & Safety Boundaries |
|:---|:---|:---|:---|:---|
| **MySQL Logical Backup** | `scripts/backup_mysql.py` | **Verified** | `test_mysql_backup_dry_run`, `test_mysql_backup_collision_detection` | Uses `mysqldump 8.4` with `--single-transaction`, `--routines`, `--triggers`, `--events`, `--hex-blob`, SHA-256, and JSON manifest. Password passed via `MYSQL_PWD` (no CLI exposure). |
| **MongoDB Analytics Backup** | `scripts/backup_mongodb.py` | **Verified** | `test_mongodb_logical_export_and_restore_mongomock` | Dual-mode: Native `mongodump` when installed; fallback to driver-based PyMongo logical bundle (`.tar.gz`) capturing documents and index specifications. URI credentials redacted. |
| **MySQL Isolated Restore** | `scripts/restore_mysql.py` | **Verified** | `test_mysql_restore_safety_guard_blocks_production` | Restores to isolated database `smart_health_recovery`. Strictly blocks restoring over production without explicit `--force-production` override. Pre-checks SHA-256 checksum. |
| **MongoDB Isolated Restore** | `scripts/restore_mongodb.py` | **Verified** | `test_mongodb_restore_safety_guard_blocks_production`, `test_mongodb_logical_export_and_restore_mongomock` | Restores into `smart_health_analytics_recovery`. Rebuilds collection documents and recreates indexes. Strictly blocks restoring over production without `--force-production`. |
| **Recovery Verification** | `scripts/verify_recovery.py` | **Verified** | `test_automated_recovery_verification_mongodb`, `test_sha256_checksum_verification_and_corruption_detection` | Validates file existence, non-zero size, SHA-256 match, test restore execution, core tables/collections, record counts, and sample analytical queries. |
| **Retention & Pruning** | `scripts/cleanup_backups.py` | **Verified** | `test_backup_cleanup_retention_and_dry_run`, `test_backup_cleanup_path_boundary_safety` | Enforces retention policy (default: keep 7 newest backup sets). Deletes matched companion files (`.sha256`, `.manifest.json`). Confined strictly to backup roots with path traversal prevention. Defaults to dry-run mode. |
| **Least-Privilege RBAC** | `provision_least_privilege_users.sql` | **Documented** | DDL script with explicit grants | Provisions 5 dedicated roles with minimal permissions. Zero administrative wildcards for application or analytics accounts. |

---

## 2. Disaster Recovery Objectives & Scope

| Metric | Target | Operational Mechanism |
|:---|:---|:---|
| **Recovery Point Objective (RPO)** | **< 15 minutes** | Daily logical dumps + continuous MySQL binary logs (`binlog`) |
| **Recovery Time Objective (RTO)** | **< 30 minutes** | Automated restore scripts, pre-flight checksum verification, and scripted recovery verification |
| **Authoritative Store (MySQL)** | **100% Lossless Recovery** | Users, Profiles, Assignments, Readings, Alerts, Conversations, Messages, Audits, Outbox |
| **Secondary Mirror (MongoDB)** | **Rebuildable & Resilient** | MongoDB Atlas telemetry and alert mirrors can be reconstructed idempotently from MySQL |

---

## 3. Least-Privilege Database Access Control

To enforce the Principle of Least Privilege (PoLP) and segregation of duties, the database architecture segregates operations across 5 distinct user accounts defined in `database/mysql/provision_least_privilege_users.sql`:

| User Account | Primary Role | Granted Privileges | Prohibited Operations |
|:---|:---|:---|:---|
| `smart_health_app` | FastAPI Application Runtime | `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `EXECUTE` on `smart_health.*` | `DROP`, `ALTER`, `CREATE`, `SUPER`, `GRANT`, `FILE` |
| `smart_health_analytics` | Streamlit & BI Read-Only Reader | `SELECT`, `SHOW VIEW` on `smart_health.*` | All DML (`INSERT`, `UPDATE`, `DELETE`), DDL (`CREATE`, `ALTER`, `DROP`) |
| `smart_health_migrator` | Alembic Schema Migrator | Full DDL (`CREATE`, `ALTER`, `DROP`, `INDEX`, `REFERENCES`), `TRIGGER`, `ROUTINE` on `smart_health.*` | Global server administration, access to system databases |
| `smart_health_backup` | Automated Backup Agent (`mysqldump`) | `SELECT`, `LOCK TABLES`, `SHOW VIEW`, `TRIGGER`, `EVENT` on `smart_health.*`; `PROCESS` on `*.*` | `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER` |
| `smart_health_admin` | Emergency DBA & Disaster Recovery | `ALL PRIVILEGES` on `smart_health.*` and `smart_health_recovery.*`; `PROCESS`, `SHOW DATABASES` | System shutdown, unrestricted file modification |

### Provisioning Least-Privilege Accounts
Execute as MySQL administrative root:

```bash
# Linux / macOS
mysql -u root -p < database/mysql/provision_least_privilege_users.sql

# Windows PowerShell
Get-Content database/mysql/provision_least_privilege_users.sql | mysql -u root -p
```

---

## 4. Backup Strategy and Tooling

### A. MySQL Logical Backup (`scripts/backup_mysql.py`)
Executes an atomic, non-locking snapshot using `mysqldump` with transaction isolation:

```powershell
# Windows PowerShell
python -m scripts.backup_mysql --compress --output-dir backups/mysql

# Dry-run validation
python -m scripts.backup_mysql --dry-run
```

**Key Features:**
- Flags enforced: `--single-transaction`, `--quick`, `--routines`, `--triggers`, `--events`, `--hex-blob`, `--default-character-set=utf8mb4`.
- Collision avoidance: Appends microseconds if multiple backups are triggered in the same second.
- Companion artifacts generated:
  - `<backup_name>.sql.gz`: Compressed SQL dump payload.
  - `<backup_name>.sql.gz.sha256`: Cryptographic SHA-256 checksum file.
  - `<backup_name>.sql.gz.manifest.json`: Structured metadata containing timestamp, size, flags, and checksum.
- Secret masking: Password passed via `MYSQL_PWD` subprocess environment variable, preventing command-line visibility.

### B. MongoDB Analytics Mirror Backup (`scripts/backup_mongodb.py`)
Exports the NoSQL analytics mirror collections (`telemetry_events`, `alert_events`):

```powershell
# Windows PowerShell
python -m scripts.backup_mongodb --output-dir backups/mongodb

# Dry-run validation
python -m scripts.backup_mongodb --dry-run
```

**Key Features:**
- Dual-mode execution:
  1. *Native mongodump*: Used if MongoDB Database Tools are found on the system.
  2. *Driver-based logical bundle*: Pure Python fallback streaming BSON documents and index specifications into a compressed `.tar.gz` bundle.
- Credential redaction: All connection strings in manifests and logs are sanitized via `sanitize_mongo_uri()`.
- Generates companion `.sha256` and `.manifest.json` files for tamper-evident tracking.

---

## 5. Restoration Runbooks and Safety Guards

### A. Safety Guard: Production Overwrite Prohibition
To prevent accidental data loss in production, both `restore_mysql.py` and `restore_mongodb.py` **block execution** if the target database matches the production configuration (`smart_health` or `smart_health_analytics`), unless the `--force-production` flag is explicitly provided.

### B. MySQL Isolated Restoration Runbook
Restores a backup archive into the isolated verification database `smart_health_recovery`:

```powershell
# Step 1: Execute restore into smart_health_recovery
python -m scripts.restore_mysql `
    --backup-file backups/mysql/mysql_smart_health_20261014_014600.sql.gz `
    --target-db smart_health_recovery

# Dry-run plan verification
python -m scripts.restore_mysql `
    --backup-file backups/mysql/mysql_smart_health_20261014_014600.sql.gz `
    --dry-run
```

### C. MongoDB Isolated Restoration Runbook
Restores an analytics backup bundle into `smart_health_analytics_recovery`:

```powershell
# Step 1: Execute restore into smart_health_analytics_recovery
python -m scripts.restore_mongodb `
    --backup-file backups/mongodb/mongodb_smart_health_analytics_20261014_014700.tar.gz `
    --target-db smart_health_analytics_recovery

# Dry-run plan verification
python -m scripts.restore_mongodb `
    --backup-file backups/mongodb/mongodb_smart_health_analytics_20261014_014700.tar.gz `
    --dry-run
```

---

## 6. Automated Recovery Verification (`scripts/verify_recovery.py`)

The automated recovery verifier validates physical artifact integrity and performs live semantic assertions:

```powershell
# Verify physical file existence and SHA-256 checksums
python -m scripts.verify_recovery `
    --artifact-path backups/mysql/mysql_smart_health_20261014_014600.sql.gz

# Execute full end-to-end recovery verification with test restore and query checks
python -m scripts.verify_recovery `
    --artifact-path backups/mysql/mysql_smart_health_20261014_014600.sql.gz `
    --verify-restore `
    --target-db smart_health_recovery
```

**Verification Steps Executed:**
1. **Physical Artifact Audit**: File existence, non-zero file size, readable permissions.
2. **Cryptographic Integrity**: Computes SHA-256 and matches against companion `.sha256` and `.manifest.json`.
3. **Isolated Test Restore**: Restores data into an ephemeral or recovery database without touching production.
4. **Schema Completeness Audit**: Verifies presence of core tables (`users`, `patient_profiles`, `vitals_readings`, `alerts`, etc.) or collections (`telemetry_events`, `alert_events`).
5. **Record Count Audit**: Calculates row/document counts across all recovered entities.
6. **Semantic Analytical Query**: Runs aggregate calculations (`AVG(heart_rate)`, `AVG(spo2)`) to verify that numeric data was not corrupted during decompression or ingestion.

---

## 7. Backup Retention and Pruning (`scripts/cleanup_backups.py`)

Automates the pruning of obsolete backup sets based on retention policies:

```powershell
# Dry-run (default mode): see what would be deleted without removing files
python -m scripts.cleanup_backups --keep-count 7

# Execute real deletion across all backup directories
python -m scripts.cleanup_backups --keep-count 7 --execute

# Prune specific directory with 30-day retention window
python -m scripts.cleanup_backups --backup-dir backups/mysql --keep-count 7 --keep-days 30 --execute
```

**Retention Rules:**
- **Guaranteed Count Floor**: Always retains at least the newest `N` backup sets (`--keep-count`, default: 7), ensuring that backups are never wiped completely even during prolonged downtime.
- **Atomic Deletions**: Deleting a primary archive automatically purges its companion `.sha256` and `.manifest.json` files.
- **Path Security Boundary**: Verifies that candidates reside strictly inside designated backup root directories, preventing path traversal attacks (`../`).

---

## 8. Cross-Database Synchronization & Post-Restore Reconciliation

When MySQL is restored to a previous point in time, MongoDB Atlas may contain newer events than MySQL, or may have missed events that occurred during downtime.

```
       +-----------------------+              +------------------------+
       |   Authoritative Store |              |  NoSQL Analytics Mirror |
       |      MySQL InnoDB     |              |     MongoDB Atlas      |
       +-----------+-----------+              +-----------+------------+
                   |                                      |
                   | 1. Restored to Point-in-Time T0      | (May contain T0 + delta)
                   |                                      |
                   v                                      v
       +-----------------------+              +------------------------+
       |   analytics_outbox    |              | telemetry_events /     |
       |  (Pending & Failed)   |              | alert_events           |
       +-----------+-----------+              +-----------+------------+
                   |                                      |
                   | 2. Replay Outbox Worker              | 3. Idempotent Upsert
                   +------------------------------------->|    (filter: _id = aggregate_id)
```

### Scenario A: Replaying Outbox Events (Idempotent Resync)
Since MongoDB documents use the authoritative MySQL integer IDs as their primary key (`_id = event_id` for telemetry, `_id = alert_id` for alerts), replaying outbox events is **100% idempotent**:

```sql
-- Step 1: Inspect pending or failed outbox events in restored MySQL
SELECT status, count(*) AS count, min(created_at) AS oldest, max(created_at) AS newest
FROM analytics_outbox
GROUP BY status;

-- Step 2: Reset any interrupted events to pending for automatic re-delivery
UPDATE analytics_outbox
SET status = 'pending', attempt_count = 0, last_error = NULL
WHERE status IN ('processing', 'failed');
```

### Scenario B: Full MongoDB Mirror Reconstruction
If MongoDB Atlas was destroyed or severely desynchronized, reconstruct the entire analytics mirror from authoritative MySQL records:

1. **Flush MongoDB Mirror Collections**:
   ```javascript
   // In mongosh connected to smart_health_analytics
   db.telemetry_events.deleteMany({});
   db.alert_events.deleteMany({});
   ```

2. **Re-stage Ingestion Events into MySQL Outbox**:
   ```sql
   -- Stage all historical ingestion events into outbox
   INSERT INTO analytics_outbox (event_type, aggregate_id, payload_json, status, attempt_count, max_attempts)
   SELECT 
       'telemetry_event',
       e.event_id,
       JSON_OBJECT(
           'event_id', e.event_id,
           'patient_id', e.patient_id,
           'measured_at', DATE_FORMAT(e.measured_at, '%Y-%m-%dT%H:%i:%sZ'),
           'source', e.source
       ),
       'pending',
       0,
       5
   FROM ingestion_events e
   ON DUPLICATE KEY UPDATE status = 'pending', attempt_count = 0;
   ```

3. **Trigger Synchronization Worker**:
   Run the background synchronization service to stream all queued outbox records to MongoDB Atlas without duplicate creation.
