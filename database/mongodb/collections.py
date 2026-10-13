"""
MongoDB Collection Names, Document Schemas, and Index Specifications.

Defines the analytics mirror schemas for MongoDB Atlas:
- telemetry_events: NoSQL time-series and vital observation mirror.
- alert_events: NoSQL clinical alert lifecycle mirror.
"""

from __future__ import annotations

from typing import Any, Dict, List

TELEMETRY_COLLECTION = "telemetry_events"
ALERTS_COLLECTION = "alert_events"

ALERT_STATUS_RANKS: Dict[str, int] = {
    "NEW": 1,
    "ACKNOWLEDGED": 2,
    "RESOLVED": 3,
}

# Index definitions: (name, list of (field, direction), unique, sparse)
TELEMETRY_INDEXES = [
    {
        "name": "idx_telemetry_patient_measured",
        "keys": [("patient_id", 1), ("measured_at", -1)],
        "unique": False,
    },
    {
        "name": "idx_telemetry_measured_at",
        "keys": [("measured_at", -1)],
        "unique": False,
    },
    {
        "name": "idx_telemetry_source",
        "keys": [("source", 1)],
        "unique": False,
    },
    {
        "name": "idx_telemetry_simulated",
        "keys": [("is_simulated", 1)],
        "unique": False,
    },
    {
        "name": "idx_telemetry_source_event_id",
        "keys": [("source_event_id", 1)],
        "unique": False,
        "sparse": True,
    },
]

ALERT_INDEXES = [
    {
        "name": "idx_alerts_patient_created",
        "keys": [("patient_id", 1), ("created_at", -1)],
        "unique": False,
    },
    {
        "name": "idx_alerts_status_severity",
        "keys": [("status", 1), ("severity", 1)],
        "unique": False,
    },
    {
        "name": "idx_alerts_rule_id",
        "keys": [("rule_id", 1)],
        "unique": False,
    },
    {
        "name": "idx_alerts_event_id",
        "keys": [("event_id", 1)],
        "unique": False,
    },
]
