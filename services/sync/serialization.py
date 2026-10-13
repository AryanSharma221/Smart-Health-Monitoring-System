"""
Document Serialization and Mapping for MongoDB Atlas Analytics Mirror.

Converts relational SQLAlchemy models into analytics-friendly, NoSQL documents:
- Preserves source units and provenance.
- Excludes sensitive security information (passwords, tokens, personal identifiers).
- Handles ISO datetime and native datetime conversion for BSON storage.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from database.mongodb.collections import ALERT_STATUS_RANKS
from database.mysql.models import Alert, IngestionEvent, VitalsReading


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder handling datetime and Decimal types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def build_telemetry_document(event: IngestionEvent) -> Dict[str, Any]:
    """
    Build a MongoDB analytics document from an IngestionEvent and its VitalsReadings.
    Preserves original Kaggle units (bpm, %, Fahrenheit, Celsius) and simulation provenance.
    """
    now = datetime.now(timezone.utc)
    metrics: Dict[str, Optional[float]] = {
        "heart_rate": None,
        "spo2": None,
        "temperature_f": None,
        "temperature_c": None,
    }
    readings_summary: List[Dict[str, Any]] = []

    for r in getattr(event, "readings", []):
        val_float = float(r.value) if r.value is not None else None
        code = r.metric_code

        if code == "heart_rate":
            metrics["heart_rate"] = val_float
        elif code == "spo2":
            metrics["spo2"] = val_float
        elif code == "temperature":
            metrics["temperature_c"] = val_float
            if getattr(r, "raw_unit", "") == "degF" and r.raw_value is not None:
                metrics["temperature_f"] = float(r.raw_value)
            elif val_float is not None:
                # Derive Fahrenheit for analytics consistency
                metrics["temperature_f"] = round(val_float * 9.0 / 5.0 + 32.0, 2)

        readings_summary.append({
            "metric_code": code,
            "value": val_float,
            "unit": r.unit,
            "raw_value": float(r.raw_value) if getattr(r, "raw_value", None) is not None else None,
            "raw_unit": getattr(r, "raw_unit", r.unit),
            "quality_status": r.quality_status,
        })

    doc: Dict[str, Any] = {
        "_id": event.event_id,
        "event_id": event.event_id,
        "patient_id": event.patient_id,
        "measured_at": event.measured_at,
        "received_at": getattr(event, "received_at", now),
        "source": event.source,
        "source_event_id": event.source_event_id,
        "is_simulated": event.is_simulated,
        "metrics": metrics,
        "readings_summary": readings_summary,
        "mirrored_at": now,
        "schema_version": 1,
    }
    return doc


def build_alert_document(alert: Alert) -> Dict[str, Any]:
    """
    Build a MongoDB analytics document from a clinical Alert entity.
    Stores lifecycle status, reason, timestamps, and monotonic state_rank.
    """
    now = datetime.now(timezone.utc)
    status_str = alert.status or "NEW"
    state_rank = ALERT_STATUS_RANKS.get(status_str, 1)

    doc: Dict[str, Any] = {
        "_id": alert.alert_id,
        "alert_id": alert.alert_id,
        "patient_id": alert.patient_id,
        "event_id": alert.event_id,
        "rule_id": alert.rule_id,
        "severity": alert.severity,
        "category": alert.category,
        "reason": alert.reason,
        "status": status_str,
        "state_rank": state_rank,
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": alert.acknowledged_at,
        "resolved_by": alert.resolved_by,
        "resolved_at": alert.resolved_at,
        "created_at": alert.created_at or now,
        "mirrored_at": now,
        "schema_version": 1,
    }
    return doc


def document_to_json(doc: Dict[str, Any]) -> str:
    """Serialize document dictionary to JSON for outbox storage."""
    return json.dumps(doc, cls=CustomJSONEncoder)


def json_to_document(payload_json: str) -> Dict[str, Any]:
    """
    Deserialize outbox JSON payload back to document dictionary.
    Converts ISO date strings back to native UTC datetime objects for BSON storage.
    """
    data = json.loads(payload_json)
    date_fields = ["measured_at", "received_at", "mirrored_at", "created_at", "acknowledged_at", "resolved_at"]
    for field in date_fields:
        val = data.get(field)
        if isinstance(val, str):
            try:
                data[field] = datetime.fromisoformat(val)
            except ValueError:
                pass
    return data
