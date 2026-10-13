"""
SQL Relational Analytics Repository for Health Telemetry and Clinical Alerts.

Provides relational analytics parity with MongoDB analytics workloads:
- Dataset overview and population statistics.
- Patient-level vital sign statistics (HR, SpO2, Temperature °F).
- Chronological time-bucket aggregates (hourly and daily).
- Bounded patient telemetry history with deterministic sorting.
- Source provenance and simulation distribution.
- Clinical alert triage and status distribution.
- Telemetry data-quality diagnostics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Integer, case, desc, distinct, func, select, text
from sqlalchemy.orm import Session

from database.mongodb.analytics.validators import (
    normalize_datetime,
    validate_bucket_interval,
    validate_pagination,
    validate_patient_id,
    validate_time_range,
)
from database.mysql.models import Alert, IngestionEvent, VitalsReading

logger = logging.getLogger(__name__)


def _round_optional(val: Optional[float], decimals: int = 2) -> Optional[float]:
    """Safely round float value to given decimal places."""
    if val is None:
        return None
    return round(float(val), decimals)


class SqlAnalyticsRepository:
    """Encapsulates relational SQL analytical queries matching MongoDB analytics parity."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_dataset_overview(self) -> Dict[str, Any]:
        """
        Execute dataset overview query across ingestion_events table.
        Returns document counts, distinct patients, time boundaries, and source breakdown.
        """
        # 1. Summary aggregations
        stmt_summary = select(
            func.count(IngestionEvent.event_id).label("total_documents"),
            func.min(IngestionEvent.measured_at).label("earliest_measured_at"),
            func.max(IngestionEvent.measured_at).label("latest_measured_at"),
            func.sum(case((IngestionEvent.is_simulated.is_(True), 1), else_=0)).label("simulated_count"),
            func.sum(case((IngestionEvent.is_simulated.is_(False), 1), else_=0)).label("non_simulated_count"),
        )
        row = self.session.execute(stmt_summary).mappings().first()
        total_docs = row["total_documents"] if row else 0

        # 2. Distinct patient IDs
        stmt_patients = (
            select(distinct(IngestionEvent.patient_id))
            .order_by(IngestionEvent.patient_id)
        )
        patient_ids = list(self.session.scalars(stmt_patients).all())

        # 3. Documents by source
        stmt_sources = (
            select(IngestionEvent.source, func.count(IngestionEvent.event_id).label("cnt"))
            .group_by(IngestionEvent.source)
            .order_by(desc("cnt"), IngestionEvent.source)
        )
        source_counts = {
            r[0]: r[1] for r in self.session.execute(stmt_sources).all()
        }

        return {
            "total_documents": total_docs or 0,
            "distinct_patients_count": len(patient_ids),
            "distinct_patient_ids": patient_ids,
            "documents_by_source": source_counts,
            "documents_by_simulation": {
                "simulated": int(row["simulated_count"] or 0) if row else 0,
                "non_simulated": int(row["non_simulated_count"] or 0) if row else 0,
            },
            "earliest_measured_at": normalize_datetime(row["earliest_measured_at"]) if row else None,
            "latest_measured_at": normalize_datetime(row["latest_measured_at"]) if row else None,
            "provenance_note": "Authoritative relational records from MySQL ingestion_events table.",
        }

    def get_patient_vitals_summary(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Compute vital measurement statistics (valid_count, min, max, avg) per patient from vitals_readings.
        Uses Fahrenheit raw_value for temperature to maintain exact parity with MongoDB metrics.
        """
        clean_patient_id = validate_patient_id(patient_id) if patient_id else None
        norm_start, norm_end = validate_time_range(start_time, end_time)

        # Temperature in Fahrenheit expression: raw_value if raw_unit == 'degF' else (value * 9/5 + 32)
        temp_f_expr = case(
            (VitalsReading.raw_unit == "degF", VitalsReading.raw_value),
            else_=func.round(VitalsReading.value * 9.0 / 5.0 + 32.0, 2),
        )

        filters = []
        if clean_patient_id:
            filters.append(VitalsReading.patient_id == clean_patient_id)
        if norm_start:
            filters.append(VitalsReading.measured_at >= norm_start)
        if norm_end:
            filters.append(VitalsReading.measured_at <= norm_end)

        stmt = (
            select(
                VitalsReading.patient_id,
                func.count(distinct(VitalsReading.event_id)).label("total_observations"),
                # Heart Rate
                func.count(case((VitalsReading.metric_code == "heart_rate", VitalsReading.value))).label("hr_count"),
                func.min(case((VitalsReading.metric_code == "heart_rate", VitalsReading.value))).label("hr_min"),
                func.max(case((VitalsReading.metric_code == "heart_rate", VitalsReading.value))).label("hr_max"),
                func.avg(case((VitalsReading.metric_code == "heart_rate", VitalsReading.value))).label("hr_avg"),
                # SpO2
                func.count(case((VitalsReading.metric_code == "spo2", VitalsReading.value))).label("spo2_count"),
                func.min(case((VitalsReading.metric_code == "spo2", VitalsReading.value))).label("spo2_min"),
                func.max(case((VitalsReading.metric_code == "spo2", VitalsReading.value))).label("spo2_max"),
                func.avg(case((VitalsReading.metric_code == "spo2", VitalsReading.value))).label("spo2_avg"),
                # Temperature (Fahrenheit)
                func.count(case((VitalsReading.metric_code == "temperature", VitalsReading.value))).label("temp_count"),
                func.min(case((VitalsReading.metric_code == "temperature", temp_f_expr))).label("temp_min"),
                func.max(case((VitalsReading.metric_code == "temperature", temp_f_expr))).label("temp_max"),
                func.avg(case((VitalsReading.metric_code == "temperature", temp_f_expr))).label("temp_avg"),
            )
            .where(*filters)
            .group_by(VitalsReading.patient_id)
            .order_by(VitalsReading.patient_id)
        )

        rows = self.session.execute(stmt).mappings().all()
        results: List[Dict[str, Any]] = []

        for r in rows:
            hr_cnt = r["hr_count"] or 0
            spo2_cnt = r["spo2_count"] or 0
            temp_cnt = r["temp_count"] or 0

            results.append({
                "patient_id": r["patient_id"],
                "total_observations": r["total_observations"] or 0,
                "heart_rate": {
                    "valid_count": hr_cnt,
                    "min": _round_optional(r["hr_min"]) if hr_cnt > 0 else None,
                    "max": _round_optional(r["hr_max"]) if hr_cnt > 0 else None,
                    "avg": _round_optional(r["hr_avg"]) if hr_cnt > 0 else None,
                },
                "spo2": {
                    "valid_count": spo2_cnt,
                    "min": _round_optional(r["spo2_min"]) if spo2_cnt > 0 else None,
                    "max": _round_optional(r["spo2_max"]) if spo2_cnt > 0 else None,
                    "avg": _round_optional(r["spo2_avg"]) if spo2_cnt > 0 else None,
                },
                "temperature_f": {
                    "valid_count": temp_cnt,
                    "min": _round_optional(r["temp_min"]) if temp_cnt > 0 else None,
                    "max": _round_optional(r["temp_max"]) if temp_cnt > 0 else None,
                    "avg": _round_optional(r["temp_avg"]) if temp_cnt > 0 else None,
                },
            })

        return results

    def get_time_bucketed_vitals(
        self,
        patient_id: Optional[str] = None,
        interval: str = "hour",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate vital signs into chronological buckets (hourly or daily) using SQL date formatting.
        Compatible with MySQL (DATE_FORMAT) and SQLite (strftime fallback).
        """
        clean_patient_id = validate_patient_id(patient_id) if patient_id else None
        clean_interval = validate_bucket_interval(interval)
        norm_start, norm_end = validate_time_range(start_time, end_time)

        # Dialect-aware date formatting
        dialect_name = getattr(getattr(self.session, "bind", None), "dialect", None)
        is_sqlite = dialect_name is not None and dialect_name.name == "sqlite"

        if is_sqlite:
            fmt_str = "%Y-%m-%d %H:00:00" if clean_interval == "hour" else "%Y-%m-%d"
            bucket_expr = func.strftime(fmt_str, IngestionEvent.measured_at)
        else:
            fmt_str = "%Y-%m-%d %H:00:00" if clean_interval == "hour" else "%Y-%m-%d"
            bucket_expr = func.date_format(IngestionEvent.measured_at, fmt_str)

        temp_f_expr = case(
            (VitalsReading.raw_unit == "degF", VitalsReading.raw_value),
            else_=func.round(VitalsReading.value * 9.0 / 5.0 + 32.0, 2),
        )

        filters = [IngestionEvent.measured_at.is_not(None)]
        if clean_patient_id:
            filters.append(IngestionEvent.patient_id == clean_patient_id)
        if norm_start:
            filters.append(IngestionEvent.measured_at >= norm_start)
        if norm_end:
            filters.append(IngestionEvent.measured_at <= norm_end)

        stmt = (
            select(
                bucket_expr.label("time_bucket"),
                func.count(distinct(IngestionEvent.event_id)).label("observation_count"),
                func.avg(case((VitalsReading.metric_code == "heart_rate", VitalsReading.value))).label("avg_heart_rate"),
                func.avg(case((VitalsReading.metric_code == "spo2", VitalsReading.value))).label("avg_spo2"),
                func.avg(case((VitalsReading.metric_code == "temperature", temp_f_expr))).label("avg_temperature_f"),
                func.min(case((VitalsReading.metric_code == "heart_rate", VitalsReading.value))).label("min_heart_rate"),
                func.max(case((VitalsReading.metric_code == "heart_rate", VitalsReading.value))).label("max_heart_rate"),
            )
            .join(VitalsReading, IngestionEvent.event_id == VitalsReading.event_id)
            .where(*filters)
            .group_by("time_bucket")
            .order_by("time_bucket")
        )

        rows = self.session.execute(stmt).mappings().all()
        results: List[Dict[str, Any]] = []

        for r in rows:
            results.append({
                "time_bucket": r["time_bucket"],
                "observation_count": r["observation_count"] or 0,
                "avg_heart_rate": _round_optional(r["avg_heart_rate"]),
                "avg_spo2": _round_optional(r["avg_spo2"]),
                "avg_temperature_f": _round_optional(r["avg_temperature_f"]),
                "min_heart_rate": _round_optional(r["min_heart_rate"]),
                "max_heart_rate": _round_optional(r["max_heart_rate"]),
            })
        return results

    def get_patient_telemetry_history(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve chronological bounded telemetry records for a patient from ingestion_events and vitals_readings.
        """
        clean_patient_id = validate_patient_id(patient_id)
        norm_start, norm_end = validate_time_range(start_time, end_time)
        bounded_limit, safe_offset = validate_pagination(limit=limit, offset=offset)

        filters = [IngestionEvent.patient_id == clean_patient_id]
        if norm_start:
            filters.append(IngestionEvent.measured_at >= norm_start)
        if norm_end:
            filters.append(IngestionEvent.measured_at <= norm_end)

        stmt = (
            select(IngestionEvent)
            .where(*filters)
            .order_by(desc(IngestionEvent.measured_at), desc(IngestionEvent.event_id))
            .offset(safe_offset)
            .limit(bounded_limit)
        )
        events = list(self.session.scalars(stmt).all())

        results: List[Dict[str, Any]] = []
        for ev in events:
            # Build metrics sub-object matching MongoDB schema
            metrics: Dict[str, Optional[float]] = {
                "heart_rate": None,
                "spo2": None,
                "temperature_f": None,
                "temperature_c": None,
            }
            for r in getattr(ev, "readings", []):
                val_flt = float(r.value) if r.value is not None else None
                if r.metric_code == "heart_rate":
                    metrics["heart_rate"] = val_flt
                elif r.metric_code == "spo2":
                    metrics["spo2"] = val_flt
                elif r.metric_code == "temperature":
                    metrics["temperature_c"] = val_flt
                    if r.raw_unit == "degF" and r.raw_value is not None:
                        metrics["temperature_f"] = float(r.raw_value)
                    elif val_flt is not None:
                        metrics["temperature_f"] = round(val_flt * 9.0 / 5.0 + 32.0, 2)

            results.append({
                "event_id": ev.event_id,
                "patient_id": ev.patient_id,
                "measured_at": normalize_datetime(ev.measured_at),
                "received_at": normalize_datetime(ev.received_at),
                "source": ev.source,
                "source_event_id": ev.source_event_id,
                "is_simulated": ev.is_simulated,
                "metrics": metrics,
            })
        return results

    def get_source_provenance_summary(self) -> Dict[str, Any]:
        """
        Calculate telemetry distribution by origin source and simulation status in MySQL.
        """
        stmt = (
            select(
                IngestionEvent.source,
                IngestionEvent.is_simulated,
                func.count(IngestionEvent.event_id).label("document_count"),
                func.min(IngestionEvent.measured_at).label("earliest_timestamp"),
                func.max(IngestionEvent.measured_at).label("latest_timestamp"),
            )
            .group_by(IngestionEvent.source, IngestionEvent.is_simulated)
            .order_by(desc("document_count"), IngestionEvent.source)
        )
        rows = self.session.execute(stmt).mappings().all()

        total_docs = sum(r["document_count"] for r in rows)
        breakdown = [
            {
                "source": r["source"],
                "is_simulated": bool(r["is_simulated"]),
                "document_count": r["document_count"],
                "earliest_timestamp": normalize_datetime(r["earliest_timestamp"]),
                "latest_timestamp": normalize_datetime(r["latest_timestamp"]),
            }
            for r in rows
        ]

        return {
            "total_documents": total_docs,
            "categories_count": len(breakdown),
            "provenance_breakdown": breakdown,
        }

    def get_alert_summary(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate clinical alerts by severity, lifecycle status, patient, and acknowledgement metrics in MySQL.
        """
        clean_patient_id = validate_patient_id(patient_id) if patient_id else None
        norm_start, norm_end = validate_time_range(start_time, end_time)

        filters = []
        if clean_patient_id:
            filters.append(Alert.patient_id == clean_patient_id)
        if norm_start:
            filters.append(Alert.created_at >= norm_start)
        if norm_end:
            filters.append(Alert.created_at <= norm_end)

        # 1. By severity
        stmt_sev = (
            select(Alert.severity, func.count(Alert.alert_id).label("cnt"))
            .where(*filters)
            .group_by(Alert.severity)
            .order_by(desc("cnt"))
        )
        by_sev = {r[0]: r[1] for r in self.session.execute(stmt_sev).all()}

        # 2. By status
        stmt_stat = (
            select(Alert.status, func.count(Alert.alert_id).label("cnt"))
            .where(*filters)
            .group_by(Alert.status)
            .order_by(desc("cnt"))
        )
        by_stat = {r[0]: r[1] for r in self.session.execute(stmt_stat).all()}

        # 3. By patient
        stmt_pat = (
            select(Alert.patient_id, func.count(Alert.alert_id).label("cnt"))
            .where(*filters)
            .group_by(Alert.patient_id)
            .order_by(desc("cnt"))
        )
        by_pat = {r[0]: r[1] for r in self.session.execute(stmt_pat).all()}

        # 4. Acknowledgement metrics
        stmt_ack = select(
            func.count(Alert.alert_id).label("total"),
            func.sum(case((Alert.acknowledged_at.is_not(None), 1), else_=0)).label("ack_cnt"),
            func.sum(case((Alert.acknowledged_at.is_(None), 1), else_=0)).label("unack_cnt"),
        ).where(*filters)
        ack_row = self.session.execute(stmt_ack).mappings().first()

        total = ack_row["total"] if ack_row else 0
        ack_count = ack_row["ack_cnt"] if ack_row and ack_row["ack_cnt"] is not None else 0
        unack_count = ack_row["unack_cnt"] if ack_row and ack_row["unack_cnt"] is not None else 0
        ack_rate = round((ack_count / total) * 100.0, 2) if total and total > 0 else 0.0

        return {
            "total_alerts": total or 0,
            "by_severity": by_sev,
            "by_status": by_stat,
            "by_patient": by_pat,
            "acknowledgement": {
                "acknowledged_count": ack_count or 0,
                "unacknowledged_count": unack_count or 0,
                "acknowledgement_rate_percent": ack_rate,
            },
        }

    def get_data_quality_report(self) -> Dict[str, Any]:
        """
        Execute comprehensive relational telemetry data-quality audit diagnostics.
        """
        # Missing fields in ingestion_events
        stmt_ev = select(
            func.count(IngestionEvent.event_id).label("total_checked"),
            func.sum(case((IngestionEvent.patient_id.is_(None) | (IngestionEvent.patient_id == ""), 1), else_=0)).label("missing_patient"),
            func.sum(case((IngestionEvent.measured_at.is_(None), 1), else_=0)).label("missing_measured"),
            func.sum(case((IngestionEvent.source.is_(None) | (IngestionEvent.source == ""), 1), else_=0)).label("missing_src"),
        )
        ev_row = self.session.execute(stmt_ev).mappings().first()
        total_checked = ev_row["total_checked"] if ev_row else 0

        # Duplicate (source, source_event_id)
        stmt_dups = select(
            func.count().label("dup_count")
        ).select_from(
            select(IngestionEvent.source, IngestionEvent.source_event_id)
            .group_by(IngestionEvent.source, IngestionEvent.source_event_id)
            .having(func.count() > 1)
            .subquery()
        )
        dup_count = self.session.scalar(stmt_dups) or 0

        # Vitals metrics quality
        temp_f_expr = case(
            (VitalsReading.raw_unit == "degF", VitalsReading.raw_value),
            else_=func.round(VitalsReading.value * 9.0 / 5.0 + 32.0, 2),
        )
        stmt_readings = select(
            func.sum(case((VitalsReading.metric_code == "heart_rate", case((VitalsReading.value.is_(None), 1), else_=0)), else_=0)).label("null_hr"),
            func.sum(case((VitalsReading.metric_code == "spo2", case((VitalsReading.value.is_(None), 1), else_=0)), else_=0)).label("null_spo2"),
            func.sum(case((VitalsReading.metric_code == "temperature", case((VitalsReading.value.is_(None), 1), else_=0)), else_=0)).label("null_temp"),
            func.sum(case((VitalsReading.metric_code == "heart_rate", case((VitalsReading.value < 30 | (VitalsReading.value > 250), 1), else_=0)), else_=0)).label("implausible_hr"),
            func.sum(case((VitalsReading.metric_code == "spo2", case((VitalsReading.value < 50.0 | (VitalsReading.value > 100.0), 1), else_=0)), else_=0)).label("implausible_spo2"),
            func.sum(case((VitalsReading.metric_code == "temperature", case((temp_f_expr < 90.0 | (temp_f_expr > 115.0), 1), else_=0)), else_=0)).label("implausible_temp"),
        )
        r_row = self.session.execute(stmt_readings).mappings().first()

        missing_fields = {
            "missing_patient_id": int(ev_row["missing_patient"] or 0) if ev_row else 0,
            "missing_measured_at": int(ev_row["missing_measured"] or 0) if ev_row else 0,
            "missing_source": int(ev_row["missing_src"] or 0) if ev_row else 0,
        }

        null_metrics = {
            "null_heart_rate": int(r_row["null_hr"] or 0) if r_row else 0,
            "null_spo2": int(r_row["null_spo2"] or 0) if r_row else 0,
            "null_temperature_f": int(r_row["null_temp"] or 0) if r_row else 0,
        }

        invalid_types = {
            "invalid_type_heart_rate": 0,  # Enforced by SQL DECIMAL types
            "invalid_type_spo2": 0,
            "invalid_type_temperature_f": 0,
        }

        implausible_values = {
            "implausible_heart_rate": int(r_row["implausible_hr"] or 0) if r_row else 0,
            "implausible_spo2": int(r_row["implausible_spo2"] or 0) if r_row else 0,
            "implausible_temperature_f": int(r_row["implausible_temp"] or 0) if r_row else 0,
        }

        has_issues = (
            sum(missing_fields.values()) > 0
            or sum(implausible_values.values()) > 0
            or dup_count > 0
        )

        return {
            "total_checked": total_checked,
            "missing_fields": missing_fields,
            "null_metrics": null_metrics,
            "invalid_types": invalid_types,
            "implausible_values": implausible_values,
            "duplicate_source_identities": dup_count,
            "is_clean": not has_issues,
        }
