"""
MongoDB Atlas Analytics Mirror Backup Utility.

Supports two complementary logical backup modes:
1. Native `mongodump` binary execution (when MongoDB Database Tools are installed).
2. Python driver-based logical bundle (PyMongo document stream + index metadata export into .tar.gz).

Safety Invariants:
- Strictly redacts MongoDB connection URIs and credentials in all logs.
- Preserves collection index specifications alongside document data.
- Generates cryptographic SHA-256 digests and JSON audit manifests.
- Supports non-destructive dry-run planning mode.

Usage:
    python -m scripts.backup_mongodb [--output-dir DIR] [--dry-run]
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bson import json_util
from database.mongodb.client import (
    get_mongo_client,
    get_mongo_database,
    sanitize_mongo_uri,
)
from database.mongodb.collections import ALERTS_COLLECTION, TELEMETRY_COLLECTION
from services.api.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backup_mongodb")

DEFAULT_BACKUP_DIR = Path("backups/mongodb")


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hexadecimal digest of a physical file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_mongodump_executable() -> Optional[str]:
    """Locate mongodump binary on PATH or standard install locations."""
    found = shutil.which("mongodump")
    if found:
        return found
    known_paths = [
        Path(r"C:\Program Files\MongoDB\Tools\bin\mongodump.exe"),
        Path(r"C:\Program Files\MongoDB\Server\8.0\bin\mongodump.exe"),
        Path(r"C:\Program Files\MongoDB\Server\7.0\bin\mongodump.exe"),
    ]
    for p in known_paths:
        if p.is_file():
            return str(p)
    return None


def execute_driver_logical_export(
    mongo_db: Any,
    output_dir: Path,
    base_name: str,
    collections: List[str],
) -> Tuple[Path, Dict[str, Any]]:
    """
    Execute driver-based logical export for analytics collections and index definitions.
    Packages documents into a compressed tar.gz archive.
    """
    export_dir = output_dir / f"tmp_{base_name}"
    export_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{base_name}.tar.gz"

    collection_stats = {}
    try:
        for col_name in collections:
            col = mongo_db[col_name]
            col_file = export_dir / f"{col_name}.jsonl"
            idx_file = export_dir / f"{col_name}.indexes.json"

            # 1. Export index specifications
            indexes = list(col.list_indexes())
            with open(idx_file, "w", encoding="utf-8") as f_idx:
                f_idx.write(json_util.dumps(indexes, indent=2))

            # 2. Export documents as JSON Lines
            doc_count = 0
            with open(col_file, "w", encoding="utf-8") as f_doc:
                for doc in col.find():
                    f_doc.write(json_util.dumps(doc) + "\n")
                    doc_count += 1

            collection_stats[col_name] = {
                "document_count": doc_count,
                "index_count": len(indexes),
            }
            logger.info("Exported collection '%s': %d documents, %d indexes.", col_name, doc_count, len(indexes))

        # 3. Create compressed tar.gz bundle
        with tarfile.open(archive_path, "w:gz") as tar:
            for item in export_dir.iterdir():
                tar.add(item, arcname=item.name)

    finally:
        shutil.rmtree(export_dir, ignore_errors=True)

    return archive_path, collection_stats


def execute_mongodb_backup(
    output_dir: Path = DEFAULT_BACKUP_DIR,
    dry_run: bool = False,
    settings: Optional[Settings] = None,
    mock_db: Any = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute a consistent logical backup of MongoDB analytics collections.
    Returns (success_boolean, metadata_manifest_dictionary).
    """
    cfg = settings or get_settings()
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    target_db_name = cfg.mongodb_database
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"mongodb_{target_db_name}_{timestamp_str}"
    collections = [TELEMETRY_COLLECTION, ALERTS_COLLECTION]

    manifest: Dict[str, Any] = {
        "database_type": "mongodb_atlas",
        "database_name": target_db_name,
        "endpoint": sanitize_mongo_uri(cfg.mongodb_uri),
        "timestamp_utc": now.isoformat(),
        "collections": collections,
        "is_dry_run": dry_run,
        "status": "pending",
    }

    if dry_run:
        logger.info("[DRY-RUN] Validating MongoDB backup for database '%s' -> %s", target_db_name, output_dir)
        manifest["status"] = "dry_run_success"
        manifest["target_file"] = f"{base_name}.tar.gz"
        manifest["artifact_size_bytes"] = 0
        manifest["sha256"] = "dry_run_simulated_checksum"
        return True, manifest

    # Determine database handle (live or provided mock for testing)
    mongo_db = mock_db
    if mongo_db is None:
        if not cfg.mongodb_uri:
            err_msg = "MONGODB_URI not configured. Cannot perform live MongoDB Atlas backup."
            logger.warning(err_msg)
            manifest["status"] = "unconfigured"
            manifest["error"] = err_msg
            return False, manifest
        mongo_db = get_mongo_database(settings=cfg)

    if mongo_db is None:
        err_msg = "Failed to obtain MongoDB database connection handle."
        logger.error(err_msg)
        manifest["status"] = "connection_failure"
        manifest["error"] = err_msg
        return False, manifest

    # Try mongodump binary if available, otherwise execute driver logical export
    mongodump_bin = find_mongodump_executable()
    if mongodump_bin and not mock_db:
        logger.info("Found mongodump binary: %s. Executing native archive dump...", mongodump_bin)
        archive_path = output_dir / f"{base_name}.archive.gz"
        cmd = [
            mongodump_bin,
            f"--uri={cfg.mongodb_uri}",
            f"--archive={archive_path}",
            "--gzip",
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=300)
            if proc.returncode != 0:
                err_text = proc.stderr.decode("utf-8", errors="replace")[:1000]
                logger.error("mongodump binary failed (code %d): %s", proc.returncode, err_text)
                manifest["status"] = "failed"
                manifest["error"] = err_text
                return False, manifest
            manifest["export_method"] = "mongodump_native_archive"
            final_artifact_path = archive_path
        except Exception as exc:
            logger.error("mongodump execution error: %s", exc)
            manifest["status"] = "error"
            manifest["error"] = str(exc)
            return False, manifest
    else:
        logger.info("Executing driver-based logical bundle export...")
        try:
            final_artifact_path, stats = execute_driver_logical_export(
                mongo_db=mongo_db,
                output_dir=output_dir,
                base_name=base_name,
                collections=collections,
            )
            manifest["export_method"] = "pymongo_logical_bundle"
            manifest["collection_statistics"] = stats
        except Exception as exc:
            logger.error("Driver logical export error: %s", exc)
            manifest["status"] = "error"
            manifest["error"] = str(exc)
            return False, manifest

    # Compute checksum
    file_sha256 = compute_sha256(final_artifact_path)
    sha_file = output_dir / f"{final_artifact_path.name}.sha256"
    sha_file.write_text(f"{file_sha256}  {final_artifact_path.name}\n", encoding="utf-8")

    manifest["status"] = "completed"
    manifest["target_file"] = str(final_artifact_path.name)
    manifest["artifact_size_bytes"] = final_artifact_path.stat().st_size
    manifest["sha256"] = file_sha256
    manifest["sha256_file"] = str(sha_file.name)

    manifest_file = output_dir / f"{final_artifact_path.name}.manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info(
        "MongoDB backup completed successfully: %s (%d bytes, SHA-256: %s)",
        final_artifact_path.name,
        manifest["artifact_size_bytes"],
        file_sha256[:16] + "...",
    )
    return True, manifest


def main() -> None:
    """CLI entrypoint for MongoDB backup utility."""
    parser = argparse.ArgumentParser(description="MongoDB Atlas Analytics Mirror Backup Utility")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BACKUP_DIR, help="Target backup directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate parameters and plan without executing dump")
    args = parser.parse_args()

    success, manifest = execute_mongodb_backup(output_dir=args.output_dir, dry_run=args.dry_run)
    print(json.dumps(manifest, indent=2))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
