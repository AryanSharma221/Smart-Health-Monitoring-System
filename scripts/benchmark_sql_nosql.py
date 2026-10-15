"""
Reproducible SQL and NoSQL Performance Benchmark.

Part 8D — Digital Assignment 3 (DA3) Reproducible Performance Evaluation.

Measures and compares representative read-only operations across:
1. Operational Relational Store (SQLite/MySQL with B-Tree indexes):
   - Q1: Patient latest vitals (Indexed covering search)
   - Q2: Unindexed filter & sort (Full table scan baseline)
   - Q3: Time-range bounded readings (Composite indexed range scan)
   - Q4: Clinical alert triage by patient & status
   - Q5: Multi-table relational join (Alerts + Patients + Doctor Assignments)
   - Q6: Statistical aggregation with GROUP BY & HAVING
   - Q7: Hourly time-window bucketing
2. MongoDB Atlas NoSQL Analytics Mirror (Strictly READ-ONLY):
   - M1: Patient telemetry retrieval (Indexed search via idx_telemetry_patient_measured)
   - M2: Telemetry filter on unindexed nested metric (Full collection scan COLLSCAN)
   - M3: Time-range bounded telemetry retrieval
   - M4: Statistical moments aggregation pipeline ($match -> $group)
   - M5: Provenance distribution aggregation pipeline ($group by source)

Safety Guarantees:
- Zero writes, updates, deletes, or schema changes to MongoDB Atlas.
- Asserts MongoDB telemetry_events document count is strictly invariant at 2,955.
- Sanitizes all connection strings and credentials via sanitize_mongo_uri.
- Configurable repetitions, warmup cycles, and graceful degradation if service unavailable.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from database.mongodb.client import get_mongo_database, sanitize_mongo_uri
from database.mongodb.collections import ALERTS_COLLECTION, TELEMETRY_COLLECTION
from services.api.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark_sql_nosql")

DB_FILE = WORKSPACE_ROOT / "smart_health_local.db"


def compute_distribution(times_ms: List[float]) -> Dict[str, float]:
    """Compute summary statistics for a sample of latency measurements in milliseconds."""
    if not times_ms:
        return {"count": 0, "min_ms": 0.0, "mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0, "stddev_ms": 0.0}
    
    sorted_times = sorted(times_ms)
    n = len(sorted_times)
    p95_idx = min(int(0.95 * n), n - 1)
    
    return {
        "count": n,
        "min_ms": round(sorted_times[0], 3),
        "mean_ms": round(statistics.mean(sorted_times), 3),
        "median_ms": round(statistics.median(sorted_times), 3),
        "p95_ms": round(sorted_times[p95_idx], 3),
        "max_ms": round(sorted_times[-1], 3),
        "stddev_ms": round(statistics.stdev(sorted_times), 3) if n > 1 else 0.0,
    }


def execute_relational_benchmarks(
    db_path: Path,
    iterations: int = 30,
    warmup: int = 5,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Execute canonical relational SQL read queries with EXPLAIN QUERY PLAN and latency timing."""
    if not db_path.exists():
        logger.error("Relational database not found at %s", db_path)
        return [], {"error": f"Database file not found: {db_path}"}

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    queries = [
        {
            "id": "SQL_Q1_LATEST_VITALS",
            "name": "Patient Latest Vitals (Indexed Search)",
            "sql": (
                "SELECT reading_id, patient_id, metric_code, measured_at, value\n"
                "FROM vitals_readings\n"
                "WHERE patient_id = 'P101' AND metric_code = 'heart_rate'\n"
                "ORDER BY measured_at DESC\n"
                "LIMIT 50;"
            ),
            "category": "indexed_lookup",
        },
        {
            "id": "SQL_Q2_UNINDEXED_SCAN",
            "name": "Unindexed Field Scan & Sorting (Full Table Scan)",
            "sql": (
                "SELECT reading_id, patient_id, measured_at, value\n"
                "FROM vitals_readings\n"
                "WHERE raw_unit = 'bpm' AND quality_status = 'valid'\n"
                "ORDER BY value DESC\n"
                "LIMIT 50;"
            ),
            "category": "full_table_scan",
        },
        {
            "id": "SQL_Q3_TIME_RANGE",
            "name": "Patient Time-Range Bounded Query (Indexed Range)",
            "sql": (
                "SELECT reading_id, patient_id, metric_code, value, unit, measured_at\n"
                "FROM vitals_readings\n"
                "WHERE patient_id = 'P101'\n"
                "  AND measured_at >= '2026-10-14 00:00:00'\n"
                "  AND measured_at <= '2026-10-15 00:00:00'\n"
                "ORDER BY measured_at DESC\n"
                "LIMIT 50;"
            ),
            "category": "indexed_range_scan",
        },
        {
            "id": "SQL_Q4_ALERT_TRIAGE",
            "name": "Clinical Alert Retrieval by Patient & Status",
            "sql": (
                "SELECT alert_id, patient_id, rule_id, severity, category, status, created_at\n"
                "FROM alerts\n"
                "WHERE patient_id = 'P101' AND status IN ('NEW', 'ACTIVE')\n"
                "ORDER BY created_at DESC\n"
                "LIMIT 25;"
            ),
            "category": "indexed_lookup",
        },
        {
            "id": "SQL_Q5_MULTI_JOIN",
            "name": "Multi-Table Relational Join (Alerts + Patients + Doctor Assignments)",
            "sql": (
                "SELECT a.alert_id, a.patient_id, p.first_name, p.last_name,\n"
                "       dp.first_name AS doctor_first_name, dp.last_name AS doctor_last_name,\n"
                "       a.severity, a.status, a.created_at\n"
                "FROM alerts a\n"
                "INNER JOIN patient_profiles p ON a.patient_id = p.patient_id\n"
                "LEFT JOIN doctor_patient_assignments dpa ON p.patient_id = dpa.patient_id AND dpa.is_active = 1\n"
                "LEFT JOIN doctor_profiles dp ON dpa.doctor_id = dp.doctor_id\n"
                "ORDER BY a.created_at DESC\n"
                "LIMIT 25;"
            ),
            "category": "multi_table_join",
        },
        {
            "id": "SQL_Q6_AGGREGATE_GROUP",
            "name": "Statistical Aggregation with GROUP BY and HAVING",
            "sql": (
                "SELECT patient_id,\n"
                "       COUNT(*) AS reading_count,\n"
                "       ROUND(AVG(value), 2) AS mean_hr,\n"
                "       ROUND(MIN(value), 2) AS min_hr,\n"
                "       ROUND(MAX(value), 2) AS max_hr\n"
                "FROM vitals_readings\n"
                "WHERE metric_code = 'heart_rate'\n"
                "GROUP BY patient_id\n"
                "HAVING COUNT(*) > 5\n"
                "ORDER BY mean_hr DESC;"
            ),
            "category": "aggregation",
        },
        {
            "id": "SQL_Q7_TIME_WINDOW_BUCKET",
            "name": "Time-Window Hourly Bucketing",
            "sql": (
                "SELECT strftime('%Y-%m-%d %H:00:00', measured_at) AS hour_bucket,\n"
                "       COUNT(*) AS count_in_bucket,\n"
                "       ROUND(AVG(value), 2) AS avg_value\n"
                "FROM vitals_readings\n"
                "WHERE patient_id = 'P101' AND metric_code = 'heart_rate'\n"
                "GROUP BY hour_bucket\n"
                "ORDER BY hour_bucket DESC\n"
                "LIMIT 24;"
            ),
            "category": "time_series_grouping",
        },
    ]

    benchmark_records = []
    for q in queries:
        # Get query plan
        cursor.execute(f"EXPLAIN QUERY PLAN {q['sql']}")
        plan_rows = cursor.fetchall()
        plan_str = " | ".join(r[3] for r in plan_rows)

        # Warm-up phase
        for _ in range(warmup):
            cursor.execute(q["sql"])
            cursor.fetchall()

        # Measure iterations
        latencies: List[float] = []
        rows_returned = 0
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            cursor.execute(q["sql"])
            res = cursor.fetchall()
            t1 = time.perf_counter_ns()
            latencies.append((t1 - t0) / 1_000_000.0)
            rows_returned = len(res)

        stats = compute_distribution(latencies)
        benchmark_records.append({
            "id": q["id"],
            "name": q["name"],
            "category": q["category"],
            "sql": q["sql"],
            "execution_plan": plan_str,
            "rows_returned": rows_returned,
            "metrics": stats,
        })
        logger.info("[RELATIONAL] %s: Mean=%.3f ms | p95=%.3f ms | Rows=%d", q["id"], stats["mean_ms"], stats["p95_ms"], rows_returned)

    conn.close()

    # Calculate index speedup ratio (Q1 indexed vs Q2 unindexed scan)
    q1_mean = benchmark_records[0]["metrics"]["mean_ms"]
    q2_mean = benchmark_records[1]["metrics"]["mean_ms"]
    speedup = round(q2_mean / q1_mean, 2) if q1_mean > 0 else 1.0

    metadata = {
        "engine": "sqlite_relational (MySQL InnoDB schema parity)",
        "database_file": str(db_path.name),
        "total_queries_benchmarked": len(benchmark_records),
        "iterations_per_query": iterations,
        "speedup_indexed_vs_scan": speedup,
    }

    return benchmark_records, metadata


