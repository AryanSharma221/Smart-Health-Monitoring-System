"""
Smartwatch Sensor Simulator Telemetry Ingestion Service.

Processes synthetic telemetry observations from the standalone simulator service:
1. Validates schema boundaries, types, and physiological limits.
2. Enforces synthetic provenance: rejects historical Kaggle masquerading or missing flags.
3. Enforces idempotency via MySQL unique constraints on (source, source_event_id).
4. Verifies patient identity against authoritative patient_profiles table.
5. Persists canonical IngestionEvent and normalized VitalsReading rows.
6. Evaluates readings via ML Isolation Forest anomaly detection and clinical alert rules.
7. Stages and syncs documents to MongoDB Atlas analytics mirror via transactional outbox.
8. Emits real-time WebSocket notifications to subscribed clinicians.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import logging
import math
from typing import Any, Dict, Optional, Tuple

from pymongo.database import Database
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.mysql.models import IngestionEvent, VitalsReading
from database.mysql.repositories.patient_repository import PatientRepository
from database.mysql.repositories.vitals_repository import VitalsRepository
from services.ml_service import MLService
from services.sync.outbox_service import OutboxSyncService
from services.websocket.dispatcher import notify_reading_created

logger = logging.getLogger(__name__)


class IngestionOutcome(str, Enum):
    """Result outcome categories for telemetry event ingestion."""
    ACCEPTED = "accepted"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    UNKNOWN_PATIENT_REJECTED = "unknown_patient_rejected"
    MALFORMED_REJECTED = "malformed_rejected"
    NOT_SIMULATED_REJECTED = "not_simulated_rejected"
    UNSUPPORTED_UNITS_REJECTED = "unsupported_units_rejected"
    UNTRUSTED_PROVENANCE_REJECTED = "untrusted_provenance_rejected"
    FAILED = "failed"


class IngestionResult:
    """Detailed summary of the ingestion attempt for a single reading."""

    def __init__(
        self,
        outcome: IngestionOutcome,
        event_id: str,
        patient_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        self.outcome = outcome
        self.event_id = event_id
        self.patient_id = patient_id
        self.detail = detail

    @property
    def is_success(self) -> bool:
        """True if the reading was either newly accepted or safely deduplicated."""
        return self.outcome in (IngestionOutcome.ACCEPTED, IngestionOutcome.DUPLICATE_SKIPPED)

    def __repr__(self) -> str:
        return (
            f"<IngestionResult outcome='{self.outcome.value}' event_id='{self.event_id}' "
            f"patient='{self.patient_id}' detail='{self.detail}'>"
        )


class SimulatorIngestionService:
    """Domain service orchestrating validation, relational persistence, ML, and mirror sync."""

    # Physiological plausibility boundaries for wearable telemetry
    HR_MIN, HR_MAX = 20.0, 300.0
    SPO2_MIN, SPO2_MAX = 50.0, 100.0
    TEMP_F_MIN, TEMP_F_MAX = 70.0, 120.0

    MAX_PAYLOAD_KEYS = 30
    MAX_EVENT_ID_LENGTH = 128
    MAX_PATIENT_ID_LENGTH = 32
    ALLOWED_SOURCES = {"smartwatch_simulator", "demo-simulator", "wearable_simulator"}
    ALLOWED_HR_UNITS = {"bpm", "BPM", ""}
    ALLOWED_SPO2_UNITS = {"%", "percent", ""}
    ALLOWED_TEMP_UNITS = {"degF", "degC", "°F", "°C", "F", "C", "Fahrenheit", "Celsius", ""}

    def __init__(self) -> None:
        self.last_ingested_event_id: Optional[str] = None
        self.last_successful_db_sync_timestamp: Optional[str] = None

    @classmethod
    def validate_reading(
        cls,
        reading: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validate incoming raw telemetry dict from the simulator.
        
        Returns:
            (is_valid, error_reason, cleaned_data)
        """
        if not isinstance(reading, dict):
            return False, "Payload must be a JSON object", None

        if len(reading) > cls.MAX_PAYLOAD_KEYS:
            return False, f"Payload contains {len(reading)} keys exceeding maximum limit of {cls.MAX_PAYLOAD_KEYS}", None

        event_id = reading.get("event_id")
        if not event_id or not isinstance(event_id, str) or not event_id.strip():
            return False, "Missing or invalid 'event_id'", None

        event_id = event_id.strip()
        if len(event_id) > cls.MAX_EVENT_ID_LENGTH:
            return False, f"Event ID length {len(event_id)} exceeds maximum of {cls.MAX_EVENT_ID_LENGTH}", None

        patient_id = reading.get("patient_id")
        if not patient_id or not isinstance(patient_id, str) or not patient_id.strip():
            return False, "Missing or invalid 'patient_id'", None

        patient_id = patient_id.strip()
        if len(patient_id) > cls.MAX_PATIENT_ID_LENGTH:
            return False, f"Patient ID length {len(patient_id)} exceeds maximum of {cls.MAX_PATIENT_ID_LENGTH}", None

        # Mandatory synthetic provenance check
        is_simulated = reading.get("is_simulated")
        if is_simulated is not True:
            return False, "Payload must have 'is_simulated': True", None

        # Verify source provenance cannot masquerade as historical Kaggle dataset
        raw_source = reading.get("source")
        if raw_source is not None:
            source_str = str(raw_source).strip()
            if source_str and source_str not in cls.ALLOWED_SOURCES:
                return (
                    False,
                    f"Untrusted provenance source '{source_str}'. Allowed simulator sources: {sorted(list(cls.ALLOWED_SOURCES))}",
                    None,
                )

        # Validate units if provided
        hr_unit = reading.get("hr_unit") or reading.get("heart_rate_unit") or reading.get("unit_hr")
        if hr_unit is not None and str(hr_unit).strip() not in cls.ALLOWED_HR_UNITS:
            return False, f"Unsupported heart rate unit '{hr_unit}'. Allowed units: bpm", None

        spo2_unit = reading.get("spo2_unit") or reading.get("unit_spo2")
        if spo2_unit is not None and str(spo2_unit).strip() not in cls.ALLOWED_SPO2_UNITS:
            return False, f"Unsupported SpO2 unit '{spo2_unit}'. Allowed units: %", None

        temp_unit = reading.get("temp_unit") or reading.get("temperature_unit") or reading.get("unit_temp")
        if temp_unit is not None and str(temp_unit).strip() not in cls.ALLOWED_TEMP_UNITS:
            return False, f"Unsupported temperature unit '{temp_unit}'. Allowed units: degF, degC, °F, °C", None

        # Validate physiological metrics
        try:
            hr = float(reading["heart_rate"])
            spo2 = float(reading["spo2"])
            temp_f = float(reading["temperature_f"])
        except (KeyError, TypeError, ValueError) as exc:
            return False, f"Missing or non-numeric vital measurements: {exc}", None

        if math.isnan(hr) or math.isinf(hr):
            return False, f"Heart rate cannot be NaN or Infinite: {hr}", None
        if math.isnan(spo2) or math.isinf(spo2):
            return False, f"SpO2 cannot be NaN or Infinite: {spo2}", None
        if math.isnan(temp_f) or math.isinf(temp_f):
            return False, f"Temperature cannot be NaN or Infinite: {temp_f}", None

        if not (cls.HR_MIN <= hr <= cls.HR_MAX):
            return False, f"Heart rate {hr} outside plausible boundary [{cls.HR_MIN}, {cls.HR_MAX}]", None

        if not (cls.SPO2_MIN <= spo2 <= cls.SPO2_MAX):
            return False, f"SpO2 {spo2} outside plausible boundary [{cls.SPO2_MIN}, {cls.SPO2_MAX}]", None

        if not (cls.TEMP_F_MIN <= temp_f <= cls.TEMP_F_MAX):
            return False, f"Temperature {temp_f}°F outside plausible boundary [{cls.TEMP_F_MIN}, {cls.TEMP_F_MAX}]", None

        # Parse observation timestamp
        raw_ts = reading.get("measured_at") or reading.get("timestamp")
        if not raw_ts:
            return False, "Missing 'measured_at' or 'timestamp' field", None

        try:
            if isinstance(raw_ts, datetime):
                measured_at = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=timezone.utc)
            else:
                ts_str = str(raw_ts).replace("Z", "+00:00")
                measured_at = datetime.fromisoformat(ts_str)
                if measured_at.tzinfo is None:
                    measured_at = measured_at.replace(tzinfo=timezone.utc)
        except Exception as exc:
            return False, f"Invalid ISO 8601 timestamp '{raw_ts}': {exc}", None

        if not (2000 <= measured_at.year <= 2100):
            return False, f"Observation timestamp year {measured_at.year} outside valid range [2000, 2100]", None

        # Exact Celsius calculation
        temp_c = reading.get("temperature_c")
        if temp_c is None:
            temp_c = round((temp_f - 32.0) * (5.0 / 9.0), 2)
        else:
            try:
                temp_c = float(temp_c)
                if math.isnan(temp_c) or math.isinf(temp_c):
                    temp_c = round((temp_f - 32.0) * (5.0 / 9.0), 2)
            except (TypeError, ValueError):
                temp_c = round((temp_f - 32.0) * (5.0 / 9.0), 2)

        cleaned: Dict[str, Any] = {
            "event_id": event_id,
            "patient_id": patient_id,
            "source": "smartwatch_simulator",
            "measured_at": measured_at,
            "heart_rate": round(hr, 2),
            "spo2": round(spo2, 2),
            "temperature_f": round(temp_f, 2),
            "temperature_c": round(temp_c, 2),
            "is_simulated": True,
            "scenario": str(reading.get("scenario") or "normal"),
        }
        return True, None, cleaned

    def ingest_single_reading(
        self,
        db: Session,
        reading: Dict[str, Any],
        mongo_db: Optional[Database] = None,
        ml_service: Optional[MLService] = None,
    ) -> IngestionResult:
        """
        Validate, persist, and process a single synthetic telemetry observation.
        Guarantees idempotency and safe error isolation.
        """
        # 1. Schema and range validation
        is_valid, err_msg, cleaned = self.validate_reading(reading)
        if not is_valid or cleaned is None:
            event_id = str(reading.get("event_id") or "unknown_event")
            patient_id = str(reading.get("patient_id") or "unknown_patient")
            outcome = IngestionOutcome.MALFORMED_REJECTED
            if "is_simulated" in (err_msg or ""):
                outcome = IngestionOutcome.NOT_SIMULATED_REJECTED
            elif "Untrusted provenance" in (err_msg or ""):
                outcome = IngestionOutcome.UNTRUSTED_PROVENANCE_REJECTED
            elif "Unsupported" in (err_msg or "") and "unit" in (err_msg or ""):
                outcome = IngestionOutcome.UNSUPPORTED_UNITS_REJECTED

            logger.warning("Rejected invalid simulator reading %s: %s", event_id, err_msg)
            return IngestionResult(
                outcome=outcome,
                event_id=event_id,
                patient_id=patient_id,
                detail=err_msg,
            )

        event_id = cleaned["event_id"]
        patient_id = cleaned["patient_id"]
        source = cleaned["source"]

        # 2. Verify patient existence in relational database
        patient_repo = PatientRepository(db)
        patient = patient_repo.get_by_id(patient_id)
        if not patient:
            logger.warning("Rejecting reading %s: Patient '%s' not found in MySQL.", event_id, patient_id)
            return IngestionResult(
                outcome=IngestionOutcome.UNKNOWN_PATIENT_REJECTED,
                event_id=event_id,
                patient_id=patient_id,
                detail=f"Patient '{patient_id}' does not exist in authoritative patient_profiles table.",
            )

        # 3. Idempotency check: query existing source_event_id
        vitals_repo = VitalsRepository(db)
        existing_ids = vitals_repo.get_existing_source_event_ids(source, [event_id])
        if event_id in existing_ids:
            logger.debug("Idempotent deduplication: Event %s already persisted. Skipping.", event_id)
            return IngestionResult(
                outcome=IngestionOutcome.DUPLICATE_SKIPPED,
                event_id=event_id,
                patient_id=patient_id,
                detail="Event already persisted in ingestion_events table.",
            )

        # 4. Atomic Relational Persistence
        now_utc = datetime.now(timezone.utc)
        event = IngestionEvent(
            event_id=event_id,
            patient_id=patient_id,
            source=source,
            source_event_id=event_id,
            batch_id=None,
            measured_at=cleaned["measured_at"],
            received_at=now_utc,
            is_simulated=True,
            mirror_status="pending",
            created_at=now_utc,
        )

        readings = [
            VitalsReading(
                event_id=event_id,
                patient_id=patient_id,
                metric_code="heart_rate",
                value=Decimal(str(cleaned["heart_rate"])),
                unit="bpm",
                raw_value=Decimal(str(cleaned["heart_rate"])),
                raw_unit="bpm",
                quality_status="valid",
                measured_at=cleaned["measured_at"],
                created_at=now_utc,
            ),
            VitalsReading(
                event_id=event_id,
                patient_id=patient_id,
                metric_code="spo2",
                value=Decimal(str(cleaned["spo2"])),
                unit="%",
                raw_value=Decimal(str(cleaned["spo2"])),
                raw_unit="%",
                quality_status="valid",
                measured_at=cleaned["measured_at"],
                created_at=now_utc,
            ),
            VitalsReading(
                event_id=event_id,
                patient_id=patient_id,
                metric_code="temperature",
                value=Decimal(str(cleaned["temperature_c"])),
                unit="degC",
                raw_value=Decimal(str(cleaned["temperature_f"])),
                raw_unit="degF",
                quality_status="valid",
                measured_at=cleaned["measured_at"],
                created_at=now_utc,
            ),
        ]

        try:
            vitals_repo.create_event(event)
            vitals_repo.add_readings(readings)

            # 5. Outbox Staging & Immediate MongoDB Atlas Mirroring (Gated by mongodb_sync_enabled)
            outbox_service = None
            sync_enabled = False
            try:
                from services.api.config import get_settings
                settings = get_settings()
                sync_enabled = settings.mongodb_sync_enabled and (mongo_db is not None)
                active_mongo = mongo_db if sync_enabled else None
                outbox_service = OutboxSyncService(db, active_mongo, sync_enabled=sync_enabled)
                outbox_service.sync_telemetry_immediate(event)
            except Exception as sync_exc:
                logger.warning("MongoDB outbox synchronization failed (non-fatal): %s", sync_exc)

            # 5b. Clinical Rule Evaluation Engine (Deterministic Vital Thresholds)
            try:
                from services.alerts.evaluator import AlertEvaluator
                alert_evaluator = AlertEvaluator(db)
                rule_alerts = alert_evaluator.evaluate_readings_batch(event=event, readings=readings)
                if sync_enabled and outbox_service is not None and rule_alerts:
                    for ra in rule_alerts:
                        outbox_service.sync_alert_immediate(ra)
            except Exception as alert_exc:
                logger.warning("Clinical alert evaluation failed for event %s (non-fatal): %s", event_id, alert_exc)

            # 6. ML Anomaly Detection & Clinical Alert Evaluation
            if ml_service is not None:
                try:
                    assessment_out = ml_service.assess_and_persist(
                        db=db,
                        patient_id=patient_id,
                        timestamp=cleaned["measured_at"],
                        heart_rate=cleaned["heart_rate"],
                        spo2=cleaned["spo2"],
                        temperature_f=cleaned["temperature_f"],
                        source_event_id=event_id,
                        is_simulated=True,
                        trigger_alert=True,
                    )
                    if sync_enabled and outbox_service is not None and assessment_out and len(assessment_out) > 1 and assessment_out[1]:
                        outbox_service.sync_alert_immediate(assessment_out[1])
                except Exception as ml_exc:
                    logger.warning("ML assessment failed for event %s (non-fatal): %s", event_id, ml_exc)

            # 7. Commit authoritative database transaction
            db.commit()
            self.last_ingested_event_id = event_id
            self.last_successful_db_sync_timestamp = datetime.now(timezone.utc).isoformat()

            # 8. Real-Time WebSocket broadcast (after successful commit)
            try:
                notify_reading_created(event)
            except Exception as ws_exc:
                logger.debug("Live WebSocket dispatch skipped/failed: %s", ws_exc)

            logger.info("Successfully ingested simulator reading: event_id=%s patient=%s", event_id, patient_id)
            return IngestionResult(
                outcome=IngestionOutcome.ACCEPTED,
                event_id=event_id,
                patient_id=patient_id,
                detail="Successfully persisted to MySQL and queued for analytics mirror.",
            )

        except IntegrityError as ie:
            db.rollback()
            logger.info("Concurrent duplicate insertion for event %s: %s. Handled idempotently.", event_id, ie)
            return IngestionResult(
                outcome=IngestionOutcome.DUPLICATE_SKIPPED,
                event_id=event_id,
                patient_id=patient_id,
                detail="Duplicate record caught by database unique constraint.",
            )
        except Exception as exc:
            db.rollback()
            logger.error("Failed to ingest simulator event %s: %s", event_id, exc, exc_info=True)
            return IngestionResult(
                outcome=IngestionOutcome.FAILED,
                event_id=event_id,
                patient_id=patient_id,
                detail=str(exc),
            )
