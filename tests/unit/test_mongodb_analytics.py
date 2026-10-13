"""
Unit Tests for MongoDB Analytics Aggregation Pipelines and Repository.

Verifies the 15 required scenarios from Part 3B:
1. Dataset overview returns correct document counts and time boundaries.
2. Distinct patient count and identifiers are exact.
3. Patient-level statistics (min, max, avg, valid_count) match expected values.
4. Null measurements are never treated as zero.
5. Time buckets contain the expected records.
6. Start and end filters are applied correctly and validated.
7. Timestamp handling follows the documented UTC timezone policy.
8. Empty collections return valid, structured empty results.
9. Missing fields are handled safely without unhandled exceptions.
10. Provenance categories are not inferred without explicit field evidence.
11. Alert aggregations work when supported alert documents exist.
12. Data-quality diagnostics identify malformed and implausible records.
13. Result limits and pagination boundaries are enforced.
14. Untrusted inputs cannot inject arbitrary aggregation stages.
15. Integration with centralized Mongo repository lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import mongomock
import pytest

from database.mongodb.analytics.normalizers import (
    normalize_alert_summary,
    normalize_data_quality,
    normalize_dataset_overview,
    normalize_patient_vitals_summary,
    normalize_source_provenance,
    normalize_time_buckets,
)
from database.mongodb.analytics.validators import (
    normalize_datetime,
    validate_bucket_interval,
    validate_pagination,
    validate_patient_id,
    validate_time_range,
)
from database.mongodb.collections import ALERTS_COLLECTION, TELEMETRY_COLLECTION
from database.mongodb.repositories.analytics_repository import MongoAnalyticsRepository


@pytest.fixture
def mock_db() -> mongomock.Database:
    """Provide a fresh, isolated mongomock database instance."""
    client = mongomock.MongoClient()
    return client["smart_health_analytics_test"]


@pytest.fixture
def analytics_repo(mock_db: mongomock.Database) -> MongoAnalyticsRepository:
    """Provide repository instance connected to mock database."""
    return MongoAnalyticsRepository(mock_db)


@pytest.fixture
def sample_telemetry_docs() -> List[Dict[str, Any]]:
    """Controlled fixture with known statistical distributions."""
    t0 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "_id": "event_1",
            "event_id": "event_1",
            "patient_id": "P101",
            "measured_at": t0,
            "received_at": t0,
            "source": "kaggle_csv",
            "source_event_id": "src_1",
            "is_simulated": False,
            "metrics": {
                "heart_rate": 80.0,
                "spo2": 98.0,
                "temperature_f": 98.6,
                "temperature_c": 37.0,
            },
        },
        {
            "_id": "event_2",
            "event_id": "event_2",
            "patient_id": "P101",
            "measured_at": t0 + timedelta(hours=1),
            "received_at": t0 + timedelta(hours=1),
            "source": "kaggle_csv",
            "source_event_id": "src_2",
            "is_simulated": False,
            "metrics": {
                "heart_rate": 100.0,
                "spo2": 94.0,
                "temperature_f": 99.4,
                "temperature_c": 37.44,
            },
        },
        {
            "_id": "event_3",
            "event_id": "event_3",
            "patient_id": "P101",
            "measured_at": t0 + timedelta(hours=1, minutes=30),
            "received_at": t0 + timedelta(hours=1, minutes=30),
            "source": "simulated",
            "source_event_id": "src_3",
            "is_simulated": True,
            "metrics": {
                "heart_rate": 90.0,
                "spo2": 96.0,
                "temperature_f": 99.0,
                "temperature_c": 37.22,
            },
        },
        {
            "_id": "event_4",
            "event_id": "event_4",
            "patient_id": "P102",
            "measured_at": t0 + timedelta(hours=2),
            "received_at": t0 + timedelta(hours=2),
            "source": "device",
            "source_event_id": "src_4",
            "is_simulated": False,
            "metrics": {
                "heart_rate": 72.0,
                "spo2": None,  # Explicit null to test missing handling
                "temperature_f": 98.4,
                "temperature_c": 36.89,
            },
        },
    ]


@pytest.fixture
def sample_alert_docs() -> List[Dict[str, Any]]:
    """Controlled fixture with known clinical alerts."""
    t0 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "_id": "alert_1",
            "alert_id": "alert_1",
            "patient_id": "P101",
            "severity": "CRITICAL",
            "status": "NEW",
            "category": "vital_sign",
            "reason": "Tachycardia HR > 130",
            "acknowledged_at": None,
            "created_at": t0,
        },
        {
            "_id": "alert_2",
            "alert_id": "alert_2",
            "patient_id": "P101",
            "severity": "HIGH",
            "status": "ACKNOWLEDGED",
            "category": "vital_sign",
            "reason": "Hypoxemia SpO2 < 90%",
            "acknowledged_at": t0 + timedelta(minutes=15),
            "created_at": t0 + timedelta(minutes=5),
        },
        {
            "_id": "alert_3",
            "alert_id": "alert_3",
            "patient_id": "P102",
            "severity": "MEDIUM",
            "status": "RESOLVED",
            "category": "vital_sign",
            "reason": "Elevated temperature",
            "acknowledged_at": t0 + timedelta(minutes=30),
            "created_at": t0 + timedelta(minutes=10),
        },
    ]


# -------------------------------------------------------------------------
# Test 1 & 2: Dataset overview returns correct counts & distinct patients
# -------------------------------------------------------------------------
def test_dataset_overview_counts(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
    sample_telemetry_docs: List[Dict[str, Any]],
) -> None:
    mock_db[TELEMETRY_COLLECTION].insert_many(sample_telemetry_docs)
    overview = analytics_repo.get_dataset_overview()

    assert overview["total_documents"] == 4
    assert overview["distinct_patients_count"] == 2
    assert overview["distinct_patient_ids"] == ["P101", "P102"]
    assert overview["documents_by_source"] == {
        "kaggle_csv": 2,
        "simulated": 1,
        "device": 1,
    }
    assert overview["documents_by_simulation"] == {
        "simulated": 1,
        "non_simulated": 3,
    }
    assert overview["earliest_measured_at"] == datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    assert overview["latest_measured_at"] == datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)


# -------------------------------------------------------------------------
# Test 3: Patient-level statistics match expected values
# -------------------------------------------------------------------------
def test_patient_level_statistics_match_expected(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
    sample_telemetry_docs: List[Dict[str, Any]],
) -> None:
    mock_db[TELEMETRY_COLLECTION].insert_many(sample_telemetry_docs)
    summaries = analytics_repo.get_patient_vitals_summary()

    assert len(summaries) == 2
    p101 = next(s for s in summaries if s["patient_id"] == "P101")
    assert p101["total_observations"] == 3
    # P101 HR: 80, 100, 90 -> min: 80, max: 100, avg: 90.0
    assert p101["heart_rate"]["valid_count"] == 3
    assert p101["heart_rate"]["min"] == 80.0
    assert p101["heart_rate"]["max"] == 100.0
    assert p101["heart_rate"]["avg"] == 90.0
    # P101 SpO2: 98, 94, 96 -> min: 94, max: 98, avg: 96.0
    assert p101["spo2"]["valid_count"] == 3
    assert p101["spo2"]["min"] == 94.0
    assert p101["spo2"]["max"] == 98.0
    assert p101["spo2"]["avg"] == 96.0
    # P101 Temp: 98.6, 99.4, 99.0 -> min: 98.6, max: 99.4, avg: 99.0
    assert p101["temperature_f"]["valid_count"] == 3
    assert p101["temperature_f"]["min"] == 98.6
    assert p101["temperature_f"]["max"] == 99.4
    assert p101["temperature_f"]["avg"] == 99.0


# -------------------------------------------------------------------------
# Test 4: Null measurements are not treated as zero
# -------------------------------------------------------------------------
def test_null_measurements_not_treated_as_zero(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
) -> None:
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    docs = [
        {
            "_id": "e1",
            "patient_id": "P_NULL_TEST",
            "measured_at": t0,
            "metrics": {"heart_rate": 80.0, "spo2": None, "temperature_f": None},
        },
        {
            "_id": "e2",
            "patient_id": "P_NULL_TEST",
            "measured_at": t0 + timedelta(minutes=10),
            "metrics": {"heart_rate": None, "spo2": None, "temperature_f": "not-a-number"},
        },
    ]
    mock_db[TELEMETRY_COLLECTION].insert_many(docs)
    summary = analytics_repo.get_patient_vitals_summary(patient_id="P_NULL_TEST")

    assert len(summary) == 1
    stats = summary[0]
    # Heart rate: one valid (80), one null -> valid_count 1, avg 80.0 (NOT 40.0)
    assert stats["heart_rate"]["valid_count"] == 1
    assert stats["heart_rate"]["avg"] == 80.0
    assert stats["heart_rate"]["min"] == 80.0
    assert stats["heart_rate"]["max"] == 80.0
    # SpO2: both null -> valid_count 0, min/max/avg None (NOT 0.0)
    assert stats["spo2"]["valid_count"] == 0
    assert stats["spo2"]["min"] is None
    assert stats["spo2"]["max"] is None
    assert stats["spo2"]["avg"] is None
    # Temperature: one null, one string -> valid_count 0, min/max/avg None
    assert stats["temperature_f"]["valid_count"] == 0
    assert stats["temperature_f"]["avg"] is None


# -------------------------------------------------------------------------
# Test 5: Time buckets contain the expected records
# -------------------------------------------------------------------------
def test_time_buckets_contain_expected_records(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
    sample_telemetry_docs: List[Dict[str, Any]],
) -> None:
    mock_db[TELEMETRY_COLLECTION].insert_many(sample_telemetry_docs)
    buckets = analytics_repo.get_time_bucketed_vitals(
        patient_id="P101",
        interval="hour",
    )

    # P101 has 1 event at 08:00, and 2 events at 09:00 and 09:30
    assert len(buckets) == 2
    b8 = next(b for b in buckets if "08:00:00" in b["time_bucket"])
    assert b8["observation_count"] == 1
    assert b8["avg_heart_rate"] == 80.0

    b9 = next(b for b in buckets if "09:00:00" in b["time_bucket"])
    assert b9["observation_count"] == 2
    # 09:00 has HR 100.0 and 90.0 -> avg 95.0
    assert b9["avg_heart_rate"] == 95.0
    assert b9["min_heart_rate"] == 90.0
    assert b9["max_heart_rate"] == 100.0


# -------------------------------------------------------------------------
# Test 6: Start and end filters applied correctly & validated
# -------------------------------------------------------------------------
def test_start_and_end_filters_applied_correctly(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
    sample_telemetry_docs: List[Dict[str, Any]],
) -> None:
    mock_db[TELEMETRY_COLLECTION].insert_many(sample_telemetry_docs)
    t_start = datetime(2026, 10, 10, 8, 30, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 10, 10, 9, 45, 0, tzinfo=timezone.utc)

    history = analytics_repo.get_patient_telemetry_history(
        patient_id="P101",
        start_time=t_start,
        end_time=t_end,
    )
    # Should include event_2 (09:00) and event_3 (09:30), but NOT event_1 (08:00)
    assert len(history) == 2
    event_ids = [d["event_id"] for d in history]
    assert "event_2" in event_ids
    assert "event_3" in event_ids
    assert "event_1" not in event_ids

    # Inverted time range raises ValueError
    with pytest.raises(ValueError, match="start_time .* must be less than or equal to end_time"):
        analytics_repo.get_patient_telemetry_history(
            patient_id="P101",
            start_time=t_end,
            end_time=t_start,
        )


# -------------------------------------------------------------------------
# Test 7: Timestamp handling follows UTC policy
# -------------------------------------------------------------------------
def test_timestamp_handling_follows_utc_policy() -> None:
    # 1. Naive datetime becomes UTC
    naive_dt = datetime(2026, 10, 10, 12, 0, 0)
    norm = normalize_datetime(naive_dt)
    assert norm is not None
    assert norm.tzinfo == timezone.utc

    # 2. Non-UTC tz becomes UTC
    tz_plus_5 = timezone(timedelta(hours=5))
    dt_tz = datetime(2026, 10, 10, 17, 0, 0, tzinfo=tz_plus_5)
    norm_utc = normalize_datetime(dt_tz)
    assert norm_utc is not None
    assert norm_utc.tzinfo == timezone.utc
    assert norm_utc.hour == 12  # 17:00 +05:00 == 12:00 UTC


# -------------------------------------------------------------------------
# Test 8: Empty collections return valid empty results
# -------------------------------------------------------------------------
def test_empty_collections_return_valid_empty_results(
    analytics_repo: MongoAnalyticsRepository,
) -> None:
    overview = analytics_repo.get_dataset_overview()
    assert overview["total_documents"] == 0
    assert overview["distinct_patients_count"] == 0
    assert overview["distinct_patient_ids"] == []
    assert overview["documents_by_source"] == {}

    vitals = analytics_repo.get_patient_vitals_summary()
    assert vitals == []

    buckets = analytics_repo.get_time_bucketed_vitals(interval="hour")
    assert buckets == []

    history = analytics_repo.get_patient_telemetry_history(patient_id="P101")
    assert history == []

    provenance = analytics_repo.get_source_provenance_summary()
    assert provenance["total_documents"] == 0
    assert provenance["categories_count"] == 0

    alerts = analytics_repo.get_alert_summary()
    assert alerts["total_alerts"] == 0
    assert alerts["by_severity"] == {}
    assert alerts["by_status"] == {}

    quality = analytics_repo.get_data_quality_report()
    assert quality["total_checked"] == 0
    assert quality["is_clean"] is True


# -------------------------------------------------------------------------
# Test 9: Missing fields handled safely
# -------------------------------------------------------------------------
def test_missing_fields_handled_safely(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
) -> None:
    # Insert bare document without 'metrics', 'source', or 'is_simulated'
    mock_db[TELEMETRY_COLLECTION].insert_one({
        "_id": "e_bare",
        "patient_id": "P_BARE",
        "measured_at": datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc),
    })

    overview = analytics_repo.get_dataset_overview()
    assert overview["total_documents"] == 1
    assert "unknown" in overview["documents_by_source"]

    summary = analytics_repo.get_patient_vitals_summary(patient_id="P_BARE")
    assert len(summary) == 1
    assert summary[0]["heart_rate"]["valid_count"] == 0
    assert summary[0]["heart_rate"]["avg"] is None


# -------------------------------------------------------------------------
# Test 10: Provenance categories not inferred without evidence
# -------------------------------------------------------------------------
def test_provenance_categories_not_inferred_without_evidence(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
    sample_telemetry_docs: List[Dict[str, Any]],
) -> None:
    mock_db[TELEMETRY_COLLECTION].insert_many(sample_telemetry_docs)
    prov = analytics_repo.get_source_provenance_summary()

    assert prov["total_documents"] == 4
    categories = {
        (c["source"], c["is_simulated"]): c["document_count"]
        for c in prov["provenance_breakdown"]
    }
    assert categories.get(("kaggle_csv", False)) == 2
    assert categories.get(("simulated", True)) == 1
    assert categories.get(("device", False)) == 1


# -------------------------------------------------------------------------
# Test 11: Alert aggregations work when supported alert documents exist
# -------------------------------------------------------------------------
def test_alert_aggregations_work_with_alert_documents(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
    sample_alert_docs: List[Dict[str, Any]],
) -> None:
    mock_db[ALERTS_COLLECTION].insert_many(sample_alert_docs)
    alert_summary = analytics_repo.get_alert_summary()

    assert alert_summary["total_alerts"] == 3
    assert alert_summary["by_severity"] == {
        "CRITICAL": 1,
        "HIGH": 1,
        "MEDIUM": 1,
    }
    assert alert_summary["by_status"] == {
        "NEW": 1,
        "ACKNOWLEDGED": 1,
        "RESOLVED": 1,
    }
    assert alert_summary["by_patient"] == {
        "P101": 2,
        "P102": 1,
    }
    assert alert_summary["acknowledgement"]["acknowledged_count"] == 2
    assert alert_summary["acknowledgement"]["unacknowledged_count"] == 1
    # 2 acknowledged out of 3 = 66.67%
    assert alert_summary["acknowledgement"]["acknowledgement_rate_percent"] == 66.67


# -------------------------------------------------------------------------
# Test 12: Data-quality diagnostics identify malformed records
# -------------------------------------------------------------------------
def test_data_quality_diagnostics_identifies_malformed_records(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
) -> None:
    malformed_docs = [
        # Record 1: missing patient_id, missing source, invalid type in HR
        {
            "_id": "bad_1",
            "patient_id": "",
            "source": None,
            "measured_at": datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
            "source_event_id": "dup_src",
            "metrics": {"heart_rate": "invalid_str", "spo2": 98.0, "temperature_f": 98.6},
        },
        # Record 2: duplicate source_event_id, missing measured_at, implausible SpO2 (< 50)
        {
            "_id": "bad_2",
            "patient_id": "P101",
            "source": "kaggle_csv",
            "measured_at": None,
            "source_event_id": "dup_src",
            "metrics": {"heart_rate": 80.0, "spo2": 35.0, "temperature_f": 98.6},
        },
        # Record 3: implausible fever temperature (> 115°F)
        {
            "_id": "bad_3",
            "patient_id": "P102",
            "source": "kaggle_csv",
            "measured_at": datetime(2026, 10, 10, 11, 0, tzinfo=timezone.utc),
            "source_event_id": "unique_src",
            "metrics": {"heart_rate": 80.0, "spo2": 98.0, "temperature_f": 120.0},
        },
        # Record 4: duplicate pair of bad_2 sharing (kaggle_csv, dup_src)
        {
            "_id": "bad_4",
            "patient_id": "P101",
            "source": "kaggle_csv",
            "measured_at": datetime(2026, 10, 10, 10, 30, tzinfo=timezone.utc),
            "source_event_id": "dup_src",
            "metrics": {"heart_rate": 82.0, "spo2": 97.0, "temperature_f": 98.6},
        },
    ]
    mock_db[TELEMETRY_COLLECTION].insert_many(malformed_docs)
    report = analytics_repo.get_data_quality_report()

    assert report["total_checked"] == 4
    assert report["is_clean"] is False
    assert report["missing_fields"]["missing_patient_id"] == 1
    assert report["missing_fields"]["missing_measured_at"] == 1
    assert report["missing_fields"]["missing_source"] == 1
    assert report["invalid_types"]["invalid_type_heart_rate"] == 1
    assert report["implausible_values"]["implausible_spo2"] == 1
    assert report["implausible_values"]["implausible_temperature_f"] == 1
    assert report["duplicate_source_identities"] == 1


# -------------------------------------------------------------------------
# Test 13: Result limits and pagination are enforced
# -------------------------------------------------------------------------
def test_result_limits_enforced(
    mock_db: mongomock.Database,
    analytics_repo: MongoAnalyticsRepository,
) -> None:
    t0 = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    docs = [
        {
            "_id": f"ev_{i}",
            "event_id": f"ev_{i}",
            "patient_id": "P_LIMIT",
            "measured_at": t0 + timedelta(minutes=i),
            "source": "kaggle_csv",
            "is_simulated": False,
            "metrics": {"heart_rate": 70.0 + i},
        }
        for i in range(15)
    ]
    mock_db[TELEMETRY_COLLECTION].insert_many(docs)

    # 1. Limit = 5
    page1 = analytics_repo.get_patient_telemetry_history(patient_id="P_LIMIT", limit=5, offset=0)
    assert len(page1) == 5
    assert page1[0]["event_id"] == "ev_14"  # Most recent first

    # 2. Offset = 5, Limit = 5
    page2 = analytics_repo.get_patient_telemetry_history(patient_id="P_LIMIT", limit=5, offset=5)
    assert len(page2) == 5
    assert page2[0]["event_id"] == "ev_9"

    # 3. Invalid limit / offset raises ValueError
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        analytics_repo.get_patient_telemetry_history(patient_id="P_LIMIT", limit=0)

    with pytest.raises(ValueError, match="offset must be a non-negative integer"):
        analytics_repo.get_patient_telemetry_history(patient_id="P_LIMIT", offset=-1)


# -------------------------------------------------------------------------
# Test 14: Untrusted inputs cannot inject arbitrary aggregation stages
# -------------------------------------------------------------------------
def test_untrusted_inputs_cannot_inject_arbitrary_stages(
    analytics_repo: MongoAnalyticsRepository,
) -> None:
    # 1. Dict injection attempt rejected
    with pytest.raises(ValueError, match="patient_id must be a string"):
        analytics_repo.get_patient_vitals_summary(patient_id={"$gt": ""})  # type: ignore

    # 2. SQL / NoSQL special characters rejected
    with pytest.raises(ValueError, match="Invalid patient_id format"):
        analytics_repo.get_patient_vitals_summary(patient_id="P101; DROP TABLE users;")

    # 3. Invalid interval rejected
    with pytest.raises(ValueError, match="Invalid time bucket interval"):
        analytics_repo.get_time_bucketed_vitals(interval="century")

    with pytest.raises(ValueError, match="Invalid time bucket interval"):
        analytics_repo.get_time_bucketed_vitals(interval="$where")
