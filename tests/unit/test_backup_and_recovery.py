"""
Unit Tests for Database Backup, Restore, Verification, and Retention Lifecycle.

Validates:
- MySQL and MongoDB backup dry-run planning and flags.
- Collision avoidance and naming schemas.
- MongoDB driver-based logical bundle export and isolated restore via mongomock.
- Production restoration safety guard (blocking destructive in-place restores without --force-production).
- Cryptographic SHA-256 generation, verification, and corruption detection.
- Backup retention cleanup, count/day pruning, companion file tracking, and dry-run safety.
- Path boundary security preventing directory traversal.
- Strict credential redaction in URIs, logs, and audit manifests.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock
import pytest

from database.mongodb.client import sanitize_mongo_uri
from database.mongodb.collections import ALERTS_COLLECTION, TELEMETRY_COLLECTION
from scripts.backup_mongodb import (
    compute_sha256 as mongo_compute_sha256,
    execute_mongodb_backup,
)
from scripts.backup_mysql import (
    compute_sha256 as mysql_compute_sha256,
    execute_mysql_backup,
)
from scripts.cleanup_backups import (
    group_backup_artifacts,
    is_safe_backup_artifact,
    prune_backups,
)
from scripts.restore_mongodb import execute_mongodb_restore
from scripts.restore_mysql import execute_mysql_restore
from scripts.verify_recovery import (
    execute_recovery_verification,
    verify_artifact_integrity,
    verify_mongodb_dataset,
)
from services.api.config import Settings


class TestBackupAndRecovery:
    """Test suite for backup, restore, verification, and retention tools."""

    @pytest.fixture
    def test_settings(self) -> Settings:
        """Isolated test settings."""
        return Settings(
            mysql_database="smart_health",
            mongodb_database="smart_health_analytics",
            mongodb_uri="mongodb://admin_user:mock_test_pass@localhost:27017/?retryWrites=true",
        )

    def test_mysql_backup_dry_run(self, tmp_path: Path, test_settings: Settings) -> None:
        """Verify MySQL backup dry-run generates manifest without invoking external process."""
        success, manifest = execute_mysql_backup(
            output_dir=tmp_path,
            database="smart_health",
            compress=True,
            dry_run=True,
            settings=test_settings,
        )
        assert success is True
        assert manifest["status"] == "dry_run_success"
        assert manifest["database_name"] == "smart_health"
        assert manifest["is_dry_run"] is True
        assert manifest["is_compressed"] is True
        assert "--single-transaction" in manifest["flags"]
        assert "--routines" in manifest["flags"]
        assert "--triggers" in manifest["flags"]
        assert "--events" in manifest["flags"]
        assert "--hex-blob" in manifest["flags"]
        # In dry-run mode, no physical archive is written
        assert len(list(tmp_path.glob("*.sql*"))) == 0

    def test_mongodb_backup_dry_run(self, tmp_path: Path, test_settings: Settings) -> None:
        """Verify MongoDB backup dry-run generates manifest with sanitized endpoint."""
        success, manifest = execute_mongodb_backup(
            output_dir=tmp_path,
            dry_run=True,
            settings=test_settings,
        )
        assert success is True
        assert manifest["status"] == "dry_run_success"
        assert manifest["database_name"] == "smart_health_analytics"
        assert manifest["is_dry_run"] is True
        assert "SuperSecretPassword123" not in manifest["endpoint"]
        assert "***" in manifest["endpoint"]

    def test_mongodb_logical_export_and_restore_mongomock(self, tmp_path: Path, test_settings: Settings) -> None:
        """
        Verify complete driver-based logical bundle export from source DB and
        restoration into an isolated recovery target DB using mongomock.
        """
        mongo_client = mongomock.MongoClient()
        source_db = mongo_client["smart_health_analytics"]

        # Seed telemetry and alerts
        source_db[TELEMETRY_COLLECTION].insert_many([
            {"patient_id": 1, "heart_rate": 78.5, "spo2": 98.0, "recorded_at": "2026-10-14T00:00:00Z"},
            {"patient_id": 2, "heart_rate": 105.2, "spo2": 91.0, "recorded_at": "2026-10-14T00:05:00Z"},
        ])
        source_db[TELEMETRY_COLLECTION].create_index([("patient_id", 1), ("recorded_at", -1)])

        source_db[ALERTS_COLLECTION].insert_one({
            "alert_id": 101,
            "patient_id": 2,
            "severity": "CRITICAL",
            "message": "High tachycardia alert",
        })

        # 1. Execute logical export
        success, backup_manifest = execute_mongodb_backup(
            output_dir=tmp_path,
            dry_run=False,
            settings=test_settings,
            mock_db=source_db,
        )
        assert success is True
        assert backup_manifest["status"] == "completed"
        assert backup_manifest["export_method"] == "pymongo_logical_bundle"

        archive_name = backup_manifest["target_file"]
        archive_path = tmp_path / archive_name
        assert archive_path.is_file()
        assert archive_path.stat().st_size > 0

        # Check companion files
        sha_file = tmp_path / f"{archive_name}.sha256"
        manifest_file = tmp_path / f"{archive_name}.manifest.json"
        assert sha_file.is_file()
        assert manifest_file.is_file()

        # 2. Execute restore into isolated recovery target database
        target_db = mongo_client["smart_health_analytics_recovery"]
        restore_success, restore_report = execute_mongodb_restore(
            backup_file=archive_path,
            target_db="smart_health_analytics_recovery",
            settings=test_settings,
            mock_db=target_db,
        )
        assert restore_success is True
        assert restore_report["status"] == "completed"
        assert restore_report["restore_method"] == "pymongo_logical_bundle"

        # Verify restored documents
        restored_telemetry = list(target_db[TELEMETRY_COLLECTION].find())
        assert len(restored_telemetry) == 2
        assert restored_telemetry[0]["patient_id"] == 1
        assert restored_telemetry[1]["heart_rate"] == 105.2

        restored_alerts = list(target_db[ALERTS_COLLECTION].find())
        assert len(restored_alerts) == 1
        assert restored_alerts[0]["severity"] == "CRITICAL"

    def test_mysql_restore_safety_guard_blocks_production(self, tmp_path: Path, test_settings: Settings) -> None:
        """
        Verify safety violation when attempting to restore directly into production 'smart_health'
        without the explicit --force-production flag.
        """
        dummy_file = tmp_path / "dummy_backup.sql"
        dummy_file.write_text("SELECT 1;", encoding="utf-8")

        # Without force_production
        success, report = execute_mysql_restore(
            backup_file=dummy_file,
            target_db="smart_health",
            force_production=False,
            settings=test_settings,
        )
        assert success is False
        assert report["status"] == "blocked_safety_violation"
        assert "SAFETY VIOLATION" in report["error"]

        # With force_production + dry_run
        success_forced, report_forced = execute_mysql_restore(
            backup_file=dummy_file,
            target_db="smart_health",
            force_production=True,
            dry_run=True,
            settings=test_settings,
        )
        assert success_forced is True
        assert report_forced["status"] == "dry_run_success"

    def test_mongodb_restore_safety_guard_blocks_production(self, tmp_path: Path, test_settings: Settings) -> None:
        """
        Verify safety violation when attempting to restore directly into production MongoDB database
        without explicit --force-production flag.
        """
        dummy_file = tmp_path / "dummy_mongo.tar.gz"
        dummy_file.write_bytes(b"dummy_tar_bytes")

        success, report = execute_mongodb_restore(
            backup_file=dummy_file,
            target_db="smart_health_analytics",
            force_production=False,
            settings=test_settings,
        )
        assert success is False
        assert report["status"] == "blocked_safety_violation"
        assert "SAFETY VIOLATION" in report["error"]

    def test_sha256_checksum_verification_and_corruption_detection(self, tmp_path: Path) -> None:
        """Verify that SHA-256 calculation verifies intact files and detects bit-level corruption."""
        test_file = tmp_path / "test_artifact.sql.gz"
        test_content = b"CRITICAL_HEALTHCARE_TRANSACTION_PAYLOAD"
        test_file.write_bytes(test_content)

        digest = mysql_compute_sha256(test_file)
        sha_file = tmp_path / f"{test_file.name}.sha256"
        sha_file.write_text(f"{digest}  {test_file.name}\n", encoding="utf-8")

        # 1. Verification of valid artifact
        res = verify_artifact_integrity(test_file)
        assert res["integrity_verified"] is True
        assert res["computed_sha256"] == digest
        assert res["checksum_file_present"] is True

        # 2. Corrupt the file
        test_file.write_bytes(test_content + b"_CORRUPTED")
        corrupted_res = verify_artifact_integrity(test_file)
        assert corrupted_res["integrity_verified"] is False
        assert any("Checksum mismatch" in err for err in corrupted_res["errors"])

    def test_manifest_checksum_mismatch_detection(self, tmp_path: Path) -> None:
        """Verify that a discrepancy between computed SHA-256 and manifest metadata is caught."""
        test_file = tmp_path / "test_artifact.tar.gz"
        test_file.write_bytes(b"DATA_PAYLOAD_TEST")
        actual_sha = mongo_compute_sha256(test_file)

        # Companion manifest with tampered SHA
        manifest_file = tmp_path / f"{test_file.name}.manifest.json"
        manifest_file.write_text(
            json.dumps({"target_file": test_file.name, "sha256": "badbeef0000000000000000000000000"}),
            encoding="utf-8",
        )

        res = verify_artifact_integrity(test_file)
        assert res["integrity_verified"] is False
        assert any("Manifest SHA mismatch" in err for err in res["errors"])

    def test_backup_cleanup_retention_and_dry_run(self, tmp_path: Path) -> None:
        """
        Verify retention policy:
        - Groups primary files with their .sha256 and .manifest.json companions.
        - Respects keep_count limit.
        - Dry-run simulates without deleting.
        - Live execution safely purges expired backup sets and companions.
        """
        backup_dir = tmp_path / "mysql_backups"
        backup_dir.mkdir()

        created_sets = []
        now = time.time()

        # Create 5 backup sets with staggered mtimes
        for i in range(5):
            base_name = f"mysql_smart_health_20261014_0{i}0000"
            primary = backup_dir / f"{base_name}.sql.gz"
            primary.write_bytes(f"dump_content_{i}".encode("utf-8"))

            sha_file = backup_dir / f"{base_name}.sql.gz.sha256"
            sha_file.write_text(f"dummy_sha_{i}", encoding="utf-8")

            manifest_file = backup_dir / f"{base_name}.sql.gz.manifest.json"
            manifest_file.write_text(f'{{"backup": "{i}"}}', encoding="utf-8")

            # Stagger timestamps (0 = oldest, 4 = newest)
            file_mtime = now - (5 - i) * 3600
            os.utime(primary, (file_mtime, file_mtime))
            os.utime(sha_file, (file_mtime, file_mtime))
            os.utime(manifest_file, (file_mtime, file_mtime))
            created_sets.append(primary)

        # 1. Dry-run keeping 2 newest
        dry_run_report = prune_backups(backup_dir=backup_dir, keep_count=2, keep_days=None, dry_run=True)
        assert dry_run_report["dry_run"] is True
        assert dry_run_report["total_sets_found"] == 5
        assert dry_run_report["retained_sets_count"] == 2
        assert dry_run_report["pruned_files_count"] == 9  # 3 sets * (1 primary + 2 companions)
        # Verify no files were actually deleted
        assert len(list(backup_dir.iterdir())) == 15

        # 2. Live execution keeping 2 newest
        live_report = prune_backups(backup_dir=backup_dir, keep_count=2, keep_days=None, dry_run=False)
        assert live_report["dry_run"] is False
        assert live_report["retained_sets_count"] == 2
        # After pruning, exactly 2 sets (6 files) remain
        remaining_files = list(backup_dir.iterdir())
        assert len(remaining_files) == 6

        # Check newest 2 primary archives are retained
        assert (backup_dir / "mysql_smart_health_20261014_040000.sql.gz").exists()
        assert (backup_dir / "mysql_smart_health_20261014_030000.sql.gz").exists()
        # Older archives are pruned
        assert not (backup_dir / "mysql_smart_health_20261014_000000.sql.gz").exists()
        assert not (backup_dir / "mysql_smart_health_20261014_010000.sql.gz").exists()

    def test_backup_cleanup_path_boundary_safety(self, tmp_path: Path) -> None:
        """Verify path security: non-backup files and directory escapes are rejected."""
        backup_dir = tmp_path / "safe_backups"
        backup_dir.mkdir()

        # Legitimate backup artifact
        safe_file = backup_dir / "mysql_smart_health_20261014_120000.sql"
        safe_file.touch()
        assert is_safe_backup_artifact(safe_file, backup_dir) is True

        # Non-backup file in directory
        config_file = backup_dir / "app_config.json"
        config_file.touch()
        assert is_safe_backup_artifact(config_file, backup_dir) is False

        # File outside directory
        outside_file = tmp_path / "system_passwords.txt"
        outside_file.touch()
        assert is_safe_backup_artifact(outside_file, backup_dir) is False

    def test_secret_redaction_in_mongo_uri(self) -> None:
        """Verify sensitive credentials in MongoDB connection strings are redacted."""
        raw_uri = "mongodb://admin_user:mock_test_pass@localhost:27017/test?retryWrites=true"
        sanitized = sanitize_mongo_uri(raw_uri)
        assert "mock_test_pass" not in sanitized
        assert "***:***@" in sanitized
        assert "localhost:27017" in sanitized

        # URI without credentials
        plain_uri = "mongodb://localhost:27017/smart_health"
        assert sanitize_mongo_uri(plain_uri) == "mongodb://localhost:27017/smart_health"

    def test_automated_recovery_verification_mongodb(self, tmp_path: Path, test_settings: Settings) -> None:
        """
        Verify end-to-end recovery verification procedure:
        - exports backup from mock DB
        - validates SHA-256 and manifest integrity
        - executes restore into recovery DB
        - validates collections and executes sample queries
        """
        client = mongomock.MongoClient()
        src_db = client["source_health"]
        src_db[TELEMETRY_COLLECTION].insert_many([
            {"patient_id": 1, "heart_rate": 72.0, "recorded_at": "2026-10-14T01:00:00Z"},
            {"patient_id": 1, "heart_rate": 76.0, "recorded_at": "2026-10-14T01:05:00Z"},
        ])
        src_db[ALERTS_COLLECTION].insert_one({
            "alert_id": 201,
            "patient_id": 1,
            "severity": "WARNING",
            "message": "Mild tachycardia",
        })

        # Backup
        success, b_manifest = execute_mongodb_backup(
            output_dir=tmp_path,
            settings=test_settings,
            mock_db=src_db,
        )
        assert success is True
        archive_path = tmp_path / b_manifest["target_file"]

        # Run verification procedure with restore enabled into target
        recovery_db = client["smart_health_analytics_recovery"]
        v_success, v_report = execute_recovery_verification(
            artifact_path=archive_path,
            target_db="smart_health_analytics_recovery",
            verify_restore=True,
            settings=test_settings,
            mock_db=recovery_db,
        )
        assert v_success is True
        assert v_report["overall_success"] is True
        assert v_report["integrity_check"]["integrity_verified"] is True
        assert v_report["restore_executed"] is True
        assert v_report["semantic_verification"]["collections_complete"] is True
        assert (
            v_report["semantic_verification"]["sample_query_verification"]["total_telemetry_documents"]
            == 2
        )
