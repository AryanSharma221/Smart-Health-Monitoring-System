"""
Kaggle Dataset Importer and Ingestion Service.

Implements transactional, idempotent CSV ingestion into MySQL 8 InnoDB:
- Validates structure and records using validator.py.
- Resolves and seeds patient identities.
- Generates stable, deterministic source event IDs based on file SHA-256 and row ordinals.
- Expands each health event into 3 canonical vitals readings (heart_rate, spo2, temperature).
- Preserves raw Fahrenheit while storing canonical Celsius.
- Enforces database idempotency: repeated imports skip already existing events.
- Supports dry-run execution without mutating the database.
- Generates comprehensive, audit-ready import reports.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.mysql.models import (
    ImportBatch,
    IngestionEvent,
    PatientProfile,
    User,
    VitalsReading,
)
from database.mysql.repositories import PatientRepository, VitalsRepository
from services.ingestion.validator import (
    DatasetValidationResult,
    ParsedKaggleRow,
    validate_kaggle_csv,
)

logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    """Detailed audit report produced after ingestion or dry-run execution."""
    source_file: str
    file_sha256: str
    dry_run: bool
    total_rows_inspected: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    unmapped_patient_records: int = 0
    events_inserted: int = 0
    readings_inserted: int = 0
    events_skipped_existing: int = 0
    batches_processed: int = 0
    status: str = "pending"  # completed, dry_run_success, failed
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error_details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        """Convert report to dictionary for JSON serialization and metadata logging."""
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        d["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        return d

    def format_console_report(self) -> str:
        """Format human-readable summary for CLI and logs."""
        duration = ""
        if self.completed_at:
            elapsed = (self.completed_at - self.started_at).total_seconds()
            duration = f" ({elapsed:.2f}s)"

        lines = [
            "=" * 70,
            f"KAGGLE DATASET INGESTION REPORT{' [DRY-RUN]' if self.dry_run else ''}",
            "=" * 70,
            f"Source File:            {self.source_file}",
            f"SHA-256 Checksum:       {self.file_sha256}",
            f"Status:                 {self.status.upper()}{duration}",
            "-" * 70,
            f"Total Rows Inspected:   {self.total_rows_inspected:,}",
            f"Valid Records:          {self.valid_records:,}",
            f"Invalid Records:        {self.invalid_records:,}",
            f"Unmapped Patient Rows:  {self.unmapped_patient_records:,}",
            "-" * 70,
            f"Events Inserted:        {self.events_inserted:,}",
            f"Readings Inserted:      {self.readings_inserted:,}",
            f"Events Skipped (Exist): {self.events_skipped_existing:,}",
            f"Batches Processed:      {self.batches_processed:,}",
            "=" * 70,
        ]
        if self.error_details:
            lines.append("Errors / Warnings Encountered:")
            for err in self.error_details[:10]:
                lines.append(f"  - {err}")
            if len(self.error_details) > 10:
                lines.append(f"  ... and {len(self.error_details) - 10} more errors.")
            lines.append("=" * 70)
        return "\n".join(lines)


def generate_source_event_id(
    file_sha256: str,
    row_ordinal: int,
    patient_id: str,
) -> str:
    """
    Generate a deterministic, stable source-event identifier.
    Format: kaggle_<sha12>_row_<ordinal>_<patient>
    Guarantees unique provenance per source file row while supporting idempotent deduplication.
    """
    short_hash = file_sha256[:12]
    return f"kaggle_{short_hash}_row_{row_ordinal:05d}_{patient_id}"


def generate_event_uuid(source_event_id: str) -> str:
    """Generate a deterministic UUID v5 from the source-event identifier."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:smarthealth:event:{source_event_id}"))


