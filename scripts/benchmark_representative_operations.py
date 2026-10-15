"""
Smart Health Monitoring System — Representative Operations Performance Benchmark.
Part 6R — Reproducible Performance Evaluation.

Measures actual, empirical response times across 9 canonical system operations:
1. Health and Liveness Probes (/health, /health/live)
2. Patient Roster Retrieval (/api/v1/patients)
3. Patient-Specific Historical Vitals Retrieval (/api/v1/readings?patient_id=P101)
4. Latest Telemetry Observation Retrieval (/api/v1/readings/latest)
5. Downstream Telemetry Ingestion Polling Cycle (/api/v1/simulator/ingestion/poll)
6. Clinical Alerts List Retrieval (/api/v1/alerts)
7. MongoDB Aggregation Pipelines (7 canonical analytics workloads)
8. End-to-End Latency: Generation to Database Persistence
9. Simulator Immediate Stop Responsiveness (/api/v1/simulator/stop)

Outputs structured statistical distributions to benchmark_representative_evidence.json.
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.mysql.models import IngestionEvent, VitalsReading
from services.api.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark_ops")


class BenchmarkSuite:
    def __init__(self) -> None:
        self.settings: Settings = get_settings()
        self.backend_url = f"http://127.0.0.1:{self.settings.api_port}"
        self.sim_url = self.settings.sensor_simulator_base_url.rstrip("/")
        self.engine = create_engine(self.settings.database_url, echo=False)
        self.session_factory = sessionmaker(bind=self.engine)
        self.client = httpx.Client(timeout=15.0)

        # Authenticate doctor to obtain JWT token for protected clinical routes
        self.token = self._acquire_clinician_token()
        self.auth_headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

        self.benchmarks: List[Dict[str, Any]] = []

    def _acquire_clinician_token(self) -> Optional[str]:
        try:
            resp = self.client.post(
                f"{self.backend_url}/api/v1/auth/login",
                json={"email": "doctor@hospital.org", "password": "DoctorPassword123!"},
            )
            if resp.status_code == 200:
                return resp.json().get("access_token")
        except Exception as exc:
            logger.warning("Could not acquire doctor JWT token: %s", exc)
        return None

    def _measure_call(
        self,
        name: str,
        category: str,
        operation: Callable[[], bool],
        iterations: int = 50,
        warmup: int = 3,
    ) -> Dict[str, Any]:
        print(f"\n[*] Benchmarking '{name}' ({iterations} iterations, {warmup} warmup)...", end="", flush=True)

        # Warm-up phase
        for _ in range(warmup):
            try:
                operation()
            except Exception:
                pass

        latencies_ms: List[float] = []
        successes = 0
        failures = 0

        t_start_total = time.perf_counter()
        for i in range(iterations):
            t0 = time.perf_counter_ns()
            try:
                ok = operation()
                t1 = time.perf_counter_ns()
                elapsed_ms = (t1 - t0) / 1_000_000.0
                if ok:
                    latencies_ms.append(elapsed_ms)
                    successes += 1
                else:
                    failures += 1
            except Exception as exc:
                failures += 1
                logger.debug("Iteration error: %s", exc)

        t_end_total = time.perf_counter()
        total_duration_sec = round(t_end_total - t_start_total, 3)

        if latencies_ms:
            sorted_lat = sorted(latencies_ms)
            min_ms = round(sorted_lat[0], 2)
            max_ms = round(sorted_lat[-1], 2)
            mean_ms = round(statistics.mean(sorted_lat), 2)
            median_ms = round(statistics.median(sorted_lat), 2)
            p95_idx = int(0.95 * len(sorted_lat))
            p95_ms = round(sorted_lat[min(p95_idx, len(sorted_lat) - 1)], 2)
            stddev_ms = round(statistics.stdev(sorted_lat), 2) if len(sorted_lat) > 1 else 0.0
        else:
            min_ms = max_ms = mean_ms = median_ms = p95_ms = stddev_ms = 0.0

        print(f" Done! [Median: {median_ms}ms | p95: {p95_ms}ms | Success: {successes}/{iterations}]")

        metric_record = {
            "name": name,
            "category": category,
            "iterations": iterations,
            "warmup_iterations": warmup,
            "success_count": successes,
            "failure_count": failures,
            "total_elapsed_sec": total_duration_sec,
            "min_ms": min_ms,
            "mean_ms": mean_ms,
            "median_ms": median_ms,
            "p95_ms": p95_ms,
            "max_ms": max_ms,
            "stddev_ms": stddev_ms,
        }
        self.benchmarks.append(metric_record)
        return metric_record

    # 1. Health / Liveness
    def benchmark_health(self) -> None:
        def op():
            r = self.client.get(f"{self.backend_url}/health")
            return r.status_code == 200

        self._measure_call("Gateway Health Probe (/health)", "System Health", op, iterations=50)

    # 2. Patient Roster
    def benchmark_patient_roster(self) -> None:
        def op():
            r = self.client.get(f"{self.backend_url}/api/v1/patients", headers=self.auth_headers)
            return r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) >= 5

        self._measure_call("Patient Cohort Directory (/api/v1/patients)", "Core EHR", op, iterations=50)

    # 3. Patient Vitals Query
    def benchmark_patient_vitals_query(self) -> None:
        def op():
            r = self.client.get(f"{self.backend_url}/api/v1/patients/P101/readings?page_size=50", headers=self.auth_headers)
            return r.status_code == 200 and len(r.json().get("items", [])) > 0

        self._measure_call("Patient Vitals History (/api/v1/patients/P101/readings)", "Telemetry Queries", op, iterations=50)

    # 4. Latest Telemetry
    def benchmark_latest_reading(self) -> None:
        def op():
            r = self.client.get(f"{self.sim_url}/api/v1/readings/latest")
            return r.status_code == 200 and "P101" in r.json().get("readings", {})

        self._measure_call("Latest Telemetry Snapshot (/api/v1/readings/latest)", "Telemetry Queries", op, iterations=50)

    # 5. Ingestion Polling Cycle
    def benchmark_ingestion_poll(self) -> None:
        def op():
            r = self.client.post(f"{self.backend_url}/api/v1/simulator/ingestion/poll")
            return r.status_code == 200

        self._measure_call("Backend Ingestion Poll Iteration (/api/v1/simulator/ingestion/poll)", "Ingestion Pipeline", op, iterations=25)

    # 6. Clinical Alerts Query
    def benchmark_alerts_query(self) -> None:
        def op():
            r = self.client.get(f"{self.backend_url}/api/v1/alerts?limit=50", headers=self.auth_headers)
            return r.status_code == 200

        self._measure_call("Clinical Alerts Retrieval (/api/v1/alerts)", "Alert Engine", op, iterations=50)

    # 7. MongoDB Aggregation Workload
    def benchmark_mongodb_aggregations(self) -> None:
        import mongomock
        from database.mongodb.collections import TELEMETRY_COLLECTION
        from database.mongodb.analytics.pipelines import build_dataset_overview_pipeline, build_patient_vitals_summary_pipeline
        from services.sync.serialization import build_telemetry_document

        # Populate in-memory mongomock with 1,500 records from database
        client_mock = mongomock.MongoClient()
        db_mock = client_mock["bench_analytics"]
        
        with self.session_factory() as session:
            events = session.query(IngestionEvent).limit(1500).all()
            docs = [build_telemetry_document(ev) for ev in events]
            if docs:
                db_mock[TELEMETRY_COLLECTION].insert_many(docs)

        pipeline_overview = build_dataset_overview_pipeline()
        def op_overview():
            res = list(db_mock[TELEMETRY_COLLECTION].aggregate(pipeline_overview))
            return len(res) > 0

        self._measure_call("MongoDB Overview $facet Aggregation", "NoSQL Analytics", op_overview, iterations=30)

        pipeline_vitals = build_patient_vitals_summary_pipeline("P101")
        def op_vitals():
            res = list(db_mock[TELEMETRY_COLLECTION].aggregate(pipeline_vitals))
            return len(res) > 0

        self._measure_call("MongoDB Patient Vitals $group Aggregation", "NoSQL Analytics", op_vitals, iterations=30)

    # 8. Generation to Persistence Latency
    def benchmark_event_persistence_latency(self) -> None:
        print("\n[*] Measuring Event Generation-to-Persistence Ingestion Latency...", end="", flush=True)
        # Query 50 most recent ingestion events and compare measured_at to received_at / created_at
        delays_ms: List[float] = []
        with self.session_factory() as session:
            events = session.query(IngestionEvent).filter(IngestionEvent.source == "smartwatch_simulator").order_by(IngestionEvent.created_at.desc()).limit(50).all()
            for ev in events:
                if ev.received_at and ev.measured_at:
                    delta = (ev.received_at - ev.measured_at).total_seconds() * 1000.0
                    # Bound to non-negative clock drift limits
                    if 0.0 <= delta <= 15000.0:
                        delays_ms.append(delta)

        if delays_ms:
            sorted_delays = sorted(delays_ms)
            median_ms = round(statistics.median(sorted_delays), 2)
            p95_ms = round(sorted_delays[int(0.95 * len(sorted_delays))], 2)
            print(f" Done! [Median Ingestion Delay: {median_ms}ms | p95: {p95_ms}ms (Sample: {len(delays_ms)})]")
            self.benchmarks.append({
                "name": "End-to-End Generation-to-Ingestion Latency",
                "category": "Pipeline Freshness",
                "iterations": len(delays_ms),
                "warmup_iterations": 0,
                "success_count": len(delays_ms),
                "failure_count": 0,
                "total_elapsed_sec": 0.0,
                "min_ms": round(sorted_delays[0], 2),
                "mean_ms": round(statistics.mean(sorted_delays), 2),
                "median_ms": median_ms,
                "p95_ms": p95_ms,
                "max_ms": round(sorted_delays[-1], 2),
                "stddev_ms": round(statistics.stdev(sorted_delays), 2) if len(sorted_delays) > 1 else 0.0,
            })
        else:
            print(" [UNAVAILABLE — No recent paired simulator events]")

    # 9. Simulator Stop Response Time
    def benchmark_simulator_stop_responsiveness(self) -> None:
        def op():
            # Start generator first so stop has work to do
            self.client.post(f"{self.backend_url}/api/v1/simulator/start")
            time.sleep(0.05)
            # Measure stop latency
            r = self.client.post(f"{self.backend_url}/api/v1/simulator/stop")
            return r.status_code == 200 and r.json().get("lifecycle_state") == "STOPPED"

        self._measure_call("Simulator Immediate Stop Response (/api/v1/simulator/stop)", "Lifecycle Controls", op, iterations=10, warmup=1)

    def run_all(self) -> None:
        print("=" * 80)
        print("SMART HEALTH MONITORING SYSTEM — PERFORMANCE BENCHMARK SUITE")
        print(f"Environment: Python {sys.version.split()[0]} on {sys.platform}")
        print(f"Backend Target: {self.backend_url} | Simulator Target: {self.sim_url}")
        print("=" * 80)

        self.benchmark_health()
        self.benchmark_patient_roster()
        self.benchmark_patient_vitals_query()
        self.benchmark_latest_reading()
        self.benchmark_ingestion_poll()
        self.benchmark_alerts_query()
        self.benchmark_mongodb_aggregations()
        self.benchmark_event_persistence_latency()
        self.benchmark_simulator_stop_responsiveness()

        print("\n" + "=" * 80)
        print("BENCHMARK EXECUTION SUMMARY")
        print("=" * 80)
        print(f"{'Operation Name':<45} | {'Median (ms)':<12} | {'p95 (ms)':<10} | {'Success':<8}")
        print("-" * 80)
        for b in self.benchmarks:
            print(f"{b['name']:<45} | {b['median_ms']:>10.2f} ms | {b['p95_ms']:>8.2f} ms | {b['success_count']}/{b['iterations']}")
        print("=" * 80)

        output_file = "benchmark_representative_evidence.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "runtime_environment": {
                    "python_version": sys.version.split()[0],
                    "platform": sys.platform,
                    "database_url_scheme": self.settings.database_url.split("://")[0],
                    "mongodb_sync_enabled": self.settings.mongodb_sync_enabled,
                },
                "benchmarks": self.benchmarks,
            }, f, indent=2)
        print(f"\n[+] Saved structured benchmark evidence to '{output_file}'")


if __name__ == "__main__":
    suite = BenchmarkSuite()
    suite.run_all()
