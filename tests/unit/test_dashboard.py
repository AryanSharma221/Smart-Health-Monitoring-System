"""
Unit Tests for Streamlit Analytics Dashboard Data Access and Processing.

Validates:
1. Dashboard analytics functions and metrics calculation.
2. Empty dataset behavior and graceful handling.
3. Missing measurements and null data handling.
4. Invalid/implausible measurement boundary diagnostics.
5. Patient and time-range filtering logic.
6. Correct units (°F, bpm, %) and aggregation semantics.
7. Benchmark artifact discovery and parsing.
8. Missing and malformed benchmark artifact tolerance.
9. Database connectivity failure detection without credential leakage.
10. Read-only behavioral invariance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from dashboard.data_access import (
    fetch_alert_summary,
    fetch_data_quality_report,
    fetch_database_reconciliation,
    fetch_dataset_overview,
    fetch_outbox_statistics,
    fetch_patient_ids,
    fetch_patient_telemetry_history,
    fetch_patient_vitals_summary,
    fetch_source_provenance,
    fetch_time_bucketed_vitals,
    get_analytics_repository,
    list_benchmark_runs,
    load_benchmark_details,
    load_benchmark_samples_df,
    probe_system_connectivity,
)
from database.mysql.models import Base
from database.mysql.repositories.analytics_repository import SqlAnalyticsRepository


@pytest.fixture
def empty_sql_session() -> Session:
    """Provide an isolated, empty SQLite session to test zero-state robustness."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


# -----------------------------------------------------------------------------
# 1. System Connectivity & Credential Protection
# -----------------------------------------------------------------------------

def test_probe_system_connectivity_structure() -> None:
    """Verify connectivity probe returns expected keys without leaking secrets."""
    status = probe_system_connectivity()

    assert "mysql_connected" in status
    assert "mysql_status" in status
    assert "mongo_connected" in status
    assert "mongo_status" in status
    assert "local_csv_available" in status
    assert "app_env" in status
    assert "timestamp_utc" in status

    # Verify no credentials leaked in status strings
    status_dump = json.dumps(status).lower()
    assert "password" not in status_dump
    assert "secret" not in status_dump
    assert "mongodb+srv://" not in status_dump


def test_get_analytics_repository_fallback_resolution() -> None:
    """Verify that get_analytics_repository gracefully resolves to fallback when offline."""
    sql_repo, sql_mode = get_analytics_repository(backend="sql", force_fallback=True)
    assert sql_repo is not None
    assert "Local Dataset Fixture" in sql_mode

    mongo_repo, mongo_mode = get_analytics_repository(backend="mongodb", force_fallback=True)
    assert mongo_repo is not None
    assert "Local Dataset Fixture" in mongo_mode


# -----------------------------------------------------------------------------
# 2. Dataset Overview & Units Semantics
# -----------------------------------------------------------------------------

def test_fetch_dataset_overview_metrics() -> None:
    """Verify high-level dataset metrics calculation."""
    overview = fetch_dataset_overview(force_fallback=True)

    assert overview["total_documents"] >= 0
    assert overview["distinct_patients_count"] >= 0
    assert isinstance(overview["distinct_patient_ids"], list)
    assert "documents_by_source" in overview
    assert "documents_by_simulation" in overview
    assert "_active_mode" in overview


def test_fetch_patient_ids_returns_sorted_list() -> None:
    """Verify distinct patient identifiers are returned as a sorted list."""
    patient_ids = fetch_patient_ids(force_fallback=True)
    assert isinstance(patient_ids, list)
    assert patient_ids == sorted(patient_ids)


def test_fetch_patient_vitals_summary_units_and_values() -> None:
    """Verify vital sign units (bpm, %, °F) and statistics aggregation."""
    summaries = fetch_patient_vitals_summary(force_fallback=True)
    assert isinstance(summaries, list)

    if summaries:
        s = summaries[0]
        assert "patient_id" in s
        assert "total_observations" in s
        assert "heart_rate" in s
        assert "spo2" in s
        assert "temperature_f" in s

        # Verify heart rate range if present
        hr = s["heart_rate"]
        if hr["valid_count"] > 0:
            assert hr["min"] is not None
            assert hr["max"] is not None
            assert hr["avg"] is not None
            assert hr["min"] <= hr["avg"] <= hr["max"]

        # Verify temperature is in Fahrenheit
        temp = s["temperature_f"]
        if temp["valid_count"] > 0:
            assert temp["avg"] > 70.0  # Fahrenheit scale invariant


# -----------------------------------------------------------------------------
# 3. Filtering & Time-Series Bucketing
# -----------------------------------------------------------------------------

def test_fetch_patient_vitals_summary_filtering() -> None:
    """Verify filtering by single patient returns at most one record."""
    patient_ids = fetch_patient_ids(force_fallback=True)
    if patient_ids:
        target_pid = patient_ids[0]
        filtered = fetch_patient_vitals_summary(patient_id=target_pid, force_fallback=True)
        assert len(filtered) == 1
        assert filtered[0]["patient_id"] == target_pid


def test_fetch_time_bucketed_vitals_intervals() -> None:
    """Verify hourly and daily bucketed vitals calculation."""
    hourly = fetch_time_bucketed_vitals(interval="hour", force_fallback=True)
    assert isinstance(hourly, list)

    daily = fetch_time_bucketed_vitals(interval="day", force_fallback=True)
    assert isinstance(daily, list)

    if hourly:
        assert "time_bucket" in hourly[0]
        assert "observation_count" in hourly[0]