def ensure_patient_identities(
    session: Session,
    patient_ids: Set[str],
    auto_seed: bool = True,
) -> Set[str]:
    """
    Verify existing patient profiles in the database.
    If auto_seed is True, automatically provisions baseline User and PatientProfile records
    for missing patient identifiers.
    Returns the set of valid patient_ids present in the database.
    """
    repo = PatientRepository(session)
    existing_ids = repo.get_existing_patient_ids(list(patient_ids))

    missing_ids = patient_ids - existing_ids
    if not missing_ids or not auto_seed:
        return existing_ids

    logger.info("Auto-provisioning %d baseline patient profiles: %s", len(missing_ids), missing_ids)
    for pid in sorted(missing_ids):
        user_id = f"usr_kaggle_{pid.lower()}"
        email = f"{pid.lower()}@smarthealth.local"
        
        # Ensure user does not already exist
        user = session.get(User, user_id)
        if not user:
            user = User(
                user_id=user_id,
                email=email,
                # Insecure dev hash placeholder for imported non-login patient stubs
                password_hash="$2b$12$e8q4M3Y8tBqVbE1.KagdEuqg8vL51eN0qg8vL51eN0qg8vL51eN0q",
                role="patient",
                is_active=True,
            )
            session.add(user)
            session.flush()

        profile = PatientProfile(
            patient_id=pid,
            user_id=user_id,
            first_name="Kaggle",
            last_name=f"Patient {pid}",
            gender="unknown",
        )
        session.add(profile)
        existing_ids.add(pid)

    session.flush()
    return existing_ids


