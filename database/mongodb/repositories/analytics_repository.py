"""
MongoDB Analytics Repository for Healthcare Telemetry & Alerts.

Provides high-level analytical queries against MongoDB Atlas analytics mirror:
- Dataset overview and provenance breakdowns.
- Patient-level vital statistics (HR, SpO2, Temp).
- Chronological time-bucket trends (hourly/daily).
- Bounded patient telemetry history.
- Clinical alert distribution and triage summaries.
- Telemetry data-quality diagnostics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo.database import Database
from pymongo.errors import PyMongoError

from database.mongodb.analytics.normalizers import (
    normalize_alert_summary,
    normalize_data_quality,
    normalize_dataset_overview,
    normalize_patient_vitals_summary,
    normalize_source_provenance,
    normalize_time_buckets,
)
from database.mongodb.analytics.pipelines import (
    build_alert_summary_pipeline,
    build_data_quality_pipeline,
    build_dataset_overview_pipeline,
    build_duplicate_source_identities_pipeline,
    build_patient_history_pipeline,
    build_patient_vitals_summary_pipeline,
    build_source_provenance_pipeline,
    build_time_bucketed_vitals_pipeline,
)
from database.mongodb.analytics.validators import (
    validate_bucket_interval,
    validate_pagination,
    validate_patient_id,
    validate_time_range,
)
from database.mongodb.collections import ALERTS_COLLECTION, TELEMETRY_COLLECTION

logger = logging.getLogger(__name__)


class MongoAnalyticsRepository:
    """Encapsulates aggregation pipeline executions for analytics and reporting."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.telemetry_col = db[TELEMETRY_COLLECTION]
        self.alert_col = db[ALERTS_COLLECTION]

    def get_dataset_overview(self) -> Dict[str, Any]:
        """
        Execute dataset overview aggregation:
        Returns document counts, distinct patients, time boundaries, and source breakdown.
        """
        pipeline = build_dataset_overview_pipeline()
        try:
            raw_res = list(self.telemetry_col.aggregate(pipeline))
            return normalize_dataset_overview(raw_res)
        except PyMongoError as exc:
            logger.error("Failed to execute get_dataset_overview aggregation: %s", exc)
            raise

    def get_patient_vitals_summary(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Compute vital measurement statistics (valid_count, min, max, avg) per patient.
        Guarantees non-numeric/null values are excluded from averages rather than coerced to zero.
        """
        clean_patient_id = validate_patient_id(patient_id) if patient_id else None
        norm_start, norm_end = validate_time_range(start_time, end_time)

        pipeline = build_patient_vitals_summary_pipeline(
            patient_id=clean_patient_id,
            start_time=norm_start,
            end_time=norm_end,
        )
        try:
            raw_res = list(self.telemetry_col.aggregate(pipeline))
            return normalize_patient_vitals_summary(raw_res)
        except PyMongoError as exc:
            logger.error("Failed to execute get_patient_vitals_summary aggregation: %s", exc)
            raise

    def get_time_bucketed_vitals(
        self,
        patient_id: Optional[str] = None,
        interval: str = "hour",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate chronological vital signs into time buckets ('hour' or 'day').
        """
        clean_patient_id = validate_patient_id(patient_id) if patient_id else None
        clean_interval = validate_bucket_interval(interval)
        norm_start, norm_end = validate_time_range(start_time, end_time)

        pipeline = build_time_bucketed_vitals_pipeline(
            patient_id=clean_patient_id,
            interval=clean_interval,
            start_time=norm_start,
            end_time=norm_end,
        )
        try:
            raw_res = list(self.telemetry_col.aggregate(pipeline))
            return normalize_time_buckets(raw_res)
        except PyMongoError as exc:
            logger.error("Failed to execute get_time_bucketed_vitals aggregation: %s", exc)
            raise

    def get_patient_telemetry_history(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve chronological bounded telemetry records for a single patient.
        Uses compound index (patient_id, measured_at DESC).
        """
        clean_patient_id = validate_patient_id(patient_id)
        norm_start, norm_end = validate_time_range(start_time, end_time)
        bounded_limit, safe_offset = validate_pagination(limit=limit, offset=offset)

        pipeline = build_patient_history_pipeline(
            patient_id=clean_patient_id,
            start_time=norm_start,
            end_time=norm_end,
            limit=bounded_limit,
            offset=safe_offset,
        )
        try:
            return list(self.telemetry_col.aggregate(pipeline))
        except PyMongoError as exc:
            logger.error("Failed to execute get_patient_telemetry_history aggregation: %s", exc)
            raise

    def get_source_provenance_summary(self) -> Dict[str, Any]:
        """
        Calculate telemetry distribution by origin source and simulation status.
        """
        pipeline = build_source_provenance_pipeline()
        try:
            raw_res = list(self.telemetry_col.aggregate(pipeline))
            return normalize_source_provenance(raw_res)
        except PyMongoError as exc:
            logger.error("Failed to execute get_source_provenance_summary aggregation: %s", exc)
            raise

    def get_alert_summary(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate clinical alerts by severity, lifecycle status, patient, and acknowledgement metrics.
        """
        clean_patient_id = validate_patient_id(patient_id) if patient_id else None
        norm_start, norm_end = validate_time_range(start_time, end_time)

        pipeline = build_alert_summary_pipeline(
            patient_id=clean_patient_id,
            start_time=norm_start,
            end_time=norm_end,
        )
        try:
            raw_res = list(self.alert_col.aggregate(pipeline))
            return normalize_alert_summary(raw_res)
        except PyMongoError as exc:
            logger.error("Failed to execute get_alert_summary aggregation: %s", exc)
            raise

    def get_data_quality_report(self) -> Dict[str, Any]:
        """
        Execute comprehensive telemetry data-quality audit diagnostics:
        Checks missing fields, null metrics, invalid types, implausible values, and duplicate source IDs.
        """
        quality_pipeline = build_data_quality_pipeline()
        duplicate_pipeline = build_duplicate_source_identities_pipeline()
        try:
            raw_quality = list(self.telemetry_col.aggregate(quality_pipeline))
            raw_dups = list(self.telemetry_col.aggregate(duplicate_pipeline))
            
            dup_count = 0
            if raw_dups and "duplicate_source_identities" in raw_dups[0]:
                dup_count = raw_dups[0]["duplicate_source_identities"]
            
            return normalize_data_quality(raw_quality, duplicate_source_count=dup_count)
        except PyMongoError as exc:
            logger.error("Failed to execute get_data_quality_report aggregation: %s", exc)
            raise
