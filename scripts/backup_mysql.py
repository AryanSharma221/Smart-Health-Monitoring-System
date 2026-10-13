"""
Authoritative MySQL Database Backup Utility.

Executes consistent logical backups of the authoritative MySQL database using `mysqldump`
with transaction isolation, stored routines, triggers, and events preservation.

Safety Invariants:
- Never exposes or logs passwords. Uses MYSQL_PWD subprocess environment isolation.
- Prevents silent overwrites: asserts unique timestamped filenames.
- Computes cryptographic SHA-256 integrity checksums.
- Emits structured JSON backup manifests for automated audit and recovery validation.

Usage:
    python -m scripts.backup_mysql [--output-dir DIR] [--compress] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from services.api.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backup_mysql")

DEFAULT_BACKUP_DIR = Path("backups/mysql")


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hexadecimal digest of a physical file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_mysqldump_executable() -> Optional[str]:
    """Locate mysqldump binary on PATH or known Windows install locations."""
    found = shutil.which("mysqldump")
    if found:
        return found

    known_paths = [
        Path(r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe"),
        Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe"),
        Path(r"C:\Program Files\MariaDB\bin\mysqldump.exe"),
    ]
    for p in known_paths:
        if p.is_file():
            return str(p)
    return None


def execute_mysql_backup(
    output_dir: Path = DEFAULT_BACKUP_DIR,
    compress: bool = False,
    dry_run: bool = False,
    database: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute a consistent logical backup of the MySQL database.
    Returns (success_boolean, metadata_manifest_dictionary).
    """
    cfg = settings or get_settings()
    target_db = database or cfg.mysql_database
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"mysql_{target_db}_{timestamp_str}"
    sql_path = output_dir / f"{base_name}.sql"
    final_artifact_path = sql_path

    # Check collision
    if final_artifact_path.exists():
        logger.warning("Collision detected for %s; appending microseconds.", final_artifact_path.name)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")
        base_name = f"mysql_{target_db}_{timestamp_str}"
        sql_path = output_dir / f"{base_name}.sql"
        final_artifact_path = sql_path

    manifest: Dict[str, Any] = {
        "database_type": "mysql_innodb",
        "database_name": target_db,
        "timestamp_utc": now.isoformat(),
        "backup_mode": "logical_dump",
        "flags": [
            "--single-transaction",
            "--quick",
            "--routines",
            "--triggers",
            "--events",
            "--hex-blob",
            "--default-character-set=utf8mb4",
        ],
        "target_file": str(final_artifact_path.name),
        "is_compressed": compress,
        "is_dry_run": dry_run,
        "status": "pending",
    }

    if dry_run:
        logger.info("[DRY-RUN] Validating MySQL backup execution for database '%s' -> %s", target_db, sql_path)
        manifest["status"] = "dry_run_success"
        manifest["artifact_size_bytes"] = 0
        manifest["sha256"] = "dry_run_simulated_checksum"
        return True, manifest

    dump_binary = find_mysqldump_executable()
    if not dump_binary:
        err_msg = "mysqldump utility not found on PATH or standard install directories."
        logger.error(err_msg)
        manifest["status"] = "failed"
        manifest["error"] = err_msg
        return False, manifest

    cmd = [
        dump_binary,
        f"--host={cfg.mysql_host}",
        f"--port={cfg.mysql_port}",
        f"--user={cfg.mysql_user}",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--events",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        target_db,
    ]

    # Mask secrets in log output
    masked_cmd = [f"--user={cfg.mysql_user}" if c.startswith("--user") else c for c in cmd]
    logger.info("Executing mysqldump: %s", " ".join(masked_cmd))

    # Pass password via MYSQL_PWD environment variable to prevent CLI process table leakage
    env = os.environ.copy()
    if cfg.mysql_password:
        env["MYSQL_PWD"] = cfg.mysql_password

    try:
        with open(sql_path, "wb") as out_file:
            proc = subprocess.run(
                cmd,
                stdout=out_file,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
                timeout=300,
            )

        if proc.returncode != 0:
            err_output = proc.stderr.decode("utf-8", errors="replace")[:1000]
            logger.error("mysqldump failed (code %d): %s", proc.returncode, err_output)
            manifest["status"] = "failed"
            manifest["exit_code"] = proc.returncode
            manifest["error"] = err_output
            if sql_path.exists():
                sql_path.unlink()
            return False, manifest

        # Optional compression
        if compress:
            import gzip
            gz_path = output_dir / f"{base_name}.sql.gz"
            logger.info("Compressing backup: %s -> %s", sql_path.name, gz_path.name)
            with open(sql_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            sql_path.unlink()
            final_artifact_path = gz_path
            manifest["target_file"] = str(final_artifact_path.name)

        # Integrity Checksum
        file_sha256 = compute_sha256(final_artifact_path)
        sha_file = output_dir / f"{final_artifact_path.name}.sha256"
        sha_file.write_text(f"{file_sha256}  {final_artifact_path.name}\n", encoding="utf-8")

        manifest["status"] = "completed"
        manifest["exit_code"] = 0
        manifest["artifact_size_bytes"] = final_artifact_path.stat().st_size
        manifest["sha256"] = file_sha256
        manifest["sha256_file"] = str(sha_file.name)

        # Save manifest file
        manifest_file = output_dir / f"{final_artifact_path.name}.manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        logger.info(
            "MySQL backup completed successfully: %s (%d bytes, SHA-256: %s)",
            final_artifact_path.name,
            manifest["artifact_size_bytes"],
            file_sha256[:16] + "...",
        )
        return True, manifest

    except subprocess.TimeoutExpired as exc:
        logger.error("mysqldump timed out after 300 seconds: %s", exc)
        manifest["status"] = "timeout"
        manifest["error"] = str(exc)
        if sql_path.exists():
            sql_path.unlink()
        return False, manifest
    except Exception as exc:
        logger.error("Unexpected error executing MySQL backup: %s", exc)
        manifest["status"] = "error"
        manifest["error"] = str(exc)
        if sql_path.exists():
            sql_path.unlink()
        return False, manifest


def main() -> None:
    """CLI entrypoint for MySQL backup utility."""
    parser = argparse.ArgumentParser(description="Authoritative MySQL Database Backup Utility")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BACKUP_DIR, help="Target backup directory")
    parser.add_argument("--compress", action="store_true", help="Gzip-compress resulting SQL dump")
    parser.add_argument("--dry-run", action="store_true", help="Validate parameters and plan without executing dump")
    parser.add_argument("--database", type=str, default=None, help="Override database name")
    args = parser.parse_args()

    success, manifest = execute_mysql_backup(
        output_dir=args.output_dir,
        compress=args.compress,
        dry_run=args.dry_run,
        database=args.database,
    )
    print(json.dumps(manifest, indent=2))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