class KaggleDatasetImporter:
    """Coordinates validation, patient identity mapping, batching, and transactional persistence."""

    def __init__(
        self,
        session: Session,
        batch_size: int = 250,
        auto_seed_patients: bool = True,
        source_timezone: str = "UTC",
    ) -> None:
        self.session = session
        self.batch_size = max(1, batch_size)
        self.auto_seed_patients = auto_seed_patients
        self.source_timezone = source_timezone

    def run_import(
        self,
        csv_path: str | Path,
        dry_run: bool = False,
    ) -> ImportReport:
        """
        Execute CSV validation and transactional database ingestion.
        If dry_run is True, validates data and checks existing records without database writes.
        """
        path = Path(csv_path).resolve()
        logger.info("Starting Kaggle ingestion pipeline for '%s' (dry_run=%s)", path.name, dry_run)

        # 1. Validation
        validation: DatasetValidationResult = validate_kaggle_csv(
            path,
            source_timezone=self.source_timezone,
        )

        report = ImportReport(
            source_file=str(path),
            file_sha256=validation.file_sha256,
            dry_run=dry_run,
            total_rows_inspected=validation.total_rows_inspected,
            valid_records=validation.valid_count,
            invalid_records=validation.error_count,
        )

        for err in validation.errors:
            report.error_details.append(
                f"Row {err.row_number}: [{err.field}] {err.message} (value='{err.value}')"
            )

        if not validation.is_valid:
            report.status = "failed"
            report.completed_at = datetime.now(timezone.utc)
            logger.error("Dataset validation failed with %d errors. Ingestion aborted.", len(validation.errors))
            return report

        # 2. Patient Identity Resolution
        try:
            if dry_run and self.auto_seed_patients:
                # In dry-run mode with auto_seed enabled, assume baseline profiles will be provisioned
                valid_patient_ids = validation.distinct_patient_ids
            else:
                valid_patient_ids = ensure_patient_identities(
                    self.session,
                    validation.distinct_patient_ids,
                    auto_seed=self.auto_seed_patients and not dry_run,
                )
        except Exception as exc:
            report.status = "failed"
            report.error_details.append(f"Failed resolving patient identities: {exc}")
            report.completed_at = datetime.now(timezone.utc)
            return report

        # Filter records by patient mapping
        importable_records: List[ParsedKaggleRow] = []
        for r in validation.valid_records:
            if r.patient_id in valid_patient_ids:
                importable_records.append(r)
            else:
                report.unmapped_patient_records += 1
                report.error_details.append(
                    f"Row {r.row_ordinal}: Unmapped patient '{r.patient_id}' not found in patient_profiles."
                )

        if dry_run:
            self._execute_dry_run_checks(importable_records, validation.file_sha256, report)
            report.status = "dry_run_success"
            report.completed_at = datetime.now(timezone.utc)
            return report

        # 3. Transactional Ingestion
        try:
            self._execute_persistence(path, importable_records, validation.file_sha256, report)
            report.status = "completed"
        except Exception as exc:
            self.session.rollback()
            report.status = "failed"
            report.error_details.append(f"Transactional ingestion failed: {exc}")
            logger.exception("Ingestion failed with exception: %s", exc)
        finally:
            report.completed_at = datetime.now(timezone.utc)

        return report

    def _execute_dry_run_checks(
        self,
        records: List[ParsedKaggleRow],
        file_sha256: str,
        report: ImportReport,
    ) -> None:
        """Inspect existing database records to predict insertion vs skip counts."""
        source_event_ids = [
            generate_source_event_id(file_sha256, r.row_ordinal, r.patient_id)
            for r in records
        ]

        vitals_repo = VitalsRepository(self.session)
        existing_set = vitals_repo.get_existing_source_event_ids("kaggle_csv", source_event_ids)

        new_count = len(records) - len(existing_set)
        report.events_inserted = new_count
        report.readings_inserted = new_count * 3
        report.events_skipped_existing = len(existing_set)
        report.batches_processed = (len(records) + self.batch_size - 1) // self.batch_size

    def _execute_persistence(
        self,
        path: Path,
        records: List[ParsedKaggleRow],
        file_sha256: str,
        report: ImportReport,
    ) -> None:
        """Persist batches transactionally into import_batches, ingestion_events, and vitals_readings."""
        now = datetime.now(timezone.utc)
        batch_id = f"batch_{file_sha256[:12]}_{int(now.timestamp())}_{uuid.uuid4().hex[:6]}"

        # Initialize import_batches record
        import_batch = ImportBatch(
            batch_id=batch_id,
            source_name="kaggle_csv",
            filename=path.name,
            file_sha256=file_sha256,
            row_count=len(records),
            status="pending",
            started_at=now,
        )
        self.session.add(import_batch)
        self.session.flush()

        vitals_repo = VitalsRepository(self.session)

        # Process in batches
        for i in range(0, len(records), self.batch_size):
            batch_slice = records[i : i + self.batch_size]
            report.batches_processed += 1

            # Check existing source_event_ids for idempotency
            id_mapping = {
                generate_source_event_id(file_sha256, r.row_ordinal, r.patient_id): r
                for r in batch_slice
            }
            existing_ids = vitals_repo.get_existing_source_event_ids("kaggle_csv", list(id_mapping.keys()))

            # Filter to new records only
            new_records = [r for src_id, r in id_mapping.items() if src_id not in existing_ids]
            report.events_skipped_existing += len(existing_ids)

            for r in new_records:
                src_event_id = generate_source_event_id(file_sha256, r.row_ordinal, r.patient_id)
                evt_uuid = generate_event_uuid(src_event_id)

                event = IngestionEvent(
                    event_id=evt_uuid,
                    patient_id=r.patient_id,
                    source="kaggle_csv",
                    source_event_id=src_event_id,
                    batch_id=batch_id,
                    measured_at=r.measured_at,
                    received_at=now,
                    is_simulated=False,
                    mirror_status="pending",
                    created_at=now,
                )
                vitals_repo.create_event(event)

                # Expand 3 vitals readings per event
                readings = [
                    VitalsReading(
                        event_id=evt_uuid,
                        patient_id=r.patient_id,
                        metric_code="heart_rate",
                        value=r.heart_rate,
                        unit="bpm",
                        raw_value=r.heart_rate,
                        raw_unit="bpm",
                        quality_status="valid",
                        measured_at=r.measured_at,
                        created_at=now,
                    ),
                    VitalsReading(
                        event_id=evt_uuid,
                        patient_id=r.patient_id,
                        metric_code="spo2",
                        value=r.spo2,
                        unit="%",
                        raw_value=r.spo2,
                        raw_unit="%",
                        quality_status="valid",
                        measured_at=r.measured_at,
                        created_at=now,
                    ),
                    VitalsReading(
                        event_id=evt_uuid,
                        patient_id=r.patient_id,
                        metric_code="temperature",
                        value=r.temperature_c,
                        unit="degC",
                        raw_value=r.temperature_f,
                        raw_unit="degF",
                        quality_status="valid",
                        measured_at=r.measured_at,
                        created_at=now,
                    ),
                ]
                vitals_repo.add_readings(readings)

                report.events_inserted += 1
                report.readings_inserted += 3

            # Commit batch transaction
            self.session.commit()

        # Update batch completion status
        import_batch.status = "completed"
        import_batch.completed_at = datetime.now(timezone.utc)
        import_batch.metadata_json = json.dumps(report.to_dict())
        self.session.commit()
