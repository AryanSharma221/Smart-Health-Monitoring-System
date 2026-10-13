"""
Reproducible SQL vs NoSQL Benchmark Harness.

Features:
- Configurable warm-up and measured iterations.
- Monotonic high-resolution timing (time.perf_counter_ns).
- Latency percentiles: median, mean, min, max, p95, stddev.
- Randomized/alternating database execution order to eliminate caching bias.
- Equivalence validation ("Correctness Before Speed").
- Safe credential-free artifact generation (JSON, CSV, Markdown).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import platform
import random
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmarks.workloads import BENCHMARK_WORKLOADS, BenchmarkWorkload
from database.mongodb.repositories.analytics_repository import MongoAnalyticsRepository
from database.mysql.repositories.analytics_repository import SqlAnalyticsRepository

logger = logging.getLogger(__name__)


@dataclass
class WorkloadTimingStats:
    """Statistical summary of query execution latencies in milliseconds."""

    iterations: int
    median_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float
    p95_ms: float
    stddev_ms: float
    raw_samples_ms: List[float] = field(default_factory=list)


def _compute_stats(samples_ms: List[float]) -> WorkloadTimingStats:
    """Compute standard statistical distribution metrics from raw latency samples."""
    if not samples_ms:
        return WorkloadTimingStats(
            iterations=0,
            median_ms=0.0,
            mean_ms=0.0,
            min_ms=0.0,
            max_ms=0.0,
            p95_ms=0.0,
            stddev_ms=0.0,
            raw_samples_ms=[],
        )

    sorted_samples = sorted(samples_ms)
    n = len(sorted_samples)
    med = statistics.median(sorted_samples)
    mean_val = statistics.mean(sorted_samples)
    min_val = min(sorted_samples)
    max_val = max(sorted_samples)
    stddev_val = statistics.stdev(sorted_samples) if n >= 2 else 0.0

    # 95th percentile index calculation
    p95_idx = min(int(math.ceil(0.95 * n)) - 1, n - 1)
    p95_val = sorted_samples[p95_idx]

    return WorkloadTimingStats(
        iterations=n,
        median_ms=round(med, 3),
        mean_ms=round(mean_val, 3),
        min_ms=round(min_val, 3),
        max_ms=round(max_val, 3),
        p95_ms=round(p95_val, 3),
        stddev_ms=round(stddev_val, 3),
        raw_samples_ms=[round(s, 3) for s in samples_ms],
    )


@dataclass
class WorkloadBenchmarkResult:
    """Comprehensive benchmark result for a single workload comparison."""

    workload_id: str
    name: str
    business_question: str
    equivalence_passed: bool
    equivalence_error: Optional[str]
    sql_stats: WorkloadTimingStats
    mongo_stats: WorkloadTimingStats
    sql_item_count: int
    mongo_item_count: int
    speed_ratio: Optional[float] = None  # sql_median / mongo_median (>1 means Mongo faster, <1 means SQL faster)
    query_plans: Dict[str, Any] = field(default_factory=dict)


class BenchmarkRunner:
    """Manages reproducible execution, timing, and reporting of database benchmarks."""

    def __init__(
        self,
        sql_repo: SqlAnalyticsRepository,
        mongo_repo: MongoAnalyticsRepository,
        warmup_iterations: int = 3,
        measured_iterations: int = 20,
        randomize_order: bool = True,
    ) -> None:
        self.sql_repo = sql_repo
        self.mongo_repo = mongo_repo
        self.warmup_iterations = max(0, warmup_iterations)
        self.measured_iterations = max(1, measured_iterations)
        self.randomize_order = randomize_order

    def run_workload(
        self,
        workload: BenchmarkWorkload,
        params: Optional[Dict[str, Any]] = None,
    ) -> WorkloadBenchmarkResult:
        """Execute a single benchmark workload across SQL and NoSQL engines."""
        logger.info("Executing benchmark for '%s' (%s)", workload.name, workload.workload_id)

        # 1. Warm-up executions (discarded from metrics)
        for _ in range(self.warmup_iterations):
            try:
                workload.execute_sql(self.sql_repo, params)
            except Exception as e:
                logger.debug("SQL warmup exception for %s: %s", workload.workload_id, e)
            try:
                workload.execute_mongo(self.mongo_repo, params)
            except Exception as e:
                logger.debug("Mongo warmup exception for %s: %s", workload.workload_id, e)

        # 2. Functional correctness check
        sql_final = None
        mongo_final = None
        eq_passed = False
        eq_error = None

        try:
            sql_final = workload.execute_sql(self.sql_repo, params)
            mongo_final = workload.execute_mongo(self.mongo_repo, params)
            eq_passed, eq_error = workload.check_equivalence(sql_final, mongo_final)
        except Exception as exc:
            eq_passed = False
            eq_error = f"Execution exception during equivalence check: {exc}"

        sql_item_count = len(sql_final) if isinstance(sql_final, list) else (1 if sql_final is not None else 0)
        mongo_item_count = len(mongo_final) if isinstance(mongo_final, list) else (1 if mongo_final is not None else 0)

        # 3. Measured sampling iterations
        sql_samples: List[float] = []
        mongo_samples: List[float] = []

        for i in range(self.measured_iterations):
            # Alternating or randomized execution order
            order = ["sql", "mongo"]
            if self.randomize_order and (i % 2 == 1 or random.random() > 0.5):
                order = ["mongo", "sql"]

            for engine in order:
                if engine == "sql":
                    t0 = time.perf_counter_ns()
                    try:
                        workload.execute_sql(self.sql_repo, params)
                        t1 = time.perf_counter_ns()
                        sql_samples.append((t1 - t0) / 1_000_000.0)
                    except Exception as exc:
                        logger.error("SQL measured iteration failed: %s", exc)
                else:
                    t0 = time.perf_counter_ns()
                    try:
                        workload.execute_mongo(self.mongo_repo, params)
                        t1 = time.perf_counter_ns()
                        mongo_samples.append((t1 - t0) / 1_000_000.0)
                    except Exception as exc:
                        logger.error("Mongo measured iteration failed: %s", exc)

        sql_stats = _compute_stats(sql_samples)
        mongo_stats = _compute_stats(mongo_samples)

        speed_ratio = None
        if sql_stats.median_ms > 0 and mongo_stats.median_ms > 0:
            speed_ratio = round(sql_stats.median_ms / mongo_stats.median_ms, 2)

        return WorkloadBenchmarkResult(
            workload_id=workload.workload_id,
            name=workload.name,
            business_question=workload.business_question,
            equivalence_passed=eq_passed,
            equivalence_error=eq_error,
            sql_stats=sql_stats,
            mongo_stats=mongo_stats,
            sql_item_count=sql_item_count,
            mongo_item_count=mongo_item_count,
            speed_ratio=speed_ratio,
        )

    def run_all(
        self,
        workloads: Optional[List[BenchmarkWorkload]] = None,
    ) -> Dict[str, Any]:
        """Execute full benchmark suite across all registered workloads."""
        target_workloads = workloads or BENCHMARK_WORKLOADS
        start_time = datetime.now(timezone.utc)

        results: List[WorkloadBenchmarkResult] = []
        for wl in target_workloads:
            res = self.run_workload(wl)
            results.append(res)

        end_time = datetime.now(timezone.utc)
        duration_sec = round((end_time - start_time).total_seconds(), 2)

        report = {
            "metadata": {
                "benchmark_run_id": f"bench_{int(start_time.timestamp())}",
                "timestamp_utc": start_time.isoformat(),
                "duration_seconds": duration_sec,
                "warmup_iterations": self.warmup_iterations,
                "measured_iterations": self.measured_iterations,
                "environment": {
                    "python_version": platform.python_version(),
                    "system_os": platform.system(),
                    "os_release": platform.release(),
                    "machine": platform.machine(),
                },
            },
            "summary": {
                "total_workloads": len(results),
                "equivalence_passed_count": sum(1 for r in results if r.equivalence_passed),
                "equivalence_failed_count": sum(1 for r in results if not r.equivalence_passed),
            },
            "workload_results": [asdict(r) for r in results],
        }
        return report


def export_benchmark_artifacts(
    report: Dict[str, Any],
    output_dir: Path,
) -> Dict[str, Path]:
    """
    Save benchmark outputs to JSON, CSV, and Markdown in dedicated directory.
    Guarantees no credentials or sensitive tokens are written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = report["metadata"]["benchmark_run_id"]

    # 1. JSON report
    json_path = output_dir / f"{run_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # 2. CSV samples
    csv_path = output_dir / f"{run_id}_samples.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["workload_id", "workload_name", "engine", "iteration", "latency_ms"])
        for wl in report["workload_results"]:
            w_id = wl["workload_id"]
            w_name = wl["name"]
            for idx, sample in enumerate(wl["sql_stats"]["raw_samples_ms"]):
                writer.writerow([w_id, w_name, "MySQL/SQL", idx + 1, sample])
            for idx, sample in enumerate(wl["mongo_stats"]["raw_samples_ms"]):
                writer.writerow([w_id, w_name, "MongoDB", idx + 1, sample])

    # 3. Markdown report
    md_path = output_dir / f"{run_id}_summary.md"
    md_content = generate_markdown_summary(report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return {
        "json": json_path,
        "csv": csv_path,
        "markdown": md_path,
    }


def generate_markdown_summary(report: Dict[str, Any]) -> str:
    """Format benchmark report into clean, publication-ready GitHub Flavored Markdown."""
    meta = report["metadata"]
    summary = report["summary"]
    lines = [
        "# SQL vs. NoSQL Performance Benchmark Summary",
        "",
        f"- **Run ID:** `{meta['benchmark_run_id']}`",
        f"- **Timestamp (UTC):** `{meta['timestamp_utc']}`",
        f"- **Environment:** Python {meta['environment']['python_version']} ({meta['environment']['system_os']} {meta['environment']['machine']})",
        f"- **Configuration:** {meta['warmup_iterations']} warm-up, {meta['measured_iterations']} measured iterations",
        f"- **Equivalence Status:** {summary['equivalence_passed_count']}/{summary['total_workloads']} Workloads Passed",
        "",
        "## Performance Comparison Table",
        "",
        "| Workload ID | Name | Equivalence | SQL Median (ms) | SQL p95 (ms) | Mongo Median (ms) | Mongo p95 (ms) | Speed Ratio (SQL/Mongo) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for wl in report["workload_results"]:
        status_badge = "[PASS]" if wl["equivalence_passed"] else "[FAIL]"
        sql_s = wl["sql_stats"]
        mongo_s = wl["mongo_stats"]
        ratio_str = f"{wl['speed_ratio']}x" if wl["speed_ratio"] else "N/A"
        lines.append(
            f"| **{wl['workload_id']}** | {wl['name']} | {status_badge} | "
            f"{sql_s['median_ms']:.2f} ms | {sql_s['p95_ms']:.2f} ms | "
            f"{mongo_s['median_ms']:.2f} ms | {mongo_s['p95_ms']:.2f} ms | {ratio_str} |"
        )

    lines.extend([
        "",
        "> [!NOTE]",
        "> Speed Ratio > 1.0 indicates MongoDB demonstrated lower latency; Speed Ratio < 1.0 indicates MySQL demonstrated lower latency.",
        "> In-memory SQLite and mongomock testing verifies execution logic and semantic parity, but does not substitute for live Atlas and MySQL InnoDB network benchmarking.",
    ])
    return "\n".join(lines)
