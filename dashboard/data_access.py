"""
Read-Only Data Access Layer for the Streamlit Analytics Dashboard.

Encapsulates data retrieval, database connectivity checks, fallback fixture
management, and benchmark artifact parsing.

Security and Safety Rules:
- Strictly read-only operations (no INSERT, UPDATE, DELETE).
- Credentials and connection strings are masked or omitted.
- Transparent reporting of database connectivity states (live vs. offline).
- Deterministic fallback to isolated Kaggle dataset fixture when live databases are offline.
"""

from __future__ import annotations

import csv
import json
import logging
import socket
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from benchmarks.run_benchmarks import setup_benchmark_fixture
from database.mongodb.client import check_mongo_connectivity, get_mongo_database
from database.mongodb.repositories.analytics_repository import MongoAnalyticsRepository
from database.mysql.repositories.analytics_repository import SqlAnalyticsRepository
from database.mysql.repositories.outbox_repository import OutboxRepository
from database.mysql.session import check_db_connectivity, get_session_factory
from services.api.config import get_settings

logger = logging.getLogger(__name__)

# Cached fallback fixture singleton for offline/coursework exploration
_FALLBACK_SQL_SESSION: Optional[Session] = None
_FALLBACK_MONGO_DB: Any = None
_BENCHMARK_RESULTS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "results"


def get_fallback_fixture() -> Tuple[Session, Any]:
    """
    Retrieve or initialize the isolated local fixture seeded with the verified Kaggle dataset.
    Ensures the dashboard functions reliably in offline or demonstration environments.
    """
    global _FALLBACK_SQL_SESSION, _FALLBACK_MONGO_DB
    if _FALLBACK_SQL_SESSION is None or _FALLBACK_MONGO_DB is None:
        logger.info("Initializing isolated local analytics dataset fixture...")
        _FALLBACK_SQL_SESSION, _FALLBACK_MONGO_DB = setup_benchmark_fixture()
    return _FALLBACK_SQL_SESSION, _FALLBACK_MONGO_DB