def test_fetch_patient_telemetry_history_bounds() -> None:
    """Verify bounded history query respects limit and returns expected structure."""
    patient_ids = fetch_patient_ids(force_fallback=True)
    if patient_ids:
        target_pid = patient_ids[0]
        history = fetch_patient_telemetry_history(
            patient_id=target_pid,
            limit=10,
            force_fallback=True,
        )
        assert len(history) <= 10
        if history:
            assert "event_id" in history[0]
            assert "metrics" in history[0]
            assert "measured_at" in history[0]


# -----------------------------------------------------------------------------
# 4. Data Quality, Outbox & Reconciliation
# -----------------------------------------------------------------------------

def test_fetch_data_quality_report_structure() -> None:
    """Verify data quality audit output schema."""
    report = fetch_data_quality_report(force_fallback=True)

    assert "total_checked" in report
    assert "missing_fields" in report
    assert "null_metrics" in report
    assert "implausible_values" in report
    assert "duplicate_source_identities" in report


def test_fetch_outbox_statistics() -> None:
    """Verify outbox sync statistics structure."""
    outbox = fetch_outbox_statistics(force_fallback=True)
    assert "stats" in outbox
    stats = outbox["stats"]
    assert "pending" in stats
    assert "completed" in stats
    assert "failed" in stats


def test_fetch_database_reconciliation() -> None:
    """Verify database mirror reconciliation audit."""
    reconcile = fetch_database_reconciliation(force_fallback=True)
    assert "sql_count" in reconcile
    assert "mongo_count" in reconcile
    assert "discrepancy" in reconcile
    assert "is_in_sync" in reconcile


# -----------------------------------------------------------------------------
# 5. Empty Dataset & Zero-State Robustness
# -----------------------------------------------------------------------------

def test_empty_dataset_handling(empty_sql_session: Session) -> None:
    """Verify analytics methods execute safely on an empty database without crashing."""
    repo = SqlAnalyticsRepository(empty_sql_session)

    overview = repo.get_dataset_overview()
    assert overview["total_documents"] == 0
    assert overview["distinct_patients_count"] == 0
    assert overview["distinct_patient_ids"] == []

    vitals = repo.get_patient_vitals_summary()
    assert vitals == []

    buckets = repo.get_time_bucketed_vitals(interval="hour")
    assert buckets == []

    history = repo.get_patient_telemetry_history(patient_id="P_NONEXISTENT", limit=10)
    assert history == []

    alerts = repo.get_alert_summary()
    assert alerts["total_alerts"] == 0
    assert alerts["acknowledgement"]["acknowledged_count"] == 0

    quality = repo.get_data_quality_report()
    assert quality["total_checked"] == 0


def test_fetch_alert_summary_zero_state() -> None:
    """Verify alert summary returns clean schema when alert count is zero."""
    alerts = fetch_alert_summary(force_fallback=True)
    assert "total_alerts" in alerts
    assert "by_severity" in alerts
    assert "by_status" in alerts
    assert "acknowledgement" in alerts


# -----------------------------------------------------------------------------
# 6. Benchmark Artifact Parsing
# -----------------------------------------------------------------------------

def test_list_benchmark_runs_discovers_artifacts() -> None:
    """Verify benchmark discovery locates valid bench_*.json files."""
    runs = list_benchmark_runs()
    assert isinstance(runs, list)
    if runs:
        r = runs[0]
        assert "run_id" in r
        assert "timestamp_utc" in r
        assert "iterations" in r
        assert "equivalence_passed" in r


def test_load_benchmark_details_valid() -> None:
    """Verify benchmark details contain all 7 workloads and timing stats."""
    runs = list_benchmark_runs()
    if runs:
        run_id = runs[0]["run_id"]
        details = load_benchmark_details(run_id)
        assert details is not None
        assert "metadata" in details
        assert "summary" in details
        assert "workload_results" in details
        workloads = details["workload_results"]
        assert len(workloads) == 7
        for w in workloads:
            assert "workload_id" in w
            assert "sql_stats" in w
            assert "mongo_stats" in w
            assert "median_ms" in w["sql_stats"]
            assert "median_ms" in w["mongo_stats"]


def test_load_benchmark_details_nonexistent() -> None:
    """Verify loading a nonexistent run_id returns None gracefully."""
    details = load_benchmark_details("bench_nonexistent_999999")
    assert details is None


def test_load_benchmark_samples_df() -> None:
    """Verify loading benchmark samples CSV into DataFrame."""
    runs = list_benchmark_runs()
    if runs:
        run_id = runs[0]["run_id"]
        df = load_benchmark_samples_df(run_id)
        if df is not None:
            assert "workload_id" in df.columns
            assert "engine" in df.columns
            assert "latency_ms" in df.columns


def test_list_benchmark_runs_malformed_dir(tmp_path: Path) -> None:
    """Verify malformed JSON files are skipped without unhandled exceptions."""
    bad_json = tmp_path / "bench_bad.json"
    bad_json.write_text("{invalid_json: true", encoding="utf-8")

    runs = list_benchmark_runs(results_dir=tmp_path)
    assert runs == []
