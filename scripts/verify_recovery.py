"""
Automated Recovery Verification Procedure.

Safety and Verification Invariants:
- Validates physical backup artifact existence, non-zero size, and SHA-256 checksums.
- Verifies manifest metadata consistency.
- Performs end-to-end dry-run or live isolated restoration into recovery databases.
- Audits recovered schema completeness, core table/collection presence, and record counts.
- Executes sample verification queries against restored datasets to ensure data readability.

Usage:
    python -m scripts.verify_recovery --artifact-path PATH [--target-db DB] [--verify-restore] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from database.mongodb.collections import ALERTS_COLLECTION, TELEMETRY_COLLECTION
from services.api.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_recovery")

DEFAULT_MYSQL_RECOVERY_DB = "smart_health_recovery"
DEFAULT_MONGO_RECOVERY_DB = "smart_health_analytics_recovery"

CORE_MYSQL_TABLES = [
    "users",
    "patient_profiles",
    "doctor_profiles",
    "vitals_readings",
    "alerts",
    "analytics_outbox",
    "audit_logs",
]

CORE_MONGO_COLLECTIONS = [
    TELEMETRY_COLLECTION,
    ALERTS_COLLECTION,
]


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hexadecimal digest of a physical file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_artifact_integrity(file_path: Path) -> Dict[str, Any]:
    """
    Verify physical file existence, non-zero size, and SHA-256 checksum matches.
    """
    result: Dict[str, Any] = {
        "file_path": str(file_path),
        "exists": False,
        "size_bytes": 0,
        "computed_sha256": None,
        "checksum_file_present": False,
        "manifest_present": False,
        "integrity_verified": False,
        "errors": [],
    }

    if not file_path.is_file():
        result["errors"].append(f"Artifact not found: '{file_path}'")
        return result

    result["exists"] = True
    result["size_bytes"] = file_path.stat().st_size

    if result["size_bytes"] == 0:
        result["errors"].append("Artifact is empty (0 bytes)")
        return result

    # Compute actual digest
    actual_sha = compute_sha256(file_path)
    result["computed_sha256"] = actual_sha

    # Check companion .sha256 file
    sha_file = file_path.parent / f"{file_path.name}.sha256"
    if sha_file.is_file():
        result["checksum_file_present"] = True
        try:
            expected_sha = sha_file.read_text(encoding="utf-8").split()[0].strip().lower()
            if actual_sha.lower() != expected_sha:
                result["errors"].append(f"Checksum mismatch: expected {expected_sha}, computed {actual_sha}")
                return result
        except Exception as exc:
            result["errors"].append(f"Error reading .sha256 file: {exc}")
            return result

    # Check companion manifest file
    manifest_file = file_path.parent / f"{file_path.name}.manifest.json"
    if manifest_file.is_file():
        result["manifest_present"] = True
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            if "sha256" in manifest_data:
                m_sha = manifest_data["sha256"].strip().lower()
                if actual_sha.lower() != m_sha:
                    result["errors"].append(f"Manifest SHA mismatch: manifest has {m_sha}, computed {actual_sha}")
                    return result
        except Exception as exc:
            result["errors"].append(f"Error parsing manifest file: {exc}")
            return result

    result["integrity_verified"] = len(result["errors"]) == 0
    return result


def verify_mysql_dataset(
    engine: Any,
    expected_tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Inspect MySQL database tables, record counts, and run sample analytical query.
    """
    from sqlalchemy import inspect, text

    expected = expected_tables or CORE_MYSQL_TABLES
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    missing_tables = [t for t in expected if t not in existing_tables]
    table_counts: Dict[str, int] = {}

    with engine.connect() as conn:
        for t in expected:
            if t in existing_tables:
                try:
                    row_count = conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
                    table_counts[t] = int(row_count or 0)
                except Exception as exc:
                    table_counts[t] = -1
                    logger.warning("Could not count rows in '%s': %s", t, exc)

        # Sample analytical query verification
        sample_query_result: Dict[str, Any] = {}
        if "vitals_readings" in existing_tables:
            try:
                row = conn.execute(
                    text("SELECT COUNT(*), AVG(heart_rate), AVG(spo2), AVG(temperature_f) FROM vitals_readings")
                ).fetchone()
                if row:
                    sample_query_result = {
                        "vitals_count": row[0],
                        "avg_heart_rate": float(row[1]) if row[1] is not None else None,
                        "avg_spo2": float(row[2]) if row[2] is not None else None,
                        "avg_temperature_f": float(row[3]) if row[3] is not None else None,
                    }
            except Exception as q_exc:
                logger.warning("Sample vitals query failed: %s", q_exc)

    return {
        "existing_tables_count": len(existing_tables),
        "missing_core_tables": missing_tables,
        "table_row_counts": table_counts,
        "sample_query_verification": sample_query_result,
        "schema_complete": len(missing_tables) == 0,
    }


