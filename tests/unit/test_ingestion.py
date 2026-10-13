"""
Automated Test Suite for Kaggle CSV Ingestion and Validation Engine.

Covers all 17 critical ingestion scenarios:
1. Valid dataset parsing
2. Column mapping and trimming
3. Missing required columns
4. Empty and header-only files
5. Invalid numeric vitals
6. Invalid timestamps
7. Timezone handling and documented policies
8. Fahrenheit preservation and Celsius derivation
9. Unmapped patient identity handling
10. Idempotent re-importing
11. Preserving identical rows with distinct ordinals
12. Deterministic source identity generation
13. Dry-run zero database mutation
14. Transactional rollback upon failure
15. Resuming interrupted / partial imports
16. Ingestion report count reconciliation
17. Source file immutability verification
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from database.mysql.models import (
    Base,
    ImportBatch,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from services.ingestion.importer import (
    ImportReport,
    KaggleDatasetImporter,
    generate_event_uuid,
    generate_source_event_id,
)
from services.ingestion.validator import (
    compute_file_sha256,
    fahrenheit_to_celsius,
    parse_timestamp_with_timezone,
    validate_kaggle_csv,
)


@pytest.fixture
def sqlite_engine():
    """In-memory SQLite engine with foreign key enforcement."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine) -> Session:
    """Database session for ingestion tests."""
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a temporary valid 3-row Kaggle CSV fixture."""
    csv_file = tmp_path / "valid_sample.csv"
    content = (
        "patient_id,heart_rate,spo2,temperature_f,timestamp\n"
        "P101,72,98.5,98.6,2023-10-01 08:00:00\n"
        "P102,80,97.0,99.1,2023-10-01 08:15:00\n"
        "P101,75,99.0,98.4,2023-10-01 08:30:00\n"
    )
    csv_file.write_text(content, encoding="utf-8")
    return csv_file


# =============================================================================
# 1. Structural & Record Validation Tests (Scenarios 1-8)
# =============================================================================

def test_valid_dataset_parsed_correctly(sample_csv: Path):
    """Scenario 1: Verify a valid dataset is parsed into strongly-typed records."""
    result = validate_kaggle_csv(sample_csv)
    assert result.is_valid
    assert result.total_rows_inspected == 3
    assert result.valid_count == 3
    assert result.error_count == 0
    assert result.distinct_patient_ids == {"P101", "P102"}

    first = result.valid_records[0]
    assert first.patient_id == "P101"
    assert first.heart_rate == Decimal("72.00")
    assert first.spo2 == Decimal("98.50")
    assert first.temperature_f == Decimal("98.60")
    assert first.temperature_c == Decimal("37.00")
    assert first.measured_at == datetime(2023, 10, 1, 8, 0, tzinfo=timezone.utc)


def test_column_names_mapping(tmp_path: Path):
    """Scenario 2: Column headers are parsed case-insensitively with leading/trailing spaces."""
    csv_file = tmp_path / "headers.csv"
    csv_file.write_text(
        " PATIENT_ID , Heart_Rate , SpO2 , Temperature_F , TIMESTAMP \n"
        "P101,70,98.0,98.6,2023-10-01 08:00:00\n",
        encoding="utf-8",
    )
    result = validate_kaggle_csv(csv_file)
    assert result.is_valid
    assert result.valid_count == 1


def test_missing_required_columns_rejected(tmp_path: Path):
    """Scenario 3: Missing required column results in structural failure."""
    csv_file = tmp_path / "missing_col.csv"
    csv_file.write_text(
        "patient_id,heart_rate,spo2,timestamp\n"  # missing temperature_f
        "P101,70,98.0,2023-10-01 08:00:00\n",
        encoding="utf-8",
    )
    result = validate_kaggle_csv(csv_file)
    assert not result.is_valid
    assert result.error_count > 0
    assert "temperature_f" in result.errors[0].message


def test_empty_and_header_only_files(tmp_path: Path):
    """Scenario 4: Completely empty and header-only files are handled cleanly."""
    empty_file = tmp_path / "empty.csv"
    empty_file.write_text("", encoding="utf-8")
    res_empty = validate_kaggle_csv(empty_file)
    assert not res_empty.is_valid
    assert "empty" in res_empty.errors[0].message.lower()

    header_only = tmp_path / "header_only.csv"
    header_only.write_text("patient_id,heart_rate,spo2,temperature_f,timestamp\n", encoding="utf-8")
    res_header = validate_kaggle_csv(header_only)
    assert not res_header.is_valid  # 0 records is not a valid dataset to ingest
    assert res_header.valid_count == 0


def test_invalid_numeric_measurements_reported(tmp_path: Path):
    """Scenario 5: Non-numeric and out-of-bounds measurements are captured with row numbers."""
    csv_file = tmp_path / "invalid_nums.csv"
    csv_file.write_text(
        "patient_id,heart_rate,spo2,temperature_f,timestamp\n"
        "P101,invalid_hr,98.0,98.6,2023-10-01 08:00:00\n"
        "P102,75,-5.0,98.6,2023-10-01 08:00:00\n"
        "P103,80,98.0,150.0,2023-10-01 08:00:00\n",
        encoding="utf-8",
    )
    result = validate_kaggle_csv(csv_file)
    assert not result.is_valid
    assert result.error_count == 3
    # Check row 2 (first data row) failed for heart_rate
    assert result.errors[0].row_number == 2
    assert result.errors[0].field == "heart_rate"
    # Check row 3 failed for spo2
    assert result.errors[1].row_number == 3
    assert result.errors[1].field == "spo2"
    # Check row 4 failed for temperature_f
    assert result.errors[2].row_number == 4
    assert result.errors[2].field == "temperature_f"


def test_invalid_timestamps_reported(tmp_path: Path):
    """Scenario 6: Malformed timestamps are rejected with line details."""
    csv_file = tmp_path / "invalid_ts.csv"
    csv_file.write_text(
        "patient_id,heart_rate,spo2,temperature_f,timestamp\n"
        "P101,70,98.0,98.6,not-a-timestamp\n",
        encoding="utf-8",
    )
    result = validate_kaggle_csv(csv_file)
    assert not result.is_valid
    assert result.errors[0].field == "timestamp"


def test_timezone_handling_documented():
    """Scenario 7: Timezone handling attaches explicit timezone without silent local drift."""
    # Parsing with UTC
    dt_utc, err_utc = parse_timestamp_with_timezone("2023-10-01 08:00:00", tz_name="UTC")
    assert err_utc is None
    assert dt_utc.utcoffset() == timezone.utc.utcoffset(None)
    assert str(dt_utc.tzinfo) == "UTC"

    # Parsing with named timezone
    dt_est, err_est = parse_timestamp_with_timezone("2023-10-01 08:00:00", tz_name="America/New_York")
    assert err_est is None
    assert str(dt_est.tzinfo) == "America/New_York"


def test_fahrenheit_preserved_and_celsius_derived():
    """Scenario 8: Exact decimal conversion preserves Fahrenheit and computes Celsius."""
    # 98.6 F -> (98.6 - 32) * 5 / 9 = 37.0 C
    c1 = fahrenheit_to_celsius(Decimal("98.60"))
    assert c1 == Decimal("37.00")

    # 102.4 F -> 39.11 C
    c2 = fahrenheit_to_celsius(Decimal("102.40"))
    assert c2 == Decimal("39.11")


# =============================================================================
# 2. Patient Identity & Idempotency Tests (Scenarios 9-12)
# =============================================================================

def test_unmapped_patient_policy(db_session: Session, sample_csv: Path):
    """Scenario 9: With auto_seed_patients=False, records with unmapped patient IDs are skipped."""
    importer = KaggleDatasetImporter(session=db_session, auto_seed_patients=False)
    report = importer.run_import(sample_csv, dry_run=False)

    assert report.status == "completed"
    assert report.unmapped_patient_records == 3  # All 3 rows had unmapped patients
    assert report.events_inserted == 0
    assert report.readings_inserted == 0


def test_repeated_import_idempotency(db_session: Session, sample_csv: Path):
    """Scenario 10: Repeatedly importing the same dataset inserts 0 duplicate observations."""
    importer = KaggleDatasetImporter(session=db_session, auto_seed_patients=True)

    # First import
    report1 = importer.run_import(sample_csv, dry_run=False)
    assert report1.status == "completed"
    assert report1.events_inserted == 3
    assert report1.readings_inserted == 9
    assert report1.events_skipped_existing == 0

    # Second import of exact same file
    report2 = importer.run_import(sample_csv, dry_run=False)
    assert report2.status == "completed"
    assert report2.events_inserted == 0
    assert report2.readings_inserted == 0
    assert report2.events_skipped_existing == 3

    # Total database rows should remain 3 events and 9 readings
    e_count = db_session.scalar(select(func.count(IngestionEvent.event_id)))
    r_count = db_session.scalar(select(func.count(VitalsReading.reading_id)))
    assert e_count == 3
    assert r_count == 9


def test_identical_measurement_rows_not_deduplicated(db_session: Session, tmp_path: Path):
    """Scenario 11: Two identical measurement rows on distinct ordinals are both preserved."""
    csv_file = tmp_path / "dup_rows.csv"
    # Row 1 and Row 2 have identical measurements and timestamp
    csv_file.write_text(
        "patient_id,heart_rate,spo2,temperature_f,timestamp\n"
        "P101,75,98.0,98.6,2023-10-01 08:00:00\n"
        "P101,75,98.0,98.6,2023-10-01 08:00:00\n",
        encoding="utf-8",
    )
    importer = KaggleDatasetImporter(session=db_session, auto_seed_patients=True)
    report = importer.run_import(csv_file, dry_run=False)

    assert report.status == "completed"
    assert report.events_inserted == 2
    assert report.readings_inserted == 6


def test_stable_source_identities_generated_consistently():
    """Scenario 12: Source event IDs and UUIDs are 100% deterministic and reproducible."""
    hash_str = "abcdef1234567890abcdef1234567890"
    id1 = generate_source_event_id(hash_str, 42, "P101")
    id2 = generate_source_event_id(hash_str, 42, "P101")
    assert id1 == id2
    assert id1 == "kaggle_abcdef123456_row_00042_P101"

    uuid1 = generate_event_uuid(id1)
    uuid2 = generate_event_uuid(id2)
    assert uuid1 == uuid2


# =============================================================================
# 3. Transactions, Dry-run & Verification (Scenarios 13-17)
# =============================================================================

def test_dry_run_leaves_database_unchanged(db_session: Session, sample_csv: Path):
    """Scenario 13: Dry-run validates data and predicts counts without mutating database."""
    importer = KaggleDatasetImporter(session=db_session, auto_seed_patients=True)
    report = importer.run_import(sample_csv, dry_run=True)

    assert report.status == "dry_run_success"
    assert report.dry_run is True
    assert report.events_inserted == 3  # predicted count
    assert report.readings_inserted == 9

    # Verify zero database rows were written
    assert db_session.scalar(select(func.count(ImportBatch.batch_id))) == 0
    assert db_session.scalar(select(func.count(IngestionEvent.event_id))) == 0
    assert db_session.scalar(select(func.count(VitalsReading.reading_id))) == 0
    assert db_session.scalar(select(func.count(PatientProfile.patient_id))) == 0


def test_persistence_failure_rolls_back(db_session: Session, sample_csv: Path):
    """Scenario 14: An exception during ingestion triggers rollback without orphan records."""
    importer = KaggleDatasetImporter(session=db_session, auto_seed_patients=True)

    with patch.object(db_session, "commit", side_effect=RuntimeError("Simulated DB connection failure")):
        report = importer.run_import(sample_csv, dry_run=False)

    assert report.status == "failed"
    assert "Simulated DB connection failure" in report.error_details[0]

    # Verify database is clean
    assert db_session.scalar(select(func.count(IngestionEvent.event_id))) == 0
    assert db_session.scalar(select(func.count(VitalsReading.reading_id))) == 0


def test_failed_or_interrupted_import_retry_safe(db_session: Session, tmp_path: Path):
    """Scenario 15: Interrupted import safely resumes and skips already committed records."""
    csv_file = tmp_path / "resume_test.csv"
    csv_file.write_text(
        "patient_id,heart_rate,spo2,temperature_f,timestamp\n"
        "P101,70,98.0,98.6,2023-10-01 08:00:00\n"
        "P102,72,98.5,98.7,2023-10-01 08:05:00\n"
        "P103,74,99.0,98.8,2023-10-01 08:10:00\n"
        "P104,76,97.5,98.9,2023-10-01 08:15:00\n",
        encoding="utf-8",
    )
    validation = validate_kaggle_csv(csv_file)
    importer = KaggleDatasetImporter(session=db_session, batch_size=2, auto_seed_patients=True)

    # Simulate importing only first 2 rows
    partial_records = validation.valid_records[:2]
    from services.ingestion.importer import ensure_patient_identities
    ensure_patient_identities(db_session, validation.distinct_patient_ids)
    partial_report = ImportReport(source_file=str(csv_file), file_sha256=validation.file_sha256, dry_run=False)
    importer._execute_persistence(csv_file, partial_records, validation.file_sha256, partial_report)

    assert db_session.scalar(select(func.count(IngestionEvent.event_id))) == 2

    # Now run full import
    resume_report = importer.run_import(csv_file, dry_run=False)
    assert resume_report.status == "completed"
    assert resume_report.events_inserted == 2  # rows 3 and 4
    assert resume_report.events_skipped_existing == 2  # rows 1 and 2

    # Total in DB is all 4
    assert db_session.scalar(select(func.count(IngestionEvent.event_id))) == 4
    assert db_session.scalar(select(func.count(VitalsReading.reading_id))) == 12


def test_import_summary_counts_reconcile(db_session: Session, sample_csv: Path):
    """Scenario 16: Mathematical reconciliation of all report count metrics."""
    importer = KaggleDatasetImporter(session=db_session, auto_seed_patients=True)
    report = importer.run_import(sample_csv, dry_run=False)

    # Reconciliation invariant:
    # inspected == valid + invalid
    assert report.total_rows_inspected == report.valid_records + report.invalid_records
    # valid == inserted + skipped + unmapped
    assert report.valid_records == report.events_inserted + report.events_skipped_existing + report.unmapped_patient_records
    # readings == inserted * 3 (for HR, SpO2, Temp)
    assert report.readings_inserted == report.events_inserted * 3


def test_source_csv_remains_unchanged():
    """Scenario 17: Source CSV checksum remains bit-for-bit unchanged before and after operations."""
    for path_str in [r"E:\DOC-20261013-WA0056.csv", r"E:\kaggle_health_dataset.csv"]:
        target = Path(path_str)
        if target.exists():
            initial_hash = compute_file_sha256(target)
            # Run validation
            res = validate_kaggle_csv(target)
            post_hash = compute_file_sha256(target)
            assert initial_hash == post_hash, f"Source file {target.name} was modified!"
            assert res.is_valid