def probe_system_connectivity() -> Dict[str, Any]:
    """
    Probe live infrastructure, database, REST gateway, and WebSocket connectivity
    without leaking credentials or internal secrets.
    """
    settings = get_settings()

    # 1. MySQL Connectivity (Authoritative Store)
    mysql_ok = False
    mysql_msg = "Offline / Connection refused"
    try:
        mysql_ok = check_db_connectivity()
        if mysql_ok:
            mysql_msg = "Connected"
    except Exception as exc:
        mysql_msg = f"Offline ({type(exc).__name__})"

    # 2. MongoDB Connectivity (Analytics Mirror)
    mongo_ok = False
    mongo_msg = "Not configured"
    try:
        is_conn, status_desc = check_mongo_connectivity(settings)
        mongo_ok = is_conn
        mongo_msg = status_desc
    except Exception as exc:
        mongo_msg = f"Offline ({type(exc).__name__})"

    # 3. REST API Gateway Probe (FastAPI)
    api_ok = False
    api_msg = "Offline / Connection refused"
    api_latency_ms: Optional[float] = None
    target_api_url = f"http://localhost:{settings.api_port}{settings.api_v1_prefix}"
    probe_url = f"http://127.0.0.1:{settings.api_port}{settings.api_v1_prefix}/health"
    try:
        t_start = time.perf_counter()
        req = urllib.request.Request(probe_url, headers={"User-Agent": "SmartHealth-Dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as res:
            if res.status == 200:
                api_latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
                api_ok = True
                api_msg = f"HTTP 200 OK ({api_latency_ms}ms)"
            else:
                api_msg = f"HTTP {res.status}"
    except Exception as exc:
        api_msg = f"Offline ({type(exc).__name__})"

    # 4. WebSocket Stream Probe
    ws_ok = False
    ws_msg = "Disconnected"
    target_ws_url = f"ws://localhost:{settings.api_port}/ws/v1/updates"
    try:
        # Check TCP availability on the gateway port
        probe_sock = socket.create_connection(("127.0.0.1", settings.api_port), timeout=1.5)
        probe_sock.close()
        ws_ok = True
        ws_msg = "Listening / Ticket Auth Required"
    except Exception as exc:
        ws_msg = f"Offline ({type(exc).__name__})"

    # 5. Smartwatch Sensor Simulator Ingestion Probe
    sim_ok = False
    sim_msg = "Disabled"
    sim_url = f"http://127.0.0.1:{settings.api_port}{settings.api_v1_prefix}/simulator/ingestion-status"
    sim_details: Dict[str, Any] = {}
    try:
        req = urllib.request.Request(sim_url, headers={"User-Agent": "SmartHealth-Dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as res:
            if res.status == 200:
                sim_data = json.loads(res.read().decode())
                sim_details = sim_data
                if sim_data.get("enabled"):
                    if sim_data.get("last_poll_succeeded"):
                        sim_ok = True
                        sim_msg = f"Ingesting ({sim_data.get('events_accepted_count', 0)} events)"
                    else:
                        sim_ok = False
                        sim_msg = f"Degraded ({sim_data.get('last_error_category', 'offline')})"
                else:
                    sim_ok = False
                    sim_msg = "Disabled by Config"
    except Exception:
        sim_msg = "Offline / Unreachable"

    # 6. Kaggle CSV availability
    kaggle_csv_path = Path(settings.kaggle_dataset_path)
    csv_available = kaggle_csv_path.is_file()

    return {
        "mysql_connected": mysql_ok,
        "mysql_status": mysql_msg,
        "mongo_connected": mongo_ok,
        "mongo_status": mongo_msg,
        "api_connected": api_ok,
        "api_status": api_msg,
        "api_url": target_api_url,
        "api_latency_ms": api_latency_ms,
        "ws_connected": ws_ok,
        "ws_status": ws_msg,
        "ws_url": target_ws_url,
        "sim_connected": sim_ok,
        "sim_status": sim_msg,
        "sim_details": sim_details,
        "local_csv_available": csv_available,
        "local_csv_path": str(kaggle_csv_path),
        "app_env": settings.app_env,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def get_analytics_repository(
    backend: str = "sql",
    force_fallback: bool = False,
) -> Tuple[Union[SqlAnalyticsRepository, MongoAnalyticsRepository], str]:
    """
    Obtain a repository instance (SQL or MongoDB) based on requested backend and live status.
    Returns (repository_instance, active_mode_description).
    """
    connectivity = probe_system_connectivity()

    if backend.lower() == "mongodb":
        if connectivity["mongo_connected"] and not force_fallback:
            mongo_db = get_mongo_database()
            if mongo_db is not None:
                return MongoAnalyticsRepository(mongo_db), "Live MongoDB Atlas"
        # Fallback to local mongomock fixture
        _, mock_db = get_fallback_fixture()
        return MongoAnalyticsRepository(mock_db), "Local Dataset Fixture (Mongo Engine)"

    # Default to SQL backend
    if connectivity["mysql_connected"] and not force_fallback:
        session_factory = get_session_factory()
        session = session_factory()
        return SqlAnalyticsRepository(session), "Live MySQL 8 (InnoDB)"

    # Fallback to local SQLite fixture
    fallback_session, _ = get_fallback_fixture()
    return SqlAnalyticsRepository(fallback_session), "Local Dataset Fixture (SQL Engine)"


# -----------------------------------------------------------------------------
# Analytics Query Functions
# -----------------------------------------------------------------------------

def fetch_dataset_overview(
    backend: str = "sql",
    force_fallback: bool = False,
) -> Dict[str, Any]:
    """Retrieve high-level population and document counts."""
    repo, mode_desc = get_analytics_repository(backend, force_fallback)
    overview = repo.get_dataset_overview()
    overview["_active_mode"] = mode_desc
    overview["_backend"] = backend
    return overview


def fetch_patient_ids(
    backend: str = "sql",
    force_fallback: bool = False,
) -> List[str]:
    """Retrieve distinct list of patient IDs."""
    overview = fetch_dataset_overview(backend=backend, force_fallback=force_fallback)
    return sorted(overview.get("distinct_patient_ids", []))


def fetch_patient_vitals_summary(
    patient_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    backend: str = "sql",
    force_fallback: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve summary vital statistics per patient."""
    repo, _ = get_analytics_repository(backend, force_fallback)
    return repo.get_patient_vitals_summary(
        patient_id=patient_id,
        start_time=start_time,
        end_time=end_time,
    )


def fetch_time_bucketed_vitals(
    patient_id: Optional[str] = None,
    interval: str = "hour",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    backend: str = "sql",
    force_fallback: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve time-aggregated chronological observation metrics."""
    repo, _ = get_analytics_repository(backend, force_fallback)
    return repo.get_time_bucketed_vitals(
        patient_id=patient_id,
        interval=interval,
        start_time=start_time,
        end_time=end_time,
    )


def fetch_patient_telemetry_history(
    patient_id: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
    backend: str = "sql",
    force_fallback: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve bounded raw telemetry records for a patient."""
    repo, _ = get_analytics_repository(backend, force_fallback)
    return repo.get_patient_telemetry_history(
        patient_id=patient_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )


def fetch_source_provenance(
    backend: str = "sql",
    force_fallback: bool = False,
) -> Dict[str, Any]:
    """Retrieve source distribution and simulation breakdown."""
    repo, _ = get_analytics_repository(backend, force_fallback)
    return repo.get_source_provenance_summary()


def fetch_alert_summary(
    patient_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    backend: str = "sql",
    force_fallback: bool = False,
) -> Dict[str, Any]:
    """Retrieve clinical alert distributions and lifecycle metrics."""
    repo, _ = get_analytics_repository(backend, force_fallback)
    return repo.get_alert_summary(
        patient_id=patient_id,
        start_time=start_time,
        end_time=end_time,
    )


def fetch_data_quality_report(
    backend: str = "sql",
    force_fallback: bool = False,
) -> Dict[str, Any]:
    """Retrieve telemetry data quality diagnostics."""
    repo, _ = get_analytics_repository(backend, force_fallback)
    return repo.get_data_quality_report()


def fetch_outbox_statistics(force_fallback: bool = False) -> Dict[str, Any]:
    """
    Retrieve transactional outbox processing stats for analytics synchronization.
    """
    connectivity = probe_system_connectivity()
    if connectivity["mysql_connected"] and not force_fallback:
        session = get_session_factory()()
        try:
            outbox_repo = OutboxRepository(session)
            stats = outbox_repo.get_outbox_stats()
            failed_entries = outbox_repo.list_failed_entries(limit=10)
            return {
                "stats": stats,
                "failed_count": len(failed_entries),
                "is_live": True,
            }
        finally:
            session.close()

    # Fallback mode
    return {
        "stats": {"pending": 0, "processing": 0, "completed": 1500, "failed": 0},
        "failed_count": 0,
        "is_live": False,
        "note": "Transactional outbox status reflects synchronous mirror in local dataset fixture.",
    }


def fetch_database_reconciliation(force_fallback: bool = False) -> Dict[str, Any]:
    """
    Compare document populations between MySQL and MongoDB to assess mirror synchronization parity.
    """
    try:
        sql_repo, sql_mode = get_analytics_repository("sql", force_fallback)
        mongo_repo, mongo_mode = get_analytics_repository("mongodb", force_fallback)

        sql_ov = sql_repo.get_dataset_overview()
        mongo_ov = mongo_repo.get_dataset_overview()

        sql_count = sql_ov.get("total_documents", 0)
        mongo_count = mongo_ov.get("total_documents", 0)
        discrepancy = abs(sql_count - mongo_count)

        return {
            "sql_count": sql_count,
            "sql_mode": sql_mode,
            "mongo_count": mongo_count,
            "mongo_mode": mongo_mode,
            "discrepancy": discrepancy,
            "is_in_sync": discrepancy == 0,
            "sql_patients": sql_ov.get("distinct_patients_count", 0),
            "mongo_patients": mongo_ov.get("distinct_patients_count", 0),
        }
    except Exception as exc:
        logger.warning("Reconciliation audit failed: %s", exc)
        return {
            "error": f"Reconciliation unavailable: {str(exc)}",
            "is_in_sync": False,
        }


# -----------------------------------------------------------------------------
# Benchmark Artifact Parsing
# -----------------------------------------------------------------------------

def list_benchmark_runs(results_dir: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """
    Scan the benchmark results directory for valid bench_*.json artifacts.
    Returns list of metadata summaries sorted with newest first.
    """
    target_dir = Path(results_dir) if results_dir else _BENCHMARK_RESULTS_DIR
    if not target_dir.is_dir():
        return []

    runs: List[Dict[str, Any]] = []
    for json_file in target_dir.glob("bench_*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("metadata", {})
            summary = data.get("summary", {})
            runs.append({
                "run_id": meta.get("benchmark_run_id", json_file.stem),
                "timestamp_utc": meta.get("timestamp_utc", ""),
                "duration_seconds": meta.get("duration_seconds", 0.0),
                "iterations": meta.get("measured_iterations", 0),
                "total_workloads": summary.get("total_workloads", 0),
                "equivalence_passed": summary.get("equivalence_passed_count", 0),
                "file_path": str(json_file),
                "mtime": json_file.stat().st_mtime,
            })
        except Exception as exc:
            logger.warning("Skipping malformed benchmark artifact %s: %s", json_file.name, exc)

    runs.sort(key=lambda r: r.get("mtime", 0.0), reverse=True)
    return runs


def load_benchmark_details(
    run_id: str,
    results_dir: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Load complete benchmark run details including workload comparisons and query plans.
    """
    target_dir = Path(results_dir) if results_dir else _BENCHMARK_RESULTS_DIR
    target_file = target_dir / f"{run_id}.json"
    if not target_file.is_file():
        # Try finding by run_id in stem
        matches = list(target_dir.glob(f"*{run_id}*.json"))
        if matches:
            target_file = matches[0]
        else:
            return None

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load benchmark artifact %s: %s", target_file, exc)
        return None


def load_benchmark_samples_df(
    run_id: str,
    results_dir: Optional[Union[str, Path]] = None,
) -> Optional[pd.DataFrame]:
    """
    Load raw benchmark sample measurements CSV for distribution visualization.
    """
    target_dir = Path(results_dir) if results_dir else _BENCHMARK_RESULTS_DIR
    csv_file = target_dir / f"{run_id}_samples.csv"
    if not csv_file.is_file():
        # Fallback to finding by pattern
        matches = list(target_dir.glob(f"*{run_id}*_samples.csv"))
        if matches:
            csv_file = matches[0]
        else:
            return None

    try:
        return pd.read_csv(csv_file)
    except Exception as exc:
        logger.warning("Failed to parse benchmark samples CSV %s: %s", csv_file, exc)
        return None
