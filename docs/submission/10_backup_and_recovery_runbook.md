# 10. Database Backup, Recovery & Disaster Recovery Runbook

**Document:** Operational Runbook & Disaster Recovery Specification  
**Project:** AI-Powered Smart Health Monitoring System  
**Auditor & Reliability Lead:** Senior Database Reliability Engineer  
**Date:** 14 October 2026  
**Relational Target:** MySQL 8.0 InnoDB  
**Document Target:** MongoDB Atlas 7.0 / 8.0  
**Automated Scripts:** `scripts/backup_and_recovery.py`  
**Test Suite:** `tests/test_backup_and_recovery.py` (Passed)  

---

## 1. Operational Backup Strategy & Rationale

In high-concurrency clinical healthcare systems, data loss or extended service downtime directly threatens patient safety. Our backup architecture defines strict operational parameters:
- **Recovery Point Objective (RPO):** $< 5 \text{ minutes}$ (guaranteed via binary log streaming).
- **Recovery Time Objective (RTO):** $< 30 \text{ minutes}$ for full cold-start database recovery.

```mermaid
graph TD
    subgraph OperationalDBS ["Production Databases"]
        MySQLProd["MySQL 8 InnoDB\n(System of Record)"]
        MongoProd["MongoDB Atlas\n(Analytical Mirror)"]
        Binlog["MySQL Binary Logs\n(Continuous Transaction Stream)"]
    end

    subgraph BackupPipeline ["Automated Backup Engine (scripts/backup_and_recovery.py)"]
        DumpWorker["mysqldump --single-transaction\n(Consistent Snapshot without Locks)"]
        MongoWorker["mongodump --archive --gzip\n(Logical Archive Dump)"]
        Hasher["SHA-256 Checksum Generator\n(Integrity Validation)"]
    end

    subgraph StorageVault ["Secure Storage & Verification"]
        BackupStorage["Local / Cloud Encrypted Vault\n(/backups/mysql_*.sql.gz)"]
        RestoreHarness["Non-Destructive Restore Drill\n(Restores to isolated test DB\nValidates row counts & drop)"]
    end

    MySQLProd --> DumpWorker
    MySQLProd --> Binlog
    MongoProd --> MongoWorker
    DumpWorker --> Hasher
    MongoWorker --> Hasher
    Hasher --> BackupStorage
    BackupStorage --> RestoreHarness
```

---

## 2. MySQL 8 InnoDB Backup & Point-in-Time Recovery (PITR)

### 2.1 Consistent Logical Snapshot (`mysqldump`)
To perform an online, non-blocking backup of MySQL InnoDB tables while patient telemetry continues to arrive:
```bash
mysqldump \
  --host=localhost \
  --user=app_backup \
  --password \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --events \
  --databases smart_health \
  | gzip > /var/backups/smart_health_$(date +%Y%m%d_%H%M%S).sql.gz
```
- `--single-transaction`: Uses InnoDB's Multi-Version Concurrency Control (MVCC) to take a snapshot without locking tables or interrupting telemetry writes.
- `--routines --triggers`: Ensures that stored functions, procedures (`sp_safe_patient_discharge`), and audit triggers (`trg_alert_status_history_after_update`) are backed up.

### 2.2 Point-in-Time Recovery via Binary Logs
If an administrator accidentally corrupts data at 14:35:00 UTC, the system is restored to 14:34:59 UTC:
1. Restore the last consistent base snapshot:
   ```bash
   gunzip < /var/backups/smart_health_20261014_000000.sql.gz | mysql -u root -p smart_health
   ```
2. Replay binary logs up to the exact transaction prior to corruption:
   ```bash
   mysqlbinlog \
     --start-datetime="2026-10-14 00:00:00" \
     --stop-datetime="2026-10-14 14:34:59" \
     /var/log/mysql/binlog.000042 | mysql -u root -p smart_health
   ```

---

## 3. MongoDB Atlas Backup & Restore Strategy

### 3.1 Logical Archive Backup (`mongodump`)
```bash
mongodump \
  --uri="mongodb+srv://user:pass@cluster0.mongodb.net/smart_health_analytics" \
  --archive=/var/backups/mongo_analytics_$(date +%Y%m%d_%H%M%S).archive.gz \
  --gzip
```

### 3.2 Restoration via `mongorestore`
```bash
mongorestore \
  --uri="mongodb+srv://user:pass@cluster0.mongodb.net/smart_health_analytics" \
  --archive=/var/backups/mongo_analytics_latest.archive.gz \
  --gzip \
  --drop
```
*Note: `--drop` clears existing collections before restoring to prevent primary key collision errors.*

---

## 4. Integrity Validation & Non-Destructive Restore Verification

A backup file is merely a liability until its restoration is proven. The system includes an automated restore drill script:

```bash
python -m scripts.backup_and_recovery --action=restore-test
```

### Verified Drill Execution Steps:
1. **Checksum Verification:** The script computes the SHA-256 hash of the backup file and verifies it against the generated `.sha256` manifest.
2. **Isolated Database Creation:** Creates a temporary, isolated database instance (`smart_health_restore_test`).
3. **Execution & DDL Loading:** Imports the database dump into the test instance.
4. **Row Count & Constraint Audit:** Queries all 17 tables, asserting that total records match the production snapshot.
5. **Procedural Logic Audit:** Executes stored procedures and triggers inside the test database to confirm procedural integrity.
6. **Destruction & Cleanup:** Drops `smart_health_restore_test` cleanly, leaving zero storage artifacts.
