"""
MongoDB Aggregation Pipeline Builders for Healthcare Telemetry & Alerts.

Provides pure, composable pipeline generation functions:
- Early $match filtering leveraging compound indexes.
- Accumulators with explicit guards for non-numeric/null values.
- Multi-faceted analytics using $facet.
- Deterministic sorting and bounded projections.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def build_dataset_overview_pipeline() -> List[Dict[str, Any]]:
    """
    Construct multi-faceted aggregation pipeline for telemetry collection overview:
    1. Global document count, time boundaries, simulation counts.
    2. Distinct patient identifiers.
    3. Breakdown by source category.
    """
    return [
        {
            "$facet": {
                "overview": [
                    {
                        "$group": {
                            "_id": None,
                            "total_documents": {"$sum": 1},
                            "earliest_measured_at": {"$min": "$measured_at"},
                            "latest_measured_at": {"$max": "$measured_at"},
                            "simulated_count": {
                                "$sum": {"$cond": [{"$eq": ["$is_simulated", True]}, 1, 0]}
                            },
                            "non_simulated_count": {
                                "$sum": {"$cond": [{"$ne": ["$is_simulated", True]}, 1, 0]}
                            },
                        }
                    }
                ],
                "distinct_patients": [
                    {"$group": {"_id": "$patient_id"}},
                    {"$sort": {"_id": 1}},
                ],
                "by_source": [
                    {"$group": {"_id": "$source", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1, "_id": 1}},
                ],
            }
        }
    ]


def build_patient_vitals_summary_pipeline(
    patient_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Construct aggregation pipeline computing measurement statistics per patient:
    - valid_count, min, max, average for heart_rate, spo2, temperature_f.
    - Explicit $isNumber guards preventing null/string corruption.
    - Early index-friendly $match on (patient_id, measured_at).
    """
    match_stage: Dict[str, Any] = {}
    if patient_id:
        match_stage["patient_id"] = patient_id
    if start_time or end_time:
        time_filter: Dict[str, Any] = {}
        if start_time:
            time_filter["$gte"] = start_time
        if end_time:
            time_filter["$lte"] = end_time
        match_stage["measured_at"] = time_filter

    pipeline: List[Dict[str, Any]] = []
    if match_stage:
        pipeline.append({"$match": match_stage})

    pipeline.extend([
        {
            "$group": {
                "_id": "$patient_id",
                "total_observations": {"$sum": 1},
                # Heart Rate stats
                "hr_valid_count": {
                    "$sum": {"$cond": [{"$isNumber": "$metrics.heart_rate"}, 1, 0]}
                },
                "hr_min": {
                    "$min": {
                        "$cond": [
                            {"$isNumber": "$metrics.heart_rate"},
                            "$metrics.heart_rate",
                            None,
                        ]
                    }
                },
                "hr_max": {
                    "$max": {
                        "$cond": [
                            {"$isNumber": "$metrics.heart_rate"},
                            "$metrics.heart_rate",
                            None,
                        ]
                    }
                },
                "hr_avg": {
                    "$avg": {
                        "$cond": [
                            {"$isNumber": "$metrics.heart_rate"},
                            "$metrics.heart_rate",
                            None,
                        ]
                    }
                },
                # SpO2 stats
                "spo2_valid_count": {
                    "$sum": {"$cond": [{"$isNumber": "$metrics.spo2"}, 1, 0]}
                },
                "spo2_min": {
                    "$min": {
                        "$cond": [{"$isNumber": "$metrics.spo2"}, "$metrics.spo2", None]
                    }
                },
                "spo2_max": {
                    "$max": {
                        "$cond": [{"$isNumber": "$metrics.spo2"}, "$metrics.spo2", None]
                    }
                },
                "spo2_avg": {
                    "$avg": {
                        "$cond": [{"$isNumber": "$metrics.spo2"}, "$metrics.spo2", None]
                    }
                },
                # Temperature (Fahrenheit) stats
                "temp_valid_count": {
                    "$sum": {
                        "$cond": [{"$isNumber": "$metrics.temperature_f"}, 1, 0]
                    }
                },
                "temp_min": {
                    "$min": {
                        "$cond": [
                            {"$isNumber": "$metrics.temperature_f"},
                            "$metrics.temperature_f",
                            None,
                        ]
                    }
                },
                "temp_max": {
                    "$max": {
                        "$cond": [
                            {"$isNumber": "$metrics.temperature_f"},
                            "$metrics.temperature_f",
                            None,
                        ]
                    }
                },
                "temp_avg": {
                    "$avg": {
                        "$cond": [
                            {"$isNumber": "$metrics.temperature_f"},
                            "$metrics.temperature_f",
                            None,
                        ]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "patient_id": "$_id",
                "total_observations": 1,
                "heart_rate": {
                    "valid_count": "$hr_valid_count",
                    "min": "$hr_min",
                    "max": "$hr_max",
                    "avg": "$hr_avg",
                },
                "spo2": {
                    "valid_count": "$spo2_valid_count",
                    "min": "$spo2_min",
                    "max": "$spo2_max",
                    "avg": "$spo2_avg",
                },
                "temperature_f": {
                    "valid_count": "$temp_valid_count",
                    "min": "$temp_min",
                    "max": "$temp_max",
                    "avg": "$temp_avg",
                },
            }
        },
        {"$sort": {"patient_id": 1}},
    ])
    return pipeline


def build_time_bucketed_vitals_pipeline(
    patient_id: Optional[str] = None,
    interval: str = "hour",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Construct aggregation pipeline grouping vitals readings into chronological time buckets.
    Supported intervals: 'hour' (%Y-%m-%d %H:00:00), 'day' (%Y-%m-%d).
    """
    date_format = "%Y-%m-%d %H:00:00" if interval == "hour" else "%Y-%m-%d"

    match_stage: Dict[str, Any] = {"measured_at": {"$ne": None}}
    if patient_id:
        match_stage["patient_id"] = patient_id
    if start_time or end_time:
        time_filter: Dict[str, Any] = match_stage["measured_at"]
        if start_time:
            time_filter["$gte"] = start_time
        if end_time:
            time_filter["$lte"] = end_time

    return [
        {"$match": match_stage},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": date_format,
                        "date": "$measured_at",
                    }
                },
                "observation_count": {"$sum": 1},
                "avg_heart_rate": {
                    "$avg": {
                        "$cond": [
                            {"$isNumber": "$metrics.heart_rate"},
                            "$metrics.heart_rate",
                            None,
                        ]
                    }
                },
                "avg_spo2": {
                    "$avg": {
                        "$cond": [
                            {"$isNumber": "$metrics.spo2"},
                            "$metrics.spo2",
                            None,
                        ]
                    }
                },
                "avg_temperature_f": {
                    "$avg": {
                        "$cond": [
                            {"$isNumber": "$metrics.temperature_f"},
                            "$metrics.temperature_f",
                            None,
                        ]
                    }
                },
                "min_heart_rate": {
                    "$min": {
                        "$cond": [
                            {"$isNumber": "$metrics.heart_rate"},
                            "$metrics.heart_rate",
                            None,
                        ]
                    }
                },
                "max_heart_rate": {
                    "$max": {
                        "$cond": [
                            {"$isNumber": "$metrics.heart_rate"},
                            "$metrics.heart_rate",
                            None,
                        ]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "time_bucket": "$_id",
                "observation_count": 1,
                "avg_heart_rate": 1,
                "avg_spo2": 1,
                "avg_temperature_f": 1,
                "min_heart_rate": 1,
                "max_heart_rate": 1,
            }
        },
        {"$sort": {"time_bucket": 1}},
    ]


def build_patient_history_pipeline(
    patient_id: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Construct pipeline for bounded, deterministic patient telemetry history:
    - Utilizes compound index (patient_id, measured_at DESC).
    - Sorts with tie-breaker on event_id.
    - Limits and skips for clean pagination.
    """
    match_stage: Dict[str, Any] = {"patient_id": patient_id}
    if start_time or end_time:
        time_filter: Dict[str, Any] = {}
        if start_time:
            time_filter["$gte"] = start_time
        if end_time:
            time_filter["$lte"] = end_time
        match_stage["measured_at"] = time_filter

    pipeline: List[Dict[str, Any]] = [
        {"$match": match_stage},
        {"$sort": {"measured_at": -1, "event_id": -1}},
    ]

    if offset > 0:
        pipeline.append({"$skip": offset})
    pipeline.append({"$limit": limit})

    pipeline.append({
        "$project": {
            "_id": 0,
            "event_id": 1,
            "patient_id": 1,
            "measured_at": 1,
            "received_at": 1,
            "source": 1,
            "source_event_id": 1,
            "is_simulated": 1,
            "metrics": 1,
        }
    })
    return pipeline


def build_source_provenance_pipeline() -> List[Dict[str, Any]]:
    """
    Construct pipeline summarizing telemetry documents by (source, is_simulated).
    """
    return [
        {
            "$group": {
                "_id": {
                    "source": "$source",
                    "is_simulated": "$is_simulated",
                },
                "document_count": {"$sum": 1},
                "earliest_timestamp": {"$min": "$measured_at"},
                "latest_timestamp": {"$max": "$measured_at"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "source": "$_id.source",
                "is_simulated": "$_id.is_simulated",
                "document_count": 1,
                "earliest_timestamp": 1,
                "latest_timestamp": 1,
            }
        },
        {"$sort": {"document_count": -1, "source": 1}},
    ]


def build_alert_summary_pipeline(
    patient_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Construct multi-faceted aggregation pipeline for clinical alerts:
    - Counts by severity (CRITICAL, HIGH, MEDIUM, LOW).
    - Counts by lifecycle status (NEW, ACKNOWLEDGED, RESOLVED).
    - Counts by patient.
    - Acknowledgement summary (acknowledged vs unacknowledged).
    """
    match_stage: Dict[str, Any] = {}
    if patient_id:
        match_stage["patient_id"] = patient_id
    if start_time or end_time:
        time_filter: Dict[str, Any] = {}
        if start_time:
            time_filter["$gte"] = start_time
        if end_time:
            time_filter["$lte"] = end_time
        match_stage["created_at"] = time_filter

    pipeline: List[Dict[str, Any]] = []
    if match_stage:
        pipeline.append({"$match": match_stage})

    pipeline.append({
        "$facet": {
            "by_severity": [
                {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
                {"$sort": {"count": -1, "_id": 1}},
            ],
            "by_status": [
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                {"$sort": {"count": -1, "_id": 1}},
            ],
            "by_patient": [
                {"$group": {"_id": "$patient_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1, "_id": 1}},
            ],
            "acknowledgement_metrics": [
                {
                    "$group": {
                        "_id": None,
                        "total_alerts": {"$sum": 1},
                        "acknowledged_count": {
                            "$sum": {
                                "$cond": [{"$ne": ["$acknowledged_at", None]}, 1, 0]
                            }
                        },
                        "unacknowledged_count": {
                            "$sum": {
                                "$cond": [{"$eq": ["$acknowledged_at", None]}, 1, 0]
                            }
                        },
                    }
                }
            ],
        }
    })
    return pipeline


def build_data_quality_pipeline() -> List[Dict[str, Any]]:
    """
    Construct aggregation pipeline computing comprehensive telemetry data-quality metrics:
    - Missing required fields (patient_id, measured_at, source).
    - Null metrics (heart_rate, spo2, temperature_f).
    - Invalid data types (non-numeric values in numeric fields).
    - Physiologically implausible values:
      * HR < 30 or > 250 bpm
      * SpO2 < 50% or > 100%
      * Temp < 90.0°F or > 115.0°F
    """
    return [
        {
            "$group": {
                "_id": None,
                "total_checked": {"$sum": 1},
                "missing_patient_id": {
                    "$sum": {
                        "$cond": [
                            {
                                "$or": [
                                    {"$eq": ["$patient_id", None]},
                                    {"$eq": ["$patient_id", ""]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "missing_measured_at": {
                    "$sum": {"$cond": [{"$eq": ["$measured_at", None]}, 1, 0]}
                },
                "missing_source": {
                    "$sum": {
                        "$cond": [
                            {
                                "$or": [
                                    {"$eq": ["$source", None]},
                                    {"$eq": ["$source", ""]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "null_heart_rate": {
                    "$sum": {"$cond": [{"$eq": ["$metrics.heart_rate", None]}, 1, 0]}
                },
                "null_spo2": {
                    "$sum": {"$cond": [{"$eq": ["$metrics.spo2", None]}, 1, 0]}
                },
                "null_temperature_f": {
                    "$sum": {
                        "$cond": [{"$eq": ["$metrics.temperature_f", None]}, 1, 0]
                    }
                },
                "invalid_type_heart_rate": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$metrics.heart_rate", None]},
                                    {"$eq": [{"$isNumber": "$metrics.heart_rate"}, False]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "invalid_type_spo2": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$metrics.spo2", None]},
                                    {"$eq": [{"$isNumber": "$metrics.spo2"}, False]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "invalid_type_temperature_f": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$metrics.temperature_f", None]},
                                    {"$eq": [{"$isNumber": "$metrics.temperature_f"}, False]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "implausible_heart_rate": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$isNumber": "$metrics.heart_rate"},
                                    {
                                        "$or": [
                                            {"$lt": ["$metrics.heart_rate", 30]},
                                            {"$gt": ["$metrics.heart_rate", 250]},
                                        ]
                                    },
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "implausible_spo2": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$isNumber": "$metrics.spo2"},
                                    {
                                        "$or": [
                                            {"$lt": ["$metrics.spo2", 50.0]},
                                            {"$gt": ["$metrics.spo2", 100.0]},
                                        ]
                                    },
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "implausible_temperature_f": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$isNumber": "$metrics.temperature_f"},
                                    {
                                        "$or": [
                                            {"$lt": ["$metrics.temperature_f", 90.0]},
                                            {"$gt": ["$metrics.temperature_f", 115.0]},
                                        ]
                                    },
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        }
    ]


def build_duplicate_source_identities_pipeline() -> List[Dict[str, Any]]:
    """
    Construct pipeline detecting duplicate (source, source_event_id) pairs.
    """
    return [
        {
            "$match": {
                "source_event_id": {"$exists": True, "$ne": None}
            }
        },
        {
            "$group": {
                "_id": {
                    "source": "$source",
                    "source_event_id": "$source_event_id",
                },
                "count": {"$sum": 1},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "duplicate_source_identities"},
    ]