def verify_mongodb_dataset(
    db_handle: Any,
    expected_collections: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Inspect MongoDB database collections, document counts, indexes, and sample queries.
    """
    expected = expected_collections or CORE_MONGO_COLLECTIONS
    existing_cols = set(db_handle.list_collection_names())
    missing_cols = [c for c in expected if c not in existing_cols]

    col_stats: Dict[str, Any] = {}
    for c in expected:
        if c in existing_cols:
            col = db_handle[c]
            doc_count = col.count_documents({})
            indexes = [idx.get("name") for idx in col.list_indexes()]
            col_stats[c] = {
                "document_count": doc_count,
                "index_names": indexes,
            }

    # Sample query verification
    sample_result: Dict[str, Any] = {}
    if TELEMETRY_COLLECTION in existing_cols:
        col = db_handle[TELEMETRY_COLLECTION]
        try:
            pipeline = [
                {"$group": {"_id": None, "total_records": {"$sum": 1}, "avg_hr": {"$avg": "$heart_rate"}}}
            ]
            agg = list(col.aggregate(pipeline))
            if agg:
                sample_result = {
                    "total_telemetry_documents": agg[0].get("total_records"),
                    "avg_heart_rate": round(agg[0].get("avg_hr", 0), 2) if agg[0].get("avg_hr") else None,
                }
        except Exception as agg_exc:
            logger.warning("Sample MongoDB aggregation query failed: %s", agg_exc)

    return {
        "existing_collections": list(existing_cols),
        "missing_core_collections": missing_cols,
        "collection_statistics": col_stats,
        "sample_query_verification": sample_result,
        "collections_complete": len(missing_cols) == 0,
    }


def execute_recovery_verification(
    artifact_path: Path,
    target_db: Optional[str] = None,
    verify_restore: bool = False,
    dry_run: bool = False,
    settings: Optional[Settings] = None,
    mock_db: Any = None,
    mock_engine: Any = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Full recovery verification entrypoint for either MySQL or MongoDB backup artifacts.
    """
    cfg = settings or get_settings()
    filename = artifact_path.name.lower()
    is_mysql = "mysql" in filename or filename.endswith(".sql") or filename.endswith(".sql.gz")
    is_mongo = "mongodb" in filename or filename.endswith(".tar.gz") or filename.endswith(".archive.gz")

    if not is_mysql and not is_mongo:
        # Default heuristic
        if filename.endswith(".gz") and not filename.endswith(".sql.gz"):
            is_mongo = True
        else:
            is_mysql = True

    db_type = "mysql" if is_mysql else "mongodb"
    resolved_target = target_db or (DEFAULT_MYSQL_RECOVERY_DB if is_mysql else DEFAULT_MONGO_RECOVERY_DB)

    report: Dict[str, Any] = {
        "verification_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "database_type": db_type,
        "artifact_path": str(artifact_path),
        "target_database": resolved_target,
        "dry_run": dry_run,
        "integrity_check": {},
        "restore_executed": False,
        "semantic_verification": {},
        "overall_success": False,
    }

    # Step 1: Physical and cryptographic verification
    integrity = verify_artifact_integrity(artifact_path)
    report["integrity_check"] = integrity

    if not integrity.get("integrity_verified"):
        logger.error("Artifact integrity verification failed: %s", integrity.get("errors"))
        return False, report

    logger.info("Artifact '%s' passed cryptographic integrity checks.", artifact_path.name)

    if dry_run or not verify_restore:
        report["overall_success"] = integrity["integrity_verified"]
        return report["overall_success"], report

    # Step 2: Live isolated recovery & semantic query verification
    if is_mysql:
        from scripts.restore_mysql import execute_mysql_restore
        from sqlalchemy import create_engine

        restore_success, restore_report = execute_mysql_restore(
            backup_file=artifact_path,
            target_db=resolved_target,
            settings=cfg,
        )
        report["restore_executed"] = True
        report["restore_report"] = restore_report

        if not restore_success:
            logger.error("MySQL restoration into '%s' failed.", resolved_target)
            return False, report

        # Semantic check
        engine = mock_engine
        if engine is None:
            db_url = f"mysql+pymysql://{cfg.mysql_user}:{cfg.mysql_password}@{cfg.mysql_host}:{cfg.mysql_port}/{resolved_target}?charset=utf8mb4"
            engine = create_engine(db_url)

        semantic_res = verify_mysql_dataset(engine=engine)
        report["semantic_verification"] = semantic_res
        report["overall_success"] = semantic_res.get("schema_complete", False)
        return report["overall_success"], report

    else:
        from scripts.restore_mongodb import execute_mongodb_restore

        restore_success, restore_report = execute_mongodb_restore(
            backup_file=artifact_path,
            target_db=resolved_target,
            settings=cfg,
            mock_db=mock_db,
        )
        report["restore_executed"] = True
        report["restore_report"] = restore_report

        if not restore_success:
            logger.error("MongoDB restoration into '%s' failed.", resolved_target)
            return False, report

        # Semantic check
        db_handle = mock_db
        if db_handle is None:
            from database.mongodb.client import get_mongo_client
            client = get_mongo_client(settings=cfg)
            if client is None:
                report["semantic_verification"] = {"error": "Failed to connect to MongoDB cluster"}
                return False, report
            db_handle = client[resolved_target]

        semantic_res = verify_mongodb_dataset(db_handle=db_handle)
        report["semantic_verification"] = semantic_res
        report["overall_success"] = semantic_res.get("collections_complete", False)
        return report["overall_success"], report


def main() -> None:
    """CLI entrypoint for automated recovery verification."""
    parser = argparse.ArgumentParser(description="Automated Recovery Verification Procedure")
    parser.add_argument("--artifact-path", type=Path, required=True, help="Path to backup artifact")
    parser.add_argument("--target-db", type=str, default=None, help="Target recovery database name")
    parser.add_argument("--verify-restore", action="store_true", help="Execute isolated test restore and query check")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run integrity validation")
    args = parser.parse_args()

    success, report = execute_recovery_verification(
        artifact_path=args.artifact_path,
        target_db=args.target_db,
        verify_restore=args.verify_restore,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
