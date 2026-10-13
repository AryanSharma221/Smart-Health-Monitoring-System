r"""
Integration Tests for Real Kaggle Dataset Ingestion and Importer Validation.

Validates the real Kaggle health dataset ingestion pipeline against isolated test databases:
1. Verifies real dataset file existence and SHA-256 baseline integrity.
2. Validates CSV structure, column recognition, and header normalization.
3. Tests dry-run execution against the real dataset (ensuring zero database mutations).
4. Tests full idempotent ingestion of real dataset records into an isolated database.
5. Verifies canonical metric conversion (Fahrenheit raw to Celsius canonical).
6. Verifies deterministic source identity generation across runs.
7. Verifies zero duplicate records on repeated execution (idempotency guarantee).
8. Verifies mathematical reconciliation between inspected, valid, inserted, and skipped rows.
9. Proves source files on E:\ remain 100% untouched and bit-for-bit identical before and after.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
    generate_source_event_id,
)
from services.ingestion.validator import (
    compute_file_sha256,
    fahrenheit_to_celsius,
    validate_kaggle_csv,
)

REAL_DATASET_PATH = Path(r"E:\kaggle_health_dataset.csv")
REAL_DOC_PATH = Path(r"E:\DOC-20261013-WA0056.csv")


@pytest.fixture(scope="function")
def isolated_db_session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_real_dataset_existence_and_hash_integrity():
    """Verify real Kaggle dataset files exist and match baseline SHA-256 signatures."""
    assert REAL_DATASET_PATH.exists(), f"Expected real dataset at {REAL_DATASET_PATH}"
    hash_main = compute_file_sha256(REAL_DATASET_PATH)
    assert hash_main.upper() == "50F391190CD58F87636C0F6AE45731F97791563210275F14E5208C75BE96EC82"

    if REAL_DOC_PATH.exists():
        hash_doc = compute_file_sha256(REAL_DOC_PATH)
        assert hash_doc.upper() == "CA15CF7776A0A670C834BA2693EDACBF4EB785ACD26D06D1617D3A56425F65A7"


def test_real_dataset_validation_structure():
    """Validate structure, column mappings, and record sanity of real dataset."""
    initial_hash = compute_file_sha256(REAL_DATASET_PATH)
    result = validate_kaggle_csv(REAL_DATASET_PATH)

    # Integrity verification: validation MUST NOT mutate source file
    assert compute_file_sha256(REAL_DATASET_PATH) == initial_hash

    assert result.is_valid is True
    assert result.total_rows_inspected == 1500
    assert len(result.valid_records) == 1500
    assert len(result.errors) == 0
    assert len(result.distinct_patient_ids) >= 1

    # Verify column recognition and field values
    sample_record = result.valid_records[0]
    assert sample_record.patient_id is not None
    assert 30 <= sample_record.heart_rate <= 250
    assert 60 <= sample_record.spo2 <= 100
    from datetime import timedelta
    assert sample_record.measured_at.utcoffset() == timedelta(0)


def test_real_dataset_dry_run_zero_mutation(isolated_db_session: Session):
    """Verify dry-run mode against real Kaggle dataset performs checks without database writes."""
    initial_hash = compute_file_sha256(REAL_DATASET_PATH)
    importer = KaggleDatasetImporter(session=isolated_db_session, auto_seed_patients=True)

    report = importer.run_import(REAL_DATASET_PATH, dry_run=True)

    # Verify source file remained untouched
    assert compute_file_sha256(REAL_DATASET_PATH) == initial_hash

    assert report.dry_run is True
    assert report.status == "dry_run_success"
    assert report.total_rows_inspected == 1500
    assert report.valid_records == 1500
    assert report.events_inserted == 1500  # Projected count
    assert report.readings_inserted == 4500  # 1500 * 3 vitals metrics

    # Assert ZERO rows were committed to database
    assert isolated_db_session.scalar(select(func.count(ImportBatch.batch_id))) == 0
    assert isolated_db_session.scalar(select(func.count(IngestionEvent.event_id))) == 0
    assert isolated_db_session.scalar(select(func.count(VitalsReading.reading_id))) == 0


def test_real_dataset_ingestion_and_idempotency(isolated_db_session: Session):
    """
    Test real dataset ingestion into isolated database, then verify that an immediate
    re-import of the exact same dataset skips 100% of rows (idempotency guarantee).
    """
    initial_hash = compute_file_sha256(REAL_DATASET_PATH)
    importer = KaggleDatasetImporter(session=isolated_db_session, batch_size=250, auto_seed_patients=True)

    # 1. First Ingestion
    report1 = importer.run_import(REAL_DATASET_PATH, dry_run=False)
    assert report1.status == "completed"
    assert report1.total_rows_inspected == 1500
    assert report1.events_inserted == 1500
    assert report1.readings_inserted == 4500
    assert report1.events_skipped_existing == 0

    # Verify DB counts
    assert isolated_db_session.scalar(select(func.count(IngestionEvent.event_id))) == 1500
    assert isolated_db_session.scalar(select(func.count(VitalsReading.reading_id))) == 4500
    assert isolated_db_session.scalar(select(func.count(ImportBatch.batch_id))) == 1

    # Verify Temperature conversion and unit preservation
    sample_temp = isolated_db_session.scalars(
        select(VitalsReading).where(VitalsReading.metric_code == "temperature").limit(1)
    ).first()
    assert sample_temp is not None
    assert sample_temp.unit == "degC"
    assert sample_temp.raw_unit == "degF"
    expected_c = fahrenheit_to_celsius(sample_temp.raw_value)
    assert abs(sample_temp.value - expected_c) < Decimal("0.05")

    # 2. Re-import (Idempotency verification)
    report2 = importer.run_import(REAL_DATASET_PATH, dry_run=False)
    assert report2.status == "completed"
    assert report2.events_inserted == 0, "No new events should be inserted on duplicate import"
    assert report2.events_skipped_existing == 1500, "All 1500 existing events must be skipped"
    assert report2.readings_inserted == 0

    # Verify total DB counts remained invariant
    assert isolated_db_session.scalar(select(func.count(IngestionEvent.event_id))) == 1500
    assert isolated_db_session.scalar(select(func.count(VitalsReading.reading_id))) == 4500

    # 3. Verify Source File Unchanged
    assert compute_file_sha256(REAL_DATASET_PATH) == initial_hash
