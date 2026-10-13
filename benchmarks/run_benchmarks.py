"""
CLI Runner for SQL vs NoSQL Performance Benchmarks.

Usage:
    python -m benchmarks.run_benchmarks [--iterations N] [--warmup W] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mongomock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from benchmarks.runner import BenchmarkRunner, export_benchmark_artifacts, generate_markdown_summary
from benchmarks.workloads import BENCHMARK_WORKLOADS
from database.mongodb.client import check_mongo_connectivity, get_mongo_database
from database.mongodb.collections import TELEMETRY_COLLECTION
from database.mongodb.repositories.analytics_repository import MongoAnalyticsRepository
from database.mysql.models import Base, IngestionEvent, PatientProfile, User, VitalsReading
from database.mysql.repositories.analytics_repository import SqlAnalyticsRepository
from database.mysql.session import check_db_connectivity, get_db, get_session_factory
from services.ingestion.importer import KaggleDatasetImporter
from services.sync.serialization import build_telemetry_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def setup_benchmark_fixture(kaggle_csv_path: Optional[Path] = None) -> tuple[Session, Any]:
    """
    Provision an isolated SQLite + mongomock benchmark environment seeded with
    identical telemetry data (either from real Kaggle CSV if present, or controlled fixture).
    """
    logger.info("Setting up isolated benchmark environment...")

    # 1. SQLite Engine & Tables
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    # 2. Mongomock Database
    mongo_client = mongomock.MongoClient()
    mongo_db = mongo_client["benchmark_analytics_db"]

    # 3. Seed data
    csv_candidates = [
        kaggle_csv_path,
        Path(r"E:\kaggle_health_dataset.csv"),
        Path(r"E:\DOC-20261013-WA0056.csv"),
    ]
    valid_csv = next((p for p in csv_candidates if p and p.is_file()), None)

    if valid_csv:
        logger.info("Ingesting real dataset from %s into benchmark fixture...", valid_csv)
        importer = KaggleDatasetImporter(session, batch_size=500)
        report = importer.run_import(valid_csv)
        logger.info(
            "Ingestion complete: %d events, %d readings inserted.",
            report.events_inserted,
            report.readings_inserted,
        )

        # Synchronize into mongomock
        events = list(session.scalars(select_events_with_readings()).unique().all())
        telemetry_docs = [build_telemetry_document(ev) for ev in events]
        if telemetry_docs:
            mongo_db[TELEMETRY_COLLECTION].insert_many(telemetry_docs)
            logger.info("Mirrored %d documents into mongomock.", len(telemetry_docs))
    else:
        logger.info("No CSV found on E:\\; seeding controlled synthetic benchmark fixture...")
        _seed_synthetic_fixture(session, mongo_db)

    return session, mongo_db


def select_events_with_readings():
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    return select(IngestionEvent).options(joinedload(IngestionEvent.readings))


def _seed_synthetic_fixture(session: Session, mongo_db: Any) -> None:
    """Fallback synthetic dataset when external CSV is unmounted."""
    t0 = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
    for p_id in ["P101", "P102", "P103"]:
        user = User(
            user_id=f"u_{p_id}",
            email=f"{p_id.lower()}@benchmark.internal",
            password_hash="$2b$12$dummyhash",
            role="patient",
        )
        profile = PatientProfile(
            patient_id=p_id,
            user_id=f"u_{p_id}",
            first_name="Benchmark",
            last_name=p_id,
        )
        session.add_all([user, profile])
        session.flush()

        for i in range(100):
            ev_id = f"evt_{p_id}_{i}"
            measured = t0.replace(hour=8 + (i % 12), minute=(i * 15) % 60)
            ev = IngestionEvent(
                event_id=ev_id,
                patient_id=p_id,
                source="kaggle_csv",
                source_event_id=f"src_{p_id}_{i}",
                measured_at=measured,
                is_simulated=False,
            )
            session.add(ev)
            session.flush()

            r_hr = VitalsReading(
                event_id=ev_id,
                patient_id=p_id,
                metric_code="heart_rate",
                value=75.0 + (i % 30),
                unit="bpm",
                raw_value=75.0 + (i % 30),
                raw_unit="bpm",
                measured_at=measured,
            )
            r_spo2 = VitalsReading(
                event_id=ev_id,
                patient_id=p_id,
                metric_code="spo2",
                value=96.0 + (i % 4),
                unit="%",
                raw_value=96.0 + (i % 4),
                raw_unit="%",
                measured_at=measured,
            )
            r_temp = VitalsReading(
                event_id=ev_id,
                patient_id=p_id,
                metric_code="temperature",
                value=37.0,
                unit="degC",
                raw_value=98.6 + (i % 3) * 0.4,
                raw_unit="degF",
                measured_at=measured,
            )
            session.add_all([r_hr, r_spo2, r_temp])
    session.commit()

    events = list(session.scalars(select_events_with_readings()).unique().all())
    telemetry_docs = [build_telemetry_document(ev) for ev in events]
    mongo_db[TELEMETRY_COLLECTION].insert_many(telemetry_docs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproducible SQL vs NoSQL Benchmark Runner")
    parser.add_argument("--iterations", type=int, default=20, help="Measured iterations (default: 20)")
    parser.add_argument("--warmup", type=int, default=3, help="Warmup iterations (default: 3)")
    parser.add_argument("--output-dir", type=str, default="benchmarks/results", help="Results directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # 1. Inspect live database connectivity
    has_live_mysql, mysql_status = check_db_connectivity(), "available" if check_db_connectivity() else "offline"
    has_live_mongo, mongo_status = check_mongo_connectivity()

    logger.info("Database Detection: MySQL live=%s (%s), MongoDB live=%s (%s)", has_live_mysql, mysql_status, has_live_mongo, mongo_status)

    if has_live_mysql and has_live_mongo:
        logger.info("Executing benchmark against LIVE MySQL and MongoDB Atlas instances.")
        sql_session = get_session_factory()()
        mongo_database = get_mongo_database()
    else:
        logger.info(
            "Live databases not fully configured (%s / %s). Running benchmark against isolated comparable benchmark fixture.",
            mysql_status,
            mongo_status,
        )
        sql_session, mongo_database = setup_benchmark_fixture()

    sql_repo = SqlAnalyticsRepository(sql_session)
    mongo_repo = MongoAnalyticsRepository(mongo_database)

    # 2. Execute benchmark harness
    runner = BenchmarkRunner(
        sql_repo=sql_repo,
        mongo_repo=mongo_repo,
        warmup_iterations=args.warmup,
        measured_iterations=args.iterations,
        randomize_order=True,
    )
    report = runner.run_all()

    # 3. Export artifacts
    artifact_paths = export_benchmark_artifacts(report, output_dir)
    logger.info("Benchmark artifacts exported:")
    for kind, path in artifact_paths.items():
        logger.info("  [%s]: %s", kind.upper(), path)

    # 4. Print Summary Markdown to stdout
    print("\n" + generate_markdown_summary(report) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