def execute_mongodb_benchmarks(
    settings: Settings,
    iterations: int = 15,
    warmup: int = 3,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Execute canonical read-only MongoDB queries with executionStats and latency timing."""
    try:
        mongo_db = get_mongo_database(settings)
    except Exception as exc:
        logger.warning("MongoDB Atlas connection failed: %s", exc)
        return [], {"error": f"Connection failed: {exc}", "cluster": sanitize_mongo_uri(settings.mongodb_uri)}

    if mongo_db is None:
        return [], {"error": "MongoDB handle returned None"}

    telem_col = mongo_db[TELEMETRY_COLLECTION]

    # Pre-audit invariant check
    count_before = telem_col.count_documents({})
    if count_before != 2955:
        logger.error("MongoDB Atlas count invariant mismatch: expected 2955, got %d", count_before)
        return [], {"error": f"Count invariant mismatch: {count_before}"}

    mongo_workloads = [
        {
            "id": "MONGO_M1_INDEXED_VITALS",
            "name": "Patient Telemetry Retrieval (Indexed via idx_telemetry_patient_measured)",
            "type": "find",
            "query": {"patient_id": "P101"},
            "sort": [("measured_at", -1)],
            "limit": 20,
            "category": "indexed_lookup",
        },
        {
            "id": "MONGO_M2_UNINDEXED_METRIC",
            "name": "Telemetry Filter on Unindexed Metric (Full Collection Scan COLLSCAN)",
            "type": "find",
            "query": {"metrics.heart_rate": {"$gt": 90.0}},
            "sort": None,
            "limit": 20,
            "category": "collection_scan",
        },
        {
            "id": "MONGO_M3_TIME_RANGE",
            "name": "Time-Bounded Telemetry Retrieval",
            "type": "find",
            "query": {
                "patient_id": "P101",
                "measured_at": {
                    "$gte": datetime(2023, 1, 1, tzinfo=timezone.utc),
                    "$lte": datetime(2027, 1, 1, tzinfo=timezone.utc),
                },
            },
            "sort": [("measured_at", -1)],
            "limit": 20,
            "category": "indexed_range_scan",
        },
        {
            "id": "MONGO_M4_AGGREGATION_SUMMARY",
            "name": "Statistical Moments Aggregation ($match -> $group)",
            "type": "aggregate",
            "pipeline": [
                {"$match": {"patient_id": "P101"}},
                {
                    "$group": {
                        "_id": "$patient_id",
                        "avg_hr": {"$avg": "$metrics.heart_rate"},
                        "min_hr": {"$min": "$metrics.heart_rate"},
                        "max_hr": {"$max": "$metrics.heart_rate"},
                        "count": {"$sum": 1},
                    }
                },
            ],
            "category": "aggregation",
        },
        {
            "id": "MONGO_M5_AGGREGATION_PROVENANCE",
            "name": "Provenance Breakdown Aggregation ($group by source)",
            "type": "aggregate",
            "pipeline": [
                {"$group": {"_id": "$source", "count": {"$sum": 1}}},
            ],
            "category": "aggregation",
        },
    ]

    benchmark_records = []

    for w in mongo_workloads:
        # 1. Obtain explain plan where supported
        plan_summary = "N/A"
        execution_stats: Dict[str, Any] = {}
        if w["type"] == "find":
            try:
                cursor_exp = telem_col.find(w["query"])
                if w.get("sort"):
                    cursor_exp = cursor_exp.sort(w["sort"])
                if w.get("limit"):
                    cursor_exp = cursor_exp.limit(w["limit"])
                exp_dict = cursor_exp.explain()
                winning = exp_dict.get("queryPlanner", {}).get("winningPlan", {})
                plan_summary = f"Stage: {winning.get('stage')}"
                if winning.get("inputStage"):
                    input_st = winning.get("inputStage", {})
                    plan_summary += f" -> {input_st.get('stage')}"
                    if input_st.get("indexName"):
                        plan_summary += f" ({input_st.get('indexName')})"
                
                stats_raw = exp_dict.get("executionStats", {})
                execution_stats = {
                    "totalKeysExamined": stats_raw.get("totalKeysExamined"),
                    "totalDocsExamined": stats_raw.get("totalDocsExamined"),
                    "executionTimeMillis": stats_raw.get("executionTimeMillis"),
                }
            except Exception as exc:
                plan_summary = f"explain() error: {exc}"
        else:
            plan_summary = "Pipeline ($match -> $group) executed in-engine; Atlas M0 sandbox blocks direct command explain"

        # 2. Warm-up
        for _ in range(warmup):
            try:
                if w["type"] == "find":
                    cur = telem_col.find(w["query"])
                    if w.get("sort"):
                        cur = cur.sort(w["sort"])
                    if w.get("limit"):
                        cur = cur.limit(w["limit"])
                    list(cur)
                else:
                    list(telem_col.aggregate(w["pipeline"]))
            except Exception:
                pass

        # 3. Benchmark iterations
        latencies: List[float] = []
        docs_returned = 0
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            if w["type"] == "find":
                cur = telem_col.find(w["query"])
                if w.get("sort"):
                    cur = cur.sort(w["sort"])
                if w.get("limit"):
                    cur = cur.limit(w["limit"])
                res = list(cur)
            else:
                res = list(telem_col.aggregate(w["pipeline"]))
            t1 = time.perf_counter_ns()
            latencies.append((t1 - t0) / 1_000_000.0)
            docs_returned = len(res)

        stats = compute_distribution(latencies)
        benchmark_records.append({
            "id": w["id"],
            "name": w["name"],
            "category": w["category"],
            "plan_summary": plan_summary,
            "execution_stats": execution_stats,
            "docs_returned": docs_returned,
            "metrics": stats,
        })
        logger.info("[MONGODB ATLAS] %s: Mean=%.3f ms | p95=%.3f ms | Docs=%d", w["id"], stats["mean_ms"], stats["p95_ms"], docs_returned)

    # Post-benchmark invariant check
    count_after = telem_col.count_documents({})
    assert count_after == 2955, f"CRITICAL: Count altered from 2955 to {count_after}!"

    metadata = {
        "engine": "mongodb_atlas_v8.0.34",
        "cluster": sanitize_mongo_uri(settings.mongodb_uri),
        "collection": TELEMETRY_COLLECTION,
        "count_invariant_verified": count_before == count_after == 2955,
        "total_queries_benchmarked": len(benchmark_records),
        "iterations_per_query": iterations,
    }

    return benchmark_records, metadata


def run_benchmark_suite(
    iterations: int = 30,
    mongo_iterations: int = 15,
) -> Dict[str, Any]:
    """Execute both SQL and NoSQL benchmark suites and return structured evidence dictionary."""
    settings = get_settings()
    now_utc = datetime.now(timezone.utc).isoformat()

    logger.info("Starting Reproducible Performance Benchmark Suite at %s", now_utc)

    sql_results, sql_meta = execute_relational_benchmarks(
        db_path=DB_FILE,
        iterations=iterations,
    )

    mongo_results, mongo_meta = execute_mongodb_benchmarks(
        settings=settings,
        iterations=mongo_iterations,
    )

    result_payload = {
        "benchmark_timestamp_utc": now_utc,
        "settings": {
            "app_env": settings.app_env,
            "database_url": settings.database_url,
            "mongodb_endpoint": sanitize_mongo_uri(settings.mongodb_uri),
            "mongodb_sync_enabled": settings.mongodb_sync_enabled,
        },
        "relational_benchmarks": {
            "metadata": sql_meta,
            "queries": sql_results,
        },
        "mongodb_benchmarks": {
            "metadata": mongo_meta,
            "queries": mongo_results,
        },
    }

    output_path = WORKSPACE_ROOT / "scratch/benchmark_sql_nosql_evidence.json"
    output_path.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
    logger.info("Saved structured performance evidence to %s", output_path)

    return result_payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reproducible SQL and NoSQL Performance Benchmark")
    parser.add_argument("--iterations", type=int, default=30, help="Number of repetitions for relational queries")
    parser.add_argument("--mongo-iterations", type=int, default=15, help="Number of repetitions for MongoDB Atlas queries")
    args = parser.parse_args()

    run_benchmark_suite(
        iterations=args.iterations,
        mongo_iterations=args.mongo_iterations,
    )
