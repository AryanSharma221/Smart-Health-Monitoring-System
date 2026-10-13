"""
Command-Line Interface for Kaggle Dataset Ingestion.

Usage:
    python -m services.ingestion.cli --dry-run
    python -m services.ingestion.cli --csv-path "E:\\kaggle_health_dataset.csv"
    python -m services.ingestion.cli --csv-path "E:\\DOC-20261013-WA0056.csv" --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from database.mysql.session import get_engine, get_session_factory
from services.api.config import get_settings
from services.ingestion.importer import KaggleDatasetImporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kaggle_importer")


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="Ingest Kaggle Health Monitoring CSV into MySQL Relational Persistence.",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default=settings.kaggle_dataset_path,
        help="Path to Kaggle health dataset CSV (default: configured in .env or settings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform structural and record validation without committing changes to database",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Number of records to persist per database transaction (default: 250)",
    )
    parser.add_argument(
        "--no-auto-seed",
        action="store_true",
        help="Do not auto-provision baseline PatientProfile records for unmapped patient IDs",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override database connection URL (e.g. sqlite:///test.db for isolated testing)",
    )

    args = parser.parse_args(argv)

    target_path = Path(args.csv_path).resolve()
    # Check if configured path exists; fallback to known locations if default doesn't exist
    if not target_path.exists():
        fallback_candidates = [
            Path(r"E:\DOC-20261013-WA0056.csv"),
            Path(r"E:\kaggle_health_dataset.csv"),
        ]
        for candidate in fallback_candidates:
            if candidate.exists():
                logger.info("Configured path '%s' not found. Falling back to '%s'", target_path, candidate)
                target_path = candidate
                break

    if not target_path.exists():
        logger.error("Dataset file not found at: %s", target_path)
        return 1

    from database.mysql.models import Base

    engine = get_engine(args.database_url)
    Base.metadata.create_all(bind=engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        importer = KaggleDatasetImporter(
            session=session,
            batch_size=args.batch_size,
            auto_seed_patients=not args.no_auto_seed,
            source_timezone=settings.dataset_source_timezone,
        )

        try:
            report = importer.run_import(
                csv_path=target_path,
                dry_run=args.dry_run,
            )
            print(report.format_console_report())
            return 0 if report.status in ("completed", "dry_run_success") else 1
        except Exception as exc:
            logger.exception("Fatal error during dataset ingestion: %s", exc)
            return 1


if __name__ == "__main__":
    sys.exit(main())
