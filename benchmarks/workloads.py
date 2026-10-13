"""
SQL vs NoSQL Benchmark Workload Definitions.

Defines the 7 standard benchmark workloads mapping clinical questions to
equivalent MySQL relational queries and MongoDB Atlas aggregation pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from benchmarks.equivalence import validate_workload_equivalence
from database.mongodb.repositories.analytics_repository import MongoAnalyticsRepository
from database.mysql.repositories.analytics_repository import SqlAnalyticsRepository


@dataclass
class BenchmarkWorkload:
    """Encapsulates a semantically equivalent query comparison between SQL and NoSQL."""

    workload_id: str
    name: str
    business_question: str
    mysql_description: str
    mongo_description: str
    required_fields: List[str]
    applicable_indexes_sql: List[str]
    applicable_indexes_mongo: List[str]
    sql_runner: Callable[[SqlAnalyticsRepository, Dict[str, Any]], Any]
    mongo_runner: Callable[[MongoAnalyticsRepository, Dict[str, Any]], Any]
    default_params: Dict[str, Any] = field(default_factory=dict)

    def execute_sql(self, repo: SqlAnalyticsRepository, params: Optional[Dict[str, Any]] = None) -> Any:
        merged_params = {**self.default_params, **(params or {})}
        return self.sql_runner(repo, merged_params)

    def execute_mongo(self, repo: MongoAnalyticsRepository, params: Optional[Dict[str, Any]] = None) -> Any:
        merged_params = {**self.default_params, **(params or {})}
        return self.mongo_runner(repo, merged_params)

    def check_equivalence(self, sql_res: Any, mongo_res: Any, epsilon: float = 0.05) -> tuple[bool, Optional[str]]:
        return validate_workload_equivalence(self.workload_id, sql_res, mongo_res, epsilon=epsilon)


# -----------------------------------------------------------------------------
# Workload Runners
# -----------------------------------------------------------------------------

def _run_workload_a_sql(repo: SqlAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_dataset_overview()

def _run_workload_a_mongo(repo: MongoAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_dataset_overview()


def _run_workload_b_sql(repo: SqlAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_patient_vitals_summary(
        patient_id=params.get("patient_id"),
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
    )

def _run_workload_b_mongo(repo: MongoAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_patient_vitals_summary(
        patient_id=params.get("patient_id"),
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
    )


def _run_workload_c_sql(repo: SqlAnalyticsRepository, params: Dict[str, Any]) -> Any:
    # Bounded time window filtering across cohort
    patient_id = params.get("patient_id", "P101")
    return repo.get_patient_telemetry_history(
        patient_id=patient_id,
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
        limit=params.get("limit", 100),
    )

def _run_workload_c_mongo(repo: MongoAnalyticsRepository, params: Dict[str, Any]) -> Any:
    patient_id = params.get("patient_id", "P101")
    return repo.get_patient_telemetry_history(
        patient_id=patient_id,
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
        limit=params.get("limit", 100),
    )


def _run_workload_d_sql(repo: SqlAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_time_bucketed_vitals(
        patient_id=params.get("patient_id", "P101"),
        interval=params.get("interval", "hour"),
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
    )

def _run_workload_d_mongo(repo: MongoAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_time_bucketed_vitals(
        patient_id=params.get("patient_id", "P101"),
        interval=params.get("interval", "hour"),
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
    )


def _run_workload_e_sql(repo: SqlAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_patient_telemetry_history(
        patient_id=params.get("patient_id", "P101"),
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
    )

def _run_workload_e_mongo(repo: MongoAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_patient_telemetry_history(
        patient_id=params.get("patient_id", "P101"),
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
    )


def _run_workload_f_sql(repo: SqlAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_source_provenance_summary()

def _run_workload_f_mongo(repo: MongoAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_source_provenance_summary()


def _run_workload_g_sql(repo: SqlAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_alert_summary(
        patient_id=params.get("patient_id"),
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
    )

def _run_workload_g_mongo(repo: MongoAnalyticsRepository, params: Dict[str, Any]) -> Any:
    return repo.get_alert_summary(
        patient_id=params.get("patient_id"),
        start_time=params.get("start_time"),
        end_time=params.get("end_time"),
    )


# -----------------------------------------------------------------------------
# Canonical Benchmark Workload Registry
# -----------------------------------------------------------------------------

BENCHMARK_WORKLOADS: List[BenchmarkWorkload] = [
    BenchmarkWorkload(
        workload_id="workload_a",
        name="Dataset Overview",
        business_question="What is the total size, time boundary, patient cohort, and source distribution of our telemetry mirror?",
        mysql_description="SELECT COUNT(*), MIN(measured_at), MAX(measured_at), SUM(is_simulated) FROM ingestion_events; plus distinct patient count and source group.",
        mongo_description="$facet pipeline aggregating global counts, distinct patient IDs, and source breakdowns in a single round-trip.",
        required_fields=["event_id", "patient_id", "measured_at", "source", "is_simulated"],
        applicable_indexes_sql=["PRIMARY (event_id)", "idx_events_patient_measured (patient_id, measured_at)"],
        applicable_indexes_mongo=["idx_telemetry_measured_at", "idx_telemetry_source"],
        sql_runner=_run_workload_a_sql,
        mongo_runner=_run_workload_a_mongo,
    ),
    BenchmarkWorkload(
        workload_id="workload_b",
        name="Patient Vitals Summary",
        business_question="What are the baseline minimum, maximum, average, and observation counts for HR, SpO2, and Temp per patient?",
        mysql_description="GROUP BY patient_id across vitals_readings with conditional aggregation on metric_code.",
        mongo_description="$group on patient_id with $min, $max, $avg accumulators guarded by $isNumber.",
        required_fields=["patient_id", "metric_code", "value", "raw_value", "raw_unit"],
        applicable_indexes_sql=["idx_vitals_patient_metric_time (patient_id, metric_code, measured_at)"],
        applicable_indexes_mongo=["idx_telemetry_patient_measured (patient_id, measured_at DESC)"],
        sql_runner=_run_workload_b_sql,
        mongo_runner=_run_workload_b_mongo,
        default_params={"patient_id": "P101"},
    ),
    BenchmarkWorkload(
        workload_id="workload_c",
        name="Time-Window Filtering",
        business_question="Retrieve bounded chronological observation events for a patient within a specific monitoring window.",
        mysql_description="SELECT * FROM ingestion_events WHERE patient_id = :id AND measured_at BETWEEN :start AND :end ORDER BY measured_at DESC LIMIT 100.",
        mongo_description="$match on patient_id and measured_at range, sorted by measured_at DESC, limited to 100 documents.",
        required_fields=["patient_id", "measured_at", "event_id"],
        applicable_indexes_sql=["idx_events_patient_measured (patient_id, measured_at)"],
        applicable_indexes_mongo=["idx_telemetry_patient_measured (patient_id, measured_at DESC)"],
        sql_runner=_run_workload_c_sql,
        mongo_runner=_run_workload_c_mongo,
        default_params={
            "patient_id": "P101",
            "start_time": datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            "limit": 100,
        },
    ),
    BenchmarkWorkload(
        workload_id="workload_d",
        name="Time-Bucket Analytics",
        business_question="What are the hourly vital trends (observation volume, average HR, SpO2, Temp) for an acute monitoring patient?",
        mysql_description="DATE_FORMAT(measured_at, '%Y-%m-%d %H:00:00') GROUP BY time_bucket with joined vitals_readings aggregations.",
        mongo_description="$dateToString hourly format grouping with conditional numeric averages.",
        required_fields=["measured_at", "patient_id", "metrics.*"],
        applicable_indexes_sql=["idx_events_patient_measured", "idx_vitals_patient_metric_time"],
        applicable_indexes_mongo=["idx_telemetry_patient_measured (patient_id, measured_at DESC)"],
        sql_runner=_run_workload_d_sql,
        mongo_runner=_run_workload_d_mongo,
        default_params={"patient_id": "P101", "interval": "hour"},
    ),
    BenchmarkWorkload(
        workload_id="workload_e",
        name="Filtered Patient History",
        business_question="Fetch the most recent 50 chronological observations for an individual patient with deterministic pagination.",
        mysql_description="SELECT * FROM ingestion_events WHERE patient_id = :id ORDER BY measured_at DESC, event_id DESC LIMIT 50 OFFSET 0.",
        mongo_description="$match patient_id, $sort (measured_at: -1, event_id: -1), $limit 50.",
        required_fields=["patient_id", "measured_at", "event_id"],
        applicable_indexes_sql=["idx_events_patient_measured (patient_id, measured_at)"],
        applicable_indexes_mongo=["idx_telemetry_patient_measured (patient_id, measured_at DESC)"],
        sql_runner=_run_workload_e_sql,
        mongo_runner=_run_workload_e_mongo,
        default_params={"patient_id": "P101", "limit": 50, "offset": 0},
    ),
    BenchmarkWorkload(
        workload_id="workload_f",
        name="Source & Provenance Summary",
        business_question="How many telemetry records originate from historical Kaggle exports vs simulated test feeds?",
        mysql_description="SELECT source, is_simulated, COUNT(*), MIN(measured_at), MAX(measured_at) GROUP BY source, is_simulated.",
        mongo_description="$group by (source, is_simulated) calculating document counts and timestamp boundaries.",
        required_fields=["source", "is_simulated", "measured_at"],
        applicable_indexes_sql=["source", "is_simulated"],
        applicable_indexes_mongo=["idx_telemetry_source", "idx_telemetry_simulated"],
        sql_runner=_run_workload_f_sql,
        mongo_runner=_run_workload_f_mongo,
    ),
    BenchmarkWorkload(
        workload_id="workload_g",
        name="Clinical Alert Analytics",
        business_question="What is the distribution of clinical alerts by severity, lifecycle status, and acknowledgment performance?",
        mysql_description="Multi-query aggregation on alerts table grouping by severity, status, patient, and acknowledgement timestamps.",
        mongo_description="$facet pipeline on alert_events grouping by severity, status, patient, and acknowledgement metrics.",
        required_fields=["severity", "status", "patient_id", "acknowledged_at"],
        applicable_indexes_sql=["idx_alerts_status_severity", "idx_alerts_patient_created"],
        applicable_indexes_mongo=["idx_alerts_status_severity", "idx_alerts_patient_created"],
        sql_runner=_run_workload_g_sql,
        mongo_runner=_run_workload_g_mongo,
    ),
]
