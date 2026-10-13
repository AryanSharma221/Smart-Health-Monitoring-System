# Database Backup, Disaster Recovery, and Synchronization Runbook

> [!IMPORTANT]
> **DISASTER RECOVERY RUNBOOK — CRITICAL OPERATIONAL PROCEDURES**  
> This runbook defines the authoritative backup and recovery strategy for the **Smart Health Monitoring System**. All recovery operations must be performed first in an isolated staging environment before promoting to production.

---

## 1. Disaster Recovery Objectives & Scope

| Objective | Target | Operational Mechanism |
|:---|:---|:---|
| **Recovery Point Objective (RPO)** | **< 15 minutes** | Daily logical backups + MySQL Binary Logging (`binlog`) |
| **Recovery Time Objective (RTO)** | **< 30 minutes** | Automated restoration scripts & pre-provisioned warm instances |
| **Data Scope (Authoritative)** | **100% of MySQL** | Users, Profiles, Readings, Alerts, Messages, Audits, Outbox |
| **Data Scope (Secondary Mirror)** | **Rebuildable** | MongoDB Atlas collections can be fully re-synchronized from MySQL |

---

## 2. MySQL Backup Strategy

### A. Logical Full Backup via `mysqldump`
Execute daily automated backups during off-peak hours using consistent non-blocking snapshot flags:

```bash
#!/usr/bin/env bash
# /opt/scripts/backup_mysql.sh
set -euo pipefail

BACKUP_DIR="/var/backups/smart_health"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/smart_health_${TIMESTAMP}.sql.gz"
ENC_BACKUP_FILE="${BACKUP_FILE}.gpg"

mkdir -p "${BACKUP_DIR}"

echo "[INFO] Starting consistent logical backup of 'smart_health' database..."
mysqldump \
  --host="${MYSQL_HOST:-localhost}" \
  --port="${MYSQL_PORT:-3306}" \
  --user="${MYSQL_BACKUP_USER:-backup_agent}" \
  --password="${MYSQL_BACKUP_PASSWORD}" \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --events \
  --hex-blob \
  --default-character-set=utf8mb4 \
  smart_health | gzip -9 > "${BACKUP_FILE}"

echo "[INFO] Encrypting backup with GPG..."
gpg --batch --yes --encrypt --recipient ops@hospital.org "${BACKUP_FILE}"
rm -f "${BACKUP_FILE}"

echo "[INFO] Backup created successfully: ${ENC_BACKUP_FILE}"
```

### B. Backup Storage & Retention Policy
1. **Local Retention**: Keep 7 days of compressed, encrypted backups on local disk.
2. **Offsite Cloud Retention**: Replicate daily backups to object storage (AWS S3 Glacier / Azure Blob Storage) with Object Lock (WORM policy) for 365 days compliance.
3. **Continuous Binary Logs (`binlog`)**: Archive MySQL binary logs every 10 minutes for point-in-time recovery.

---

## 3. Step-by-Step MySQL Restoration Runbook

### Step 1: Prepare Isolated Recovery Database
Never restore directly over an active database. Always restore into a designated validation schema or isolated database instance:

```bash
mysql -u root -p -e "CREATE DATABASE smart_health_recovery CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### Step 2: Decrypt and Decompress Backup Artifact
```bash
gpg --decrypt smart_health_20261013_020000.sql.gz.gpg | gunzip > /tmp/restore_payload.sql
```

### Step 3: Ingest SQL Dump into Recovery Database
```bash
mysql -u root -p smart_health_recovery < /tmp/restore_payload.sql
rm -f /tmp/restore_payload.sql
```

### Step 4: Validate Data Integrity and Schema Revision
Execute validation queries to confirm record counts, relationships, and migration consistency:

```sql
USE smart_health_recovery;

-- 1. Verify schema migration version
SELECT version_num FROM alembic_version;
-- Expected output: '003_conversations_and_messaging'

-- 2. Verify core record counts
SELECT 'users' AS table_name, count(*) AS count FROM users
UNION ALL
SELECT 'patient_profiles', count(*) FROM patient_profiles
UNION ALL
SELECT 'ingestion_events', count(*) FROM ingestion_events
UNION ALL
SELECT 'vitals_readings', count(*) FROM vitals_readings
UNION ALL
SELECT 'alerts', count(*) FROM alerts
UNION ALL
SELECT 'conversations', count(*) FROM conversations
UNION ALL
SELECT 'messages', count(*) FROM messages
UNION ALL
SELECT 'analytics_outbox', count(*) FROM analytics_outbox;

-- 3. Verify zero orphan records (referential integrity)
SELECT count(*) AS orphan_readings 
FROM vitals_readings r 
LEFT JOIN patient_profiles p ON r.patient_id = p.patient_id 
WHERE p.patient_id IS NULL;
-- Expected: 0
```

### Step 5: Safe Production Cutover
Once validation passes:
1. Put API into maintenance mode (`/health/ready` returns 503).
2. Point application environment (`MYSQL_DATABASE=smart_health_recovery` or rename database).
3. Restart API service and execute smoke tests.

---

## 4. MongoDB Atlas Mirroring & Outbox Recovery

> [!NOTE]
> MongoDB Atlas is an asynchronous secondary mirror. If MongoDB Atlas data is lost or corrupted, the authoritative database (MySQL) is unaffected.

### A. Diagnosing Outbox Synchronization Status
Query MySQL `analytics_outbox` table to inspect backlog and failure counts:

```sql
SELECT status, count(*) AS count, min(created_at) AS oldest_entry, max(attempt_count) AS max_attempts
FROM analytics_outbox
GROUP BY status;
```

### B. Recovering Failed or Stalled Outbox Events
If network interruptions to MongoDB Atlas caused events to exhaust retries (`status = 'failed'`):

```sql
-- 1. Inspect error messages
SELECT outbox_id, event_type, aggregate_id, attempt_count, last_error
FROM analytics_outbox
WHERE status = 'failed'
LIMIT 10;

-- 2. Reset failed entries for immediate retry once Atlas connectivity is restored
UPDATE analytics_outbox
SET status = 'pending', attempt_count = 0, last_error = NULL
WHERE status = 'failed';
```

### C. Full Analytics Mirror Reconstruction Runbook
If the entire MongoDB Atlas cluster was wiped or replaced:

1. **Create Collections and Indexes**:
   Connect via `mongosh` and ensure target collections exist with proper unique indexes:
   ```javascript
   use smart_health_analytics;
   db.telemetry_events.createIndex({ patient_id: 1, measured_at: -1 });
   db.alert_events.createIndex({ patient_id: 1, created_at: -1 });
   db.alert_events.createIndex({ severity: 1, status: 1 });
   ```

2. **Re-stage Events into Outbox**:
   Since MongoDB documents use the MySQL primary key as `_id` (`_id: event_id` for telemetry, `_id: alert_id` for alerts), replaying records is **100% idempotent** and will never create duplicates:
   ```sql
   -- Re-enqueue all historical telemetry events
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
   WHERE NOT EXISTS (
       SELECT 1 FROM analytics_outbox o 
       WHERE o.aggregate_id = e.event_id AND o.event_type = 'telemetry_event'
   );
   ```

---

## 5. Routine Backup Verification Drills

- **Schedule**: First Monday of every month.
- **Procedure**: Automate the restoration of the latest production backup into an ephemeral containerized MySQL instance, execute the validation script, and send a signed audit report to the DevOps team.
