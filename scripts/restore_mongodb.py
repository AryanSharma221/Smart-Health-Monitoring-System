"""
MongoDB Atlas Analytics Mirror Restore and Recovery Tool.

Safety Invariants:
- Strictly prohibits restoring directly over production MongoDB database without explicit `--force-production` override.
- Pre-validates SHA-256 file integrity checksums before restoring data.
- Supports isolated recovery targets (e.g., `smart_health_analytics_recovery`).
- Restores both document data and collection index specifications.
- Supports native `mongorestore` and Python driver-based bundle extraction.

Usage:
    python -m scripts.restore_mongodb --backup-file PATH [--target-db DB] [--dry-run]
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
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bson import json_util
from database.mongodb.client import (
    get_mongo_client,
    get_mongo_database,
    sanitize_mongo_uri,
)
from services.api.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("restore_mongodb")

DEFAULT_RECOVERY_DB = "smart_health_analytics_recovery"


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hexadecimal digest of a physical file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_mongorestore_executable() -> Optional[str]:
    """Locate mongorestore binary on PATH or standard install locations."""
    found = shutil.which("mongorestore")
    if found:
        return found
    known_paths = [
        Path(r"C:\Program Files\MongoDB\Tools\bin\mongorestore.exe"),
        Path(r"C:\Program Files\MongoDB\Server\8.0\bin\mongorestore.exe"),
        Path(r"C:\Program Files\MongoDB\Server\7.0\bin\mongorestore.exe"),
    ]
    for p in known_paths:
        if p.is_file():
            return str(p)
    return None


def restore_driver_logical_bundle(
    tar_path: Path,
    target_db: Any,
) -> Dict[str, Any]:
    """
    Extract and restore collections and indexes from a .tar.gz bundle.
    """
    stats: Dict[str, Any] = {}
    temp_dir = Path(tempfile.mkdtemp(prefix="mongo_restore_"))

    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(path=temp_dir, filter="data")
            else:
                tar.extractall(path=temp_dir)

        # Identify all JSONL files
        jsonl_files = list(temp_dir.glob("*.jsonl"))
        for jf in jsonl_files:
            col_name = jf.stem
            col = target_db[col_name]

            # 1. Restore documents
            doc_count = 0
            batch = []
            with open(jf, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    doc = json_util.loads(line)
                    batch.append(doc)
                    if len(batch) >= 500:
                        col.insert_many(batch)
                        doc_count += len(batch)
                        batch = []
                if batch:
                    col.insert_many(batch)
                    doc_count += len(batch)

            # 2. Restore indexes
            idx_file = temp_dir / f"{col_name}.indexes.json"
            idx_restored = 0
            if idx_file.is_file():
                idx_data = json_util.loads(idx_file.read_text(encoding="utf-8"))
                for idx in idx_data:
                    idx_name = idx.get("name", "")
                    if idx_name == "_id_":
                        continue
                    key_pairs = list(idx["key"].items())
                    kwargs: Dict[str, Any] = {}
                    if "unique" in idx:
                        kwargs["unique"] = idx["unique"]
                    if idx_name:
                        kwargs["name"] = idx_name
                    try:
                        col.create_index(key_pairs, **kwargs)
                        idx_restored += 1
                    except Exception as idx_err:
                        logger.warning("Could not recreate index '%s' on '%s': %s", idx_name, col_name, idx_err)

            stats[col_name] = {
                "documents_restored": doc_count,
                "indexes_restored": idx_restored,
            }
            logger.info("Restored collection '%s': %d docs, %d indexes.", col_name, doc_count, idx_restored)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return stats


def execute_mongodb_restore(
    backup_file: Path,
    target_db: str = DEFAULT_RECOVERY_DB,
    force_production: bool = False,
    dry_run: bool = False,
    settings: Optional[Settings] = None,
    mock_db: Any = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Restore a MongoDB backup artifact into an isolated recovery target database.
    """
    cfg = settings or get_settings()
    report: Dict[str, Any] = {
        "operation": "mongodb_restore",
        "backup_file": str(backup_file),
        "target_database": target_db,
        "endpoint": sanitize_mongo_uri(cfg.mongodb_uri),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "is_dry_run": dry_run,
        "status": "pending",
    }

    # 1. Target database safety guard
    if target_db == cfg.mongodb_database and not force_production:
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
        logger.info("[DRY-RUN] MongoDB restore plan validated for %s -> database '%s'.", backup_file.name, target_db)
        report["status"] = "dry_run_success"
        return True, report

    # Obtain MongoDB database handle
    target_database_handle = mock_db
    if target_database_handle is None:
        if not cfg.mongodb_uri:
            err_msg = "MONGODB_URI not configured. Cannot perform live MongoDB restore."
            logger.error(err_msg)
            report["status"] = "unconfigured"
            report["error"] = err_msg
            return False, report

        client = get_mongo_client(settings=cfg)
        if client is None:
            err_msg = "Failed to connect to MongoDB cluster."
            logger.error(err_msg)
            report["status"] = "connection_failure"
            report["error"] = err_msg
            return False, report
        target_database_handle = client[target_db]

    # Check restore method: native mongorestore for .archive.gz, or tar.gz logical bundle
    is_archive = backup_file.name.endswith(".archive.gz") or backup_file.name.endswith(".archive")
    mongorestore_bin = find_mongorestore_executable()

    if is_archive and mongorestore_bin and not mock_db:
        logger.info("Executing native mongorestore with binary: %s", mongorestore_bin)
        cmd = [
            mongorestore_bin,
            f"--uri={cfg.mongodb_uri}",
            f"--nsInclude={target_db}.*",
            f"--archive={backup_file}",
            "--gzip",
            "--drop",
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=600)
            if proc.returncode != 0:
                err_text = proc.stderr.decode("utf-8", errors="replace")[:1000]
                logger.error("mongorestore failed (code %d): %s", proc.returncode, err_text)
                report["status"] = "restore_execution_failed"
                report["error"] = err_text
                return False, report
            report["status"] = "completed"
            report["restore_method"] = "mongorestore_native_archive"
            return True, report
        except Exception as exc:
            logger.error("mongorestore execution error: %s", exc)
            report["status"] = "error"
            report["error"] = str(exc)
            return False, report

    # Fallback / driver-based logical bundle restore
    logger.info("Executing driver-based logical bundle restore into '%s'...", target_db)
    try:
        stats = restore_driver_logical_bundle(tar_path=backup_file, target_db=target_database_handle)
        report["status"] = "completed"
        report["restore_method"] = "pymongo_logical_bundle"
        report["collection_statistics"] = stats
        logger.info("Driver-based MongoDB restore completed successfully into '%s'.", target_db)
        return True, report
    except Exception as exc:
        logger.error("Driver logical restore error: %s", exc)
        report["status"] = "error"
        report["error"] = str(exc)
        return False, report


def main() -> None:
    """CLI entrypoint for MongoDB restore utility."""
    parser = argparse.ArgumentParser(description="MongoDB Atlas Analytics Mirror Restore Tool")
    parser.add_argument("--backup-file", type=Path, required=True, help="Path to MongoDB backup archive (.tar.gz)")
    parser.add_argument("--target-db", type=str, default=DEFAULT_RECOVERY_DB, help="Target recovery database name")
    parser.add_argument("--force-production", action="store_true", help="Explicit override to restore into production")
    parser.add_argument("--dry-run", action="store_true", help="Validate artifact and parameters without restoring")
    args = parser.parse_args()

    success, report = execute_mongodb_restore(
        backup_file=args.backup_file,
        target_db=args.target_db,
        force_production=args.force_production,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
