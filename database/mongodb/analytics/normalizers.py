"""
Result Normalization and Formatting for MongoDB Analytics Aggregation Outputs.

Ensures:
- Safe handling of empty collections and zero-matched result sets.
- Consistent numeric rounding (2 decimal places for clinical statistics).
- Preservation of None (null) semantics for absent measurements.
- Serialization-friendly dictionary representations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from database.mongodb.analytics.validators import normalize_datetime


def _round_optional(val: Optional[float], decimals: int = 2) -> Optional[float]:
    """Safely round optional float to given decimal places."""
    if val is None:
        return None
    return round(float(val), decimals)


def normalize_dataset_overview(raw_result: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Normalize dataset overview facet aggregation results into a clean dictionary.
    """
    default_response: Dict[str, Any] = {
        "total_documents": 0,
        "distinct_patients_count": 0,
        "distinct_patient_ids": [],
        "documents_by_source": {},
        "documents_by_simulation": {
            "simulated": 0,
            "non_simulated": 0,
        },
        "earliest_measured_at": None,
        "latest_measured_at": None,
        "provenance_note": "MongoDB analytics mirror reflects replicated telemetry events from MySQL outbox.",
    }

    if not raw_result:
        return default_response

    facet_data = raw_result[0]
    overview_list = facet_data.get("overview", [])
    if not overview_list:
        return default_response

    ov = overview_list[0]
    distinct_patients = [doc["_id"] for doc in facet_data.get("distinct_patients", []) if doc.get("_id")]
    
    by_source: Dict[str, int] = {}
    for item in facet_data.get("by_source", []):
        src_name = item.get("_id") or "unknown"
        by_source[src_name] = item.get("count", 0)

    simulated_count = ov.get("simulated_count", 0)
    non_simulated_count = ov.get("non_simulated_count", 0)

    return {
        "total_documents": ov.get("total_documents", 0),
        "distinct_patients_count": len(distinct_patients),
        "distinct_patient_ids": distinct_patients,
        "documents_by_source": by_source,
        "documents_by_simulation": {
            "simulated": simulated_count,
            "non_simulated": non_simulated_count,
        },
        "earliest_measured_at": normalize_datetime(ov.get("earliest_measured_at")),
        "latest_measured_at": normalize_datetime(ov.get("latest_measured_at")),
        "provenance_note": default_response["provenance_note"],
    }


