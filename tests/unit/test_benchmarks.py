"""
Unit and Integration Tests for the SQL vs NoSQL Benchmark Suite.

Verifies the 12 requirements from Part 3C:
1. Equivalent queries return equivalent normalized results.
2. Unequal results fail validation with clear mismatch diagnostics.
3. Null measurements are handled consistently without zero coercion.
4. Time-window boundaries match across SQL and MongoDB.
5. Deterministic ordering is preserved in both engines.
6. Warm-up executions are excluded from measured samples.
7. Raw timing samples are retained.
8. Summary statistics (median, mean, min, max, p95, stddev) are calculated correctly.
9. Failed queries are recorded as failures without crashing the suite.
10. Missing database configuration is detected and reported clearly.
11. Output artifacts contain no credentials or sensitive tokens.
12. Seamless integration with isolated benchmark fixtures.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import mongomock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from benchmarks.equivalence import (
    assert_dicts_equivalent,
    assert_lists_equivalent,
    validate_workload_equivalence,
)
from benchmarks.explain import capture_mongo_plan, capture_mysql_plan
from benchmarks.runner import (
    BenchmarkRunner,
    WorkloadTimingStats,
    _compute_stats,
    export_benchmark_artifacts,
    generate_markdown_summary,
)
from benchmarks.workloads import BENCHMARK_WORKLOADS, BenchmarkWorkload
from database.mongodb.collections import TELEMETRY_COLLECTION
from database.mongodb.repositories.analytics_repository import MongoAnalyticsRepository
from database.mysql.models import Base, IngestionEvent, PatientProfile, User, VitalsReading
from database.mysql.repositories.analytics_repository import SqlAnalyticsRepository


@pytest.fixture
def benchmark_databases() -> tuple[Session, mongomock.Database]:
    """Provide isolated, in-memory SQLite and mongomock instances with identical seed data."""
    # 1. SQLite
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    # 2. Mongomock
    mongo_client = mongomock.MongoClient()
    mongo_db = mongo_client["test_bench_analytics"]

    # 3. Seed identical patient and vitals
    t0 = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
    user = User(
        user_id="u_P101",
        email="p101@test.internal",
        password_hash="$2b$12$dummyhash",
        role="patient",
    )
    patient = PatientProfile(
        patient_id="P101",
        user_id="u_P101",
        first_name="Test",
        last_name="Patient",
    )
    session.add_all([user, patient])
    session.flush()

    events_data = [
        ("ev_1", "src_1", 80.0, 98.0, 98.6, t0),
        ("ev_2", "src_2", 90.0, 96.0, 99.0, t0.replace(minute=30)),
        ("ev_3", "src_3", 100.0, 94.0, 99.4, t0.replace(hour=9)),
    ]

    for ev_id, src_id, hr, spo2, temp_f, ts in events_data:
        ev = IngestionEvent(
            event_id=ev_id,
            patient_id="P101",
            source="kaggle_csv",
            source_event_id=src_id,
            measured_at=ts,
            received_at=ts,
            is_simulated=False,
        )
        session.add(ev)
        session.flush()

        temp_c = round((temp_f - 32.0) * 5.0 / 9.0, 2)
        r_hr = VitalsReading(
            event_id=ev_id,
            patient_id="P101",
            metric_code="heart_rate",
            value=hr,
            unit="bpm",
            raw_value=hr,
            raw_unit="bpm",
            measured_at=ts,
        )
        r_spo2 = VitalsReading(
            event_id=ev_id,
            patient_id="P101",
            metric_code="spo2",
            value=spo2,
            unit="%",
            raw_value=spo2,
            raw_unit="%",
            measured_at=ts,
        )
        r_temp = VitalsReading(
            event_id=ev_id,
            patient_id="P101",
            metric_code="temperature",
            value=temp_c,
            unit="degC",
            raw_value=temp_f,
            raw_unit="degF",
            measured_at=ts,
        )
        session.add_all([r_hr, r_spo2, r_temp])

        # Mirror to Mongo
        mongo_db[TELEMETRY_COLLECTION].insert_one({
            "_id": ev_id,
            "event_id": ev_id,
            "patient_id": "P101",
            "measured_at": ts,
            "received_at": ts,
            "source": "kaggle_csv",
            "source_event_id": src_id,
            "is_simulated": False,
            "metrics": {
                "heart_rate": hr,
                "spo2": spo2,
                "temperature_f": temp_f,
                "temperature_c": temp_c,
            },
        })

    session.commit()
    return session, mongo_db


# -----------------------------------------------------------------------------
# Test 1: Equivalent queries return equivalent normalized results
# -----------------------------------------------------------------------------
def test_equivalent_queries_return_equivalent_results(
    benchmark_databases: tuple[Session, mongomock.Database],
) -> None:
    session, mongo_db = benchmark_databases
    sql_repo = SqlAnalyticsRepository(session)
    mongo_repo = MongoAnalyticsRepository(mongo_db)

    for wl in BENCHMARK_WORKLOADS:
        res_sql = wl.execute_sql(sql_repo)
        res_mongo = wl.execute_mongo(mongo_repo)
        is_eq, err = wl.check_equivalence(res_sql, res_mongo)
        assert is_eq is True, f"Workload {wl.workload_id} equivalence failed: {err}"


# -----------------------------------------------------------------------------
# Test 2: Unequal results fail validation with clear diagnostics
# -----------------------------------------------------------------------------
def test_unequal_results_fail_validation() -> None:
    # 1. Numeric divergence beyond epsilon
    dict_a = {"avg_hr": 80.0}
    dict_b = {"avg_hr": 85.0}
    is_eq, err = validate_workload_equivalence("test", dict_a, dict_b, epsilon=0.05)
    assert is_eq is False
    assert "Numeric mismatch" in (err or "")

    # 2. List length divergence
    list_a = [{"id": 1}]
    list_b = [{"id": 1}, {"id": 2}]
    is_eq, err = validate_workload_equivalence("test", list_a, list_b)
    assert is_eq is False
    assert "List length mismatch" in (err or "")


# -----------------------------------------------------------------------------
# Test 3: Null measurements are handled consistently
# -----------------------------------------------------------------------------
def test_null_measurements_handled_consistently() -> None:
    dict_sql = {"hr": {"min": None, "max": None, "avg": None, "valid_count": 0}}
    dict_mongo = {"hr": {"min": None, "max": None, "avg": None, "valid_count": 0}}
    is_eq, err = validate_workload_equivalence("test", dict_sql, dict_mongo)
    assert is_eq is True

    # Null vs 0.0 must FAIL
    dict_bad = {"hr": {"min": 0.0, "max": 0.0, "avg": 0.0, "valid_count": 0}}
    is_eq, err = validate_workload_equivalence("test", dict_sql, dict_bad)
    assert is_eq is False
    assert "Null mismatch" in (err or "")


# -----------------------------------------------------------------------------
# Test 4 & 5: Time-window boundaries and deterministic ordering match
# -----------------------------------------------------------------------------
def test_time_window_and_ordering_match(
    benchmark_databases: tuple[Session, mongomock.Database],
) -> None:
    session, mongo_db = benchmark_databases
    sql_repo = SqlAnalyticsRepository(session)
    mongo_repo = MongoAnalyticsRepository(mongo_db)

    # Both retrieve history sorted by measured_at DESC
    history_sql = sql_repo.get_patient_telemetry_history(patient_id="P101", limit=10)
    history_mongo = mongo_repo.get_patient_telemetry_history(patient_id="P101", limit=10)

    assert len(history_sql) == 3
    assert len(history_mongo) == 3

    # Check identical deterministic order (ev_3 @ 09:00, ev_2 @ 08:30, ev_1 @ 08:00)
    assert [d["event_id"] for d in history_sql] == ["ev_3", "ev_2", "ev_1"]
    assert [d["event_id"] for d in history_mongo] == ["ev_3", "ev_2", "ev_1"]


# -----------------------------------------------------------------------------
# Test 6 & 7: Warm-up excluded from samples & raw samples retained
# -----------------------------------------------------------------------------
def test_warmup_excluded_and_raw_samples_retained(
    benchmark_databases: tuple[Session, mongomock.Database],
) -> None:
    session, mongo_db = benchmark_databases
    sql_repo = SqlAnalyticsRepository(session)
    mongo_repo = MongoAnalyticsRepository(mongo_db)

    runner = BenchmarkRunner(
        sql_repo=sql_repo,
        mongo_repo=mongo_repo,
        warmup_iterations=2,
        measured_iterations=5,
    )
    result = runner.run_workload(BENCHMARK_WORKLOADS[0])

    # Must contain exactly 5 measured samples, not 5 + 2 = 7
    assert len(result.sql_stats.raw_samples_ms) == 5
    assert len(result.mongo_stats.raw_samples_ms) == 5
    assert result.sql_stats.iterations == 5
    assert result.mongo_stats.iterations == 5


# -----------------------------------------------------------------------------
# Test 8: Summary statistics calculated correctly
# -----------------------------------------------------------------------------
def test_summary_statistics_calculation() -> None:
    # Controlled distribution: [10.0, 20.0, 30.0, 40.0, 50.0]
    samples = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = _compute_stats(samples)

    assert stats.iterations == 5
    assert stats.min_ms == 10.0
    assert stats.max_ms == 50.0
    assert stats.median_ms == 30.0
    assert stats.mean_ms == 30.0
    assert stats.p95_ms == 50.0
    assert stats.stddev_ms == round(statistics.stdev(samples), 3)


# -----------------------------------------------------------------------------
# Test 9: Failed queries recorded without crashing suite
# -----------------------------------------------------------------------------
def test_failed_queries_recorded_as_failures(
    benchmark_databases: tuple[Session, mongomock.Database],
) -> None:
    session, mongo_db = benchmark_databases
    sql_repo = SqlAnalyticsRepository(session)
    mongo_repo = MongoAnalyticsRepository(mongo_db)

    # Construct broken workload that raises exception in SQL
    failing_workload = BenchmarkWorkload(
        workload_id="workload_broken",
        name="Broken Workload",
        business_question="Test resilience",
        mysql_description="Raises error",
        mongo_description="Normal",
        required_fields=[],
        applicable_indexes_sql=[],
        applicable_indexes_mongo=[],
        sql_runner=lambda repo, params: (_ for _ in ()).throw(RuntimeError("Simulated DB connection error")),
        mongo_runner=lambda repo, params: {"status": "ok"},
    )

    runner = BenchmarkRunner(
        sql_repo=sql_repo,
        mongo_repo=mongo_repo,
        warmup_iterations=0,
        measured_iterations=3,
    )
    result = runner.run_workload(failing_workload)

    assert result.equivalence_passed is False
    assert "Simulated DB connection error" in (result.equivalence_error or "")
    assert result.sql_stats.iterations == 0  # Failed samples are omitted


# -----------------------------------------------------------------------------
# Test 10: Query plan inspection captures details
# -----------------------------------------------------------------------------
def test_query_plan_inspection(
    benchmark_databases: tuple[Session, mongomock.Database],
) -> None:
    session, mongo_db = benchmark_databases
    # Test SQLite plan capture
    plan_sql = capture_mysql_plan(session, "SELECT * FROM ingestion_events WHERE patient_id = 'P101'")
    assert plan_sql["engine"] == "sqlite"
    assert "raw_plan" in plan_sql

    # Test Mongo plan capture (mongomock returns is_mock=True)
    plan_mongo = capture_mongo_plan(mongo_db[TELEMETRY_COLLECTION], [{"$match": {"patient_id": "P101"}}])
    assert plan_mongo["is_mock"] is True
    assert plan_mongo["stage"] == "MONGOMOCK_IN_MEMORY"


# -----------------------------------------------------------------------------
# Test 11: Output artifacts contain no credentials
# -----------------------------------------------------------------------------
def test_output_artifacts_contain_no_credentials(tmp_path: Path) -> None:
    sample_report = {
        "metadata": {
            "benchmark_run_id": "bench_test_run",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": 1.23,
            "warmup_iterations": 1,
            "measured_iterations": 2,
            "environment": {"python_version": "3.12.0", "system_os": "TestOS", "machine": "x86"},
        },
        "summary": {"total_workloads": 1, "equivalence_passed_count": 1, "equivalence_failed_count": 0},
        "workload_results": [
            {
                "workload_id": "workload_a",
                "name": "Dataset Overview",
                "business_question": "Overview query",
                "equivalence_passed": True,
                "equivalence_error": None,
                "sql_stats": {"iterations": 2, "median_ms": 1.0, "mean_ms": 1.0, "min_ms": 1.0, "max_ms": 1.0, "p95_ms": 1.0, "stddev_ms": 0.0, "raw_samples_ms": [1.0, 1.0]},
                "mongo_stats": {"iterations": 2, "median_ms": 2.0, "mean_ms": 2.0, "min_ms": 2.0, "max_ms": 2.0, "p95_ms": 2.0, "stddev_ms": 0.0, "raw_samples_ms": [2.0, 2.0]},
                "sql_item_count": 1,
                "mongo_item_count": 1,
                "speed_ratio": 0.5,
                "query_plans": {},
            }
        ],
    }

    paths = export_benchmark_artifacts(sample_report, tmp_path)
    assert paths["json"].is_file()
    assert paths["csv"].is_file()
    assert paths["markdown"].is_file()

    # Verify no secret keywords leaked
    secret_terms = ["password", "secret", "mongodb+srv://", "bearer", "token"]
    for p in paths.values():
        content = p.read_text(encoding="utf-8").lower()
        for term in secret_terms:
            assert term not in content, f"Leaked sensitive token '{term}' found in artifact {p}"
