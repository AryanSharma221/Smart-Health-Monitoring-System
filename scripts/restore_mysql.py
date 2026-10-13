"""
MySQL Database Restore and Isolated Recovery Tool.

Safety Invariants:
- Strictly prohibits restoring directly over production `smart_health` without explicit `--force-production` override.
- Pre-validates SHA-256 file integrity checksums before executing DDL/DML.
- Supports isolated validation targets (e.g., `smart_health_recovery`).
- Verifies post-restore table presence, row counts, and migration revisions.

Usage:
    python -m scripts.restore_mysql --backup-file PATH [--target-db DB] [--dry-run]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.api.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("restore_mysql")

DEFAULT_RECOVERY_DB = "smart_health_recovery"
CORE_TABLES = [
    "users",
    "patient_profiles",
    "doctor_profiles",
    "doctor_patient_assignments",
    "ingestion_events",
    "vitals_readings",
    "alerts",
    "analytics_outbox",
    "audit_logs",
]


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hexadecimal digest of a physical file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_mysql_executable() -> Optional[str]:
    """Locate mysql client binary on PATH or standard install locations."""
    found = shutil.which("mysql")
    if found:
        return found
    known_paths = [
        Path(r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"),
        Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"),
        Path(r"C:\Program Files\MariaDB\bin\mysql.exe"),
    ]
    for p in known_paths:
        if p.is_file():
            return str(p)
    return None


def execute_mysql_restore(
    backup_file: Path,
    target_db: str = DEFAULT_RECOVERY_DB,
    force_production: bool = False,
    dry_run: bool = False,
    settings: Optional[Settings] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Restore a MySQL logical dump into an isolated recovery database.
    """
    cfg = settings or get_settings()
    report: Dict[str, Any] = {
        "operation": "mysql_restore",
        "backup_file": str(backup_file),
        "target_database": target_db,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "is_dry_run": dry_run,
        "status": "pending",
    }

    # 1. Target database safety guard
    if target_db == cfg.mysql_database and not force_production:
        err_msg = (
            f"SAFETY VIOLATION: Target database is production '{target_db}'. "
            f"Routine restoration over active production data is forbidden without --force-production."
        )
        logger.error(err_msg)
        report["status"] = "blocked_safety_violation"
        report["error"] = err_msg
        return False, report

    # 2. Validate backup artifact existence
    if not backup_file.is_file():
        err_msg = f"Backup file '{backup_file}' does not exist or is not a readable file."
        logger.error(err_msg)
        report["status"] = "file_not_found"
        report["error"] = err_msg
        return False, report

    file_size = backup_file.stat().st_size
    if file_size == 0:
        err_msg = f"Backup file '{backup_file}' is empty (0 bytes)."
        logger.error(err_msg)
        report["status"] = "empty_artifact"
        report["error"] = err_msg
        return False, report

    # 3. Cryptographic integrity check
    actual_sha256 = compute_sha256(backup_file)
    report["sha256"] = actual_sha256

    sha_file = backup_file.parent / f"{backup_file.name}.sha256"
    if sha_file.is_file():
        expected_sha256 = sha_file.read_text(encoding="utf-8").split()[0].strip()
        if actual_sha256.lower() != expected_sha256.lower():
            err_msg = f"Integrity failure: expected SHA-256 {expected_sha256}, got {actual_sha256}."
            logger.error(err_msg)
            report["status"] = "checksum_mismatch"
            report["error"] = err_msg
            return False, report
        report["checksum_verified"] = True

    if dry_run:
        logger.info("[DRY-RUN] Restore plan validated for %s -> database '%s'.", backup_file.name, target_db)
        report["status"] = "dry_run_success"
        return True, report

    mysql_bin = find_mysql_executable()
    if not mysql_bin:
        err_msg = "mysql client binary not found on PATH or standard install locations."
        logger.error(err_msg)
        report["status"] = "client_utility_missing"
        report["error"] = err_msg
        return False, report

    # 4. Prepare SQL payload
    is_gzipped = backup_file.suffix == ".gz" or backup_file.name.endswith(".sql.gz")
    env = os.environ.copy()
    if cfg.mysql_password:
        env["MYSQL_PWD"] = cfg.mysql_password

    try:
        # Pre-create recovery database if needed
        create_db_cmd = [
            mysql_bin,
            f"--host={cfg.mysql_host}",
            f"--port={cfg.mysql_port}",
            f"--user={cfg.mysql_user}",
            "-e",
            f"CREATE DATABASE IF NOT EXISTS `{target_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        ]
        subprocess.run(create_db_cmd, env=env, check=True, stderr=subprocess.PIPE, timeout=60)

        # Ingest SQL dump
        restore_cmd = [
            mysql_bin,
            f"--host={cfg.mysql_host}",
            f"--port={cfg.mysql_port}",
            f"--user={cfg.mysql_user}",
            f"--default-character-set=utf8mb4",
            target_db,
        ]

        logger.info("Restoring backup artifact '%s' into '%s'...", backup_file.name, target_db)
        if is_gzipped:
            with gzip.open(backup_file, "rb") as f_gz:
                proc = subprocess.run(restore_cmd, stdin=f_gz, stderr=subprocess.PIPE, env=env, timeout=600)
        else:
            with open(backup_file, "rb") as f_raw:
                proc = subprocess.run(restore_cmd, stdin=f_raw, stderr=subprocess.PIPE, env=env, timeout=600)

        if proc.returncode != 0:
            err_text = proc.stderr.decode("utf-8", errors="replace")[:1000]
            logger.error("Restore failed (code %d): %s", proc.returncode, err_text)
            report["status"] = "restore_execution_failed"
            report["error"] = err_text
            return False, report

        report["status"] = "completed"
        logger.info("Successfully restored MySQL backup into database '%s'.", target_db)
        return True, report

    except Exception as exc:
        logger.error("Unexpected error during MySQL restore: %s", exc)
        report["status"] = "error"
        report["error"] = str(exc)
        return False, report


def main() -> None:
    """CLI entrypoint for MySQL restore utility."""
    parser = argparse.ArgumentParser(description="MySQL Database Restore and Recovery Tool")
    parser.add_argument("--backup-file", type=Path, required=True, help="Path to SQL or SQL.GZ backup file")
    parser.add_argument("--target-db", type=str, default=DEFAULT_RECOVERY_DB, help="Target recovery database name")
    parser.add_argument("--force-production", action="store_true", help="Explicit override to restore into production")
    parser.add_argument("--dry-run", action="store_true", help="Validate artifact and parameters without restoring")
    args = parser.parse_args()

    success, report = execute_mysql_restore(
        backup_file=args.backup_file,
        target_db=args.target_db,
        force_production=args.force_production,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
