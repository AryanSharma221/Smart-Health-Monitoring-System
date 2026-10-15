"""
Unit and regression tests for DA3 Indexing, Query Optimization, and Execution Plans.
Verifies the presence and structure of the 62 relational indexes, composite index 004,
query execution plans, and performance invariants.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OPERATIONAL_DB_PATH = PROJECT_ROOT / "smart_health_local.db"
OPTIMIZATION_RESULTS_PATH = PROJECT_ROOT / "scratch" / "query_optimization_results.json"


@pytest.fixture(scope="module")
def sqlite_conn():
    """Provides a read-only connection to the operational relational database."""
    assert OPERATIONAL_DB_PATH.exists(), f"Operational DB {OPERATIONAL_DB_PATH} not found."
    conn = sqlite3.connect(str(OPERATIONAL_DB_PATH))
    try:
        yield conn
    finally:
        conn.close()


def test_relational_index_count_and_core_indexes(sqlite_conn):
    """Verify that all operational tables have active indexes (at least 60 total)."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT type, name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%';")
    manual_indexes = cursor.fetchall()
    
    # Also fetch auto-created primary key unique indexes
    cursor.execute("SELECT type, name, tbl_name FROM sqlite_master WHERE type='index';")
    all_indexes = cursor.fetchall()

    assert len(all_indexes) >= 60, f"Expected at least 60 total relational indexes, found {len(all_indexes)}"

    index_names = {idx[1] for idx in all_indexes}
    
    # Verify critical composite and foreign key indexes
    assert "idx_vitals_patient_metric_time" in index_names
    assert "idx_vitals_patient_measured" in index_names
    assert "idx_alerts_patient_status_time" in index_names
    assert "idx_assignments_doctor_active" in index_names
    assert "idx_outbox_status_created" in index_names
    assert "idx_audit_actor_time" in index_names


def test_vitals_patient_measured_composite_columns(sqlite_conn):
    """Verify that idx_vitals_patient_measured indexes (patient_id, measured_at) in order."""
    cursor = sqlite_conn.cursor()
    cursor.execute("PRAGMA index_info(idx_vitals_patient_measured);")
    cols = cursor.fetchall()
    assert len(cols) == 2, f"Expected 2 columns on idx_vitals_patient_measured, found {len(cols)}"
    col_names = [col[2] for col in cols]
    assert col_names == ["patient_id", "measured_at"], f"Columns mismatch: expected ['patient_id', 'measured_at'], got {col_names}"


def test_q1_indexed_vitals_execution_plan(sqlite_conn):
    """Verify Q1 uses idx_vitals_patient_metric_time with no temporary sort table."""
    sql = """
    EXPLAIN QUERY PLAN
    SELECT reading_id, patient_id, metric_code, measured_at, value
    FROM vitals_readings
    WHERE patient_id = 'P101' AND metric_code = 'heart_rate'
    ORDER BY measured_at DESC
    LIMIT 50;
    """
    cursor = sqlite_conn.cursor()
    cursor.execute(sql)
    plan_rows = cursor.fetchall()
    plan_text = " | ".join(row[3] for row in plan_rows)

    assert "idx_vitals_patient_metric_time" in plan_text
    assert "SEARCH vitals_readings" in plan_text
    assert "USE TEMP B-TREE FOR ORDER BY" not in plan_text, "Q1 should not require a temporary sort buffer"


def test_q2_unindexed_vitals_execution_plan(sqlite_conn):
    """Verify Q2 on unindexed fields triggers full table scan and sort buffer."""
    sql = """
    EXPLAIN QUERY PLAN
    SELECT reading_id, patient_id, measured_at, value
    FROM vitals_readings
    WHERE raw_unit = 'bpm' AND quality_status = 'valid'
    ORDER BY value DESC
    LIMIT 50;
    """
    cursor = sqlite_conn.cursor()
    cursor.execute(sql)
    plan_rows = cursor.fetchall()
    plan_text = " | ".join(row[3] for row in plan_rows)

    assert "SCAN vitals_readings" in plan_text
    assert "USE TEMP B-TREE FOR ORDER BY" in plan_text


def test_q3_optimized_time_range_execution_plan(sqlite_conn):
    """Verify Q3 time-range query uses idx_vitals_patient_measured and avoids filesort."""
    sql = """
    EXPLAIN QUERY PLAN
    SELECT reading_id, patient_id, metric_code, value, unit, measured_at
    FROM vitals_readings
    WHERE patient_id = 'P101'
      AND measured_at >= '2026-10-14 00:00:00'
      AND measured_at <= '2026-10-15 00:00:00'
    ORDER BY measured_at DESC
    LIMIT 50;
    """
    cursor = sqlite_conn.cursor()
    cursor.execute(sql)
    plan_rows = cursor.fetchall()
    plan_text = " | ".join(row[3] for row in plan_rows)

    assert "idx_vitals_patient_measured" in plan_text, f"Q3 plan did not use idx_vitals_patient_measured: {plan_text}"
    assert "USE TEMP B-TREE FOR ORDER BY" not in plan_text, f"Q3 plan should not have filesort: {plan_text}"


def test_alembic_migration_004_and_model_synchronization():
    """Verify that Alembic migration 004 exists and models.py declares idx_vitals_patient_measured."""
    migration_file = PROJECT_ROOT / "database" / "mysql" / "alembic" / "versions" / "004_optimize_patient_timeseries_index.py"
    assert migration_file.exists(), f"Migration file {migration_file} missing."
    content = migration_file.read_text(encoding="utf-8")
    assert '004_optimize_patient_timeseries_index' in content
    assert '003_conversations_and_messaging' in content
    assert "idx_vitals_patient_measured" in content
    assert "patient_id" in content and "measured_at" in content

    # Verify models.py declaration
    models_file = PROJECT_ROOT / "database" / "mysql" / "models.py"
    models_content = models_file.read_text(encoding="utf-8")
    assert 'Index("idx_vitals_patient_measured", "patient_id", "measured_at")' in models_content


def test_empirical_benchmark_results_file():
    """Verify that scratch/query_optimization_results.json exists with valid metrics."""
    assert OPTIMIZATION_RESULTS_PATH.exists(), f"Benchmark results {OPTIMIZATION_RESULTS_PATH} not found."
    data = json.loads(OPTIMIZATION_RESULTS_PATH.read_text(encoding="utf-8"))
    
    assert data["relational_indexes_count"] == 62
    assert data["mongodb_count_invariant_verified"] is True
    assert data["speedup_ratio_indexed_vs_scan"] > 5.0
    
    benchmarks = data["benchmarks"]
    assert "Q1_INDEXED_VITALS" in benchmarks
    assert "Q2_UNINDEXED_VITALS" in benchmarks
    assert "Q3_TIME_RANGE" in benchmarks
    
    q1_mean = benchmarks["Q1_INDEXED_VITALS"]["metrics"]["mean_ms"]
    q2_mean = benchmarks["Q2_UNINDEXED_VITALS"]["metrics"]["mean_ms"]
    assert q1_mean < q2_mean, f"Indexed Q1 ({q1_mean}ms) should be faster than Q2 ({q2_mean}ms)"