def normalize_patient_vitals_summary(raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize patient vitals summary statistics:
    - Rounds average figures.
    - Preserves nulls when no valid numeric observations exist.
    """
    normalized: List[Dict[str, Any]] = []
    for doc in raw_results:
        patient_id = doc.get("patient_id", "")
        total_obs = doc.get("total_observations", 0)

        def _format_metric(sub: Dict[str, Any]) -> Dict[str, Any]:
            vcount = sub.get("valid_count", 0)
            return {
                "valid_count": vcount,
                "min": _round_optional(sub.get("min")) if vcount > 0 else None,
                "max": _round_optional(sub.get("max")) if vcount > 0 else None,
                "avg": _round_optional(sub.get("avg")) if vcount > 0 else None,
            }

        hr = _format_metric(doc.get("heart_rate", {}))
        spo2 = _format_metric(doc.get("spo2", {}))
        temp = _format_metric(doc.get("temperature_f", {}))

        normalized.append({
            "patient_id": patient_id,
            "total_observations": total_obs,
            "heart_rate": hr,
            "spo2": spo2,
            "temperature_f": temp,
        })
    return normalized


def normalize_time_buckets(raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize time-bucketed vitals aggregates.
    """
    normalized: List[Dict[str, Any]] = []
    for doc in raw_results:
        normalized.append({
            "time_bucket": doc.get("time_bucket"),
            "observation_count": doc.get("observation_count", 0),
            "avg_heart_rate": _round_optional(doc.get("avg_heart_rate")),
            "avg_spo2": _round_optional(doc.get("avg_spo2")),
            "avg_temperature_f": _round_optional(doc.get("avg_temperature_f")),
            "min_heart_rate": _round_optional(doc.get("min_heart_rate")),
            "max_heart_rate": _round_optional(doc.get("max_heart_rate")),
        })
    return normalized


def normalize_source_provenance(raw_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Normalize source and provenance summary.
    """
    total_docs = sum(item.get("document_count", 0) for item in raw_results)
    breakdown: List[Dict[str, Any]] = []
    
    for item in raw_results:
        breakdown.append({
            "source": item.get("source") or "unknown",
            "is_simulated": bool(item.get("is_simulated", False)),
            "document_count": item.get("document_count", 0),
            "earliest_timestamp": normalize_datetime(item.get("earliest_timestamp")),
            "latest_timestamp": normalize_datetime(item.get("latest_timestamp")),
        })

    return {
        "total_documents": total_docs,
        "categories_count": len(breakdown),
        "provenance_breakdown": breakdown,
    }


def normalize_alert_summary(raw_result: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Normalize clinical alert facet aggregation results.
    """
    default_response: Dict[str, Any] = {
        "total_alerts": 0,
        "by_severity": {},
        "by_status": {},
        "by_patient": {},
        "acknowledgement": {
            "acknowledged_count": 0,
            "unacknowledged_count": 0,
            "acknowledgement_rate_percent": 0.0,
        },
    }

    if not raw_result:
        return default_response

    facet_data = raw_result[0]

    by_sev: Dict[str, int] = {}
    for item in facet_data.get("by_severity", []):
        by_sev[item.get("_id") or "UNKNOWN"] = item.get("count", 0)

    by_stat: Dict[str, int] = {}
    for item in facet_data.get("by_status", []):
        by_stat[item.get("_id") or "UNKNOWN"] = item.get("count", 0)

    by_pat: Dict[str, int] = {}
    for item in facet_data.get("by_patient", []):
        by_pat[item.get("_id") or "UNKNOWN"] = item.get("count", 0)

    ack_list = facet_data.get("acknowledgement_metrics", [])
    total_alerts = 0
    ack_count = 0
    unack_count = 0
    ack_rate = 0.0

    if ack_list:
        ack_doc = ack_list[0]
        total_alerts = ack_doc.get("total_alerts", 0)
        ack_count = ack_doc.get("acknowledged_count", 0)
        unack_count = ack_doc.get("unacknowledged_count", 0)
        if total_alerts > 0:
            ack_rate = round((ack_count / total_alerts) * 100.0, 2)

    return {
        "total_alerts": total_alerts,
        "by_severity": by_sev,
        "by_status": by_stat,
        "by_patient": by_pat,
        "acknowledgement": {
            "acknowledged_count": ack_count,
            "unacknowledged_count": unack_count,
            "acknowledgement_rate_percent": ack_rate,
        },
    }


def normalize_data_quality(
    raw_metrics: List[Dict[str, Any]],
    duplicate_source_count: int = 0,
) -> Dict[str, Any]:
    """
    Normalize telemetry data-quality audit diagnostics.
    """
    if not raw_metrics:
        return {
            "total_checked": 0,
            "missing_fields": {
                "missing_patient_id": 0,
                "missing_measured_at": 0,
                "missing_source": 0,
            },
            "null_metrics": {
                "null_heart_rate": 0,
                "null_spo2": 0,
                "null_temperature_f": 0,
            },
            "invalid_types": {
                "invalid_type_heart_rate": 0,
                "invalid_type_spo2": 0,
                "invalid_type_temperature_f": 0,
            },
            "implausible_values": {
                "implausible_heart_rate": 0,
                "implausible_spo2": 0,
                "implausible_temperature_f": 0,
            },
            "duplicate_source_identities": 0,
            "is_clean": True,
        }

    m = raw_metrics[0]
    total_checked = m.get("total_checked", 0)

    missing_fields = {
        "missing_patient_id": m.get("missing_patient_id", 0),
        "missing_measured_at": m.get("missing_measured_at", 0),
        "missing_source": m.get("missing_source", 0),
    }

    null_metrics = {
        "null_heart_rate": m.get("null_heart_rate", 0),
        "null_spo2": m.get("null_spo2", 0),
        "null_temperature_f": m.get("null_temperature_f", 0),
    }

    invalid_types = {
        "invalid_type_heart_rate": m.get("invalid_type_heart_rate", 0),
        "invalid_type_spo2": m.get("invalid_type_spo2", 0),
        "invalid_type_temperature_f": m.get("invalid_type_temperature_f", 0),
    }

    implausible_values = {
        "implausible_heart_rate": m.get("implausible_heart_rate", 0),
        "implausible_spo2": m.get("implausible_spo2", 0),
        "implausible_temperature_f": m.get("implausible_temperature_f", 0),
    }

    has_issues = (
        sum(missing_fields.values()) > 0
        or sum(invalid_types.values()) > 0
        or sum(implausible_values.values()) > 0
        or duplicate_source_count > 0
    )

    return {
        "total_checked": total_checked,
        "missing_fields": missing_fields,
        "null_metrics": null_metrics,
        "invalid_types": invalid_types,
        "implausible_values": implausible_values,
        "duplicate_source_identities": duplicate_source_count,
        "is_clean": not has_issues,
    }
