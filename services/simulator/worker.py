"""
Smartwatch Sensor Simulator Background Ingestion Worker.

Runs an asynchronous, non-blocking polling loop against the simulator's
verified cursor-based streaming endpoint (`GET /api/v1/readings/stream`).

Key capabilities:
1. Lifecycle-managed: starts on FastAPI lifespan startup when enabled, terminates cleanly on shutdown.
2. Lossless cursor progression: advances cursor only after events are verified and processed.
3. Idempotent resilience: duplicate events are safely detected and skipped without data corruption.
4. Operational metrics: reports live counters, latencies, and sanitized error categories.
5. Interruptible sleep: stops immediately without lagging for the full polling interval on shutdown.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from database.mongodb.client import get_mongo_database
from database.mysql.models import IngestionEvent
from database.mysql.session import get_session_factory
from services.api.config import Settings, get_settings
from services.ml_service import get_ml_service
from services.simulator.ingestion_service import (
    IngestionOutcome,
    SimulatorIngestionService,
)

logger = logging.getLogger(__name__)

_worker_instance: Optional[SimulatorIngestionWorker] = None


class SimulatorIngestionWorker:
    """Manages the background polling loop and telemetry ingestion pipeline."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.ingestion_service = SimulatorIngestionService()
        self.session_factory = get_session_factory()

        # Operational state & metrics
        self.is_running: bool = False
        self.cursor: Optional[str] = None
        self.last_poll_succeeded: Optional[bool] = None
        self.last_poll_timestamp: Optional[str] = None
        self.last_successful_poll_timestamp: Optional[str] = None
        self.last_ingested_event_id: Optional[str] = None
        self.last_successful_db_sync_timestamp: Optional[str] = None
        self.events_received_count: int = 0
        self.events_accepted_count: int = 0
        self.events_duplicates_skipped_count: int = 0
        self.events_rejected_count: int = 0
        self.consecutive_failures: int = 0
        self.last_error_category: str = "none"
        self.last_error_detail: Optional[str] = None
        self.last_latency_ms: Optional[float] = None

        # Concurrency primitives
        self._task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def is_enabled(self) -> bool:
        return bool(self.settings.simulator_ingestion_enabled)

    def init_cursor_from_database(self) -> None:
        """
        Check relational database for the latest persisted simulator source_event_id.
        Avoids redundant reprocessing upon backend restarts.
        """
        try:
            with self.session_factory() as session:
                stmt = (
                    select(IngestionEvent.source_event_id)
                    .where(IngestionEvent.source == "smartwatch_simulator")
                    .order_by(desc(IngestionEvent.measured_at), desc(IngestionEvent.event_id))
                    .limit(1)
                )
                latest_id = session.scalar(stmt)
                if latest_id:
                    self.cursor = latest_id
                    logger.info("Initialized simulator ingestion cursor from MySQL: %s", latest_id)
        except Exception as exc:
            logger.warning("Could not pre-populate cursor from database (will start from beginning): %s", exc)

    async def poll_once(self, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        """
        Execute a single polling and ingestion iteration.
        Returns a dictionary summarizing results and operational metrics.
        """
        self.last_poll_timestamp = datetime.now(timezone.utc).isoformat()
        base_url = self.settings.sensor_simulator_base_url.rstrip("/")
        stream_url = f"{base_url}/api/v1/readings/stream"

        params: Dict[str, Any] = {
            "limit": self.settings.simulator_batch_limit,
        }
        if self.cursor:
            params["cursor"] = self.cursor

        headers: Dict[str, str] = {
            "Accept": "application/json",
        }
        if self.settings.simulator_api_key:
            headers["X-Simulator-Key"] = self.settings.simulator_api_key

        t0 = time.perf_counter()
        owns_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.simulator_poll_timeout_seconds)
            owns_client = True

        try:
            response = await client.get(stream_url, params=params, headers=headers)
            self.last_latency_ms = round((time.perf_counter() - t0) * 1000, 2)

            if response.status_code != 200:
                self.last_poll_succeeded = False
                self.consecutive_failures += 1
                self.last_error_category = "http_error"
                self.last_error_detail = f"Simulator HTTP {response.status_code}: {response.text[:200]}"
                logger.warning("Simulator polling error: %s", self.last_error_detail)
                return {"status": "error", "error": self.last_error_category}

            try:
                data = response.json()
            except Exception as json_err:
                self.last_poll_succeeded = False
                self.consecutive_failures += 1
                self.last_error_category = "malformed_response"
                self.last_error_detail = f"Simulator returned non-JSON payload: {json_err}"
                return {"status": "error", "error": "malformed_response"}

            if not isinstance(data, dict):
                self.last_poll_succeeded = False
                self.consecutive_failures += 1
                self.last_error_category = "malformed_response"
                self.last_error_detail = "Simulator returned top-level JSON that is not an object."
                return {"status": "error", "error": "malformed_response"}

            readings = data.get("items") or data.get("readings") or []
            if not isinstance(readings, list):
                self.last_poll_succeeded = False
                self.consecutive_failures += 1
                self.last_error_category = "malformed_response"
                self.last_error_detail = "Simulator readings field is not a list."
                return {"status": "error", "error": "malformed_response"}

            next_cursor = data.get("next_cursor")
            self.events_received_count += len(readings)

            # Lazy access to MongoDB and ML services
            mongo_db = get_mongo_database(self.settings) if self.settings.mongodb_sync_enabled else None
            try:
                ml_service = get_ml_service(self.settings)
            except Exception:
                ml_service = None

            batch_failed = False
            last_processed_event_id: Optional[str] = None

            # Process events sequentially through existing relational pipeline
            with self.session_factory() as db:
                for r in readings:
                    res = self.ingestion_service.ingest_single_reading(
                        db=db,
                        reading=r,
                        mongo_db=mongo_db,
                        ml_service=ml_service,
                    )

                    if res.outcome == IngestionOutcome.ACCEPTED:
                        self.events_accepted_count += 1
                        last_processed_event_id = res.event_id
                        self.last_ingested_event_id = res.event_id
                        self.last_successful_db_sync_timestamp = datetime.now(timezone.utc).isoformat()
                    elif res.outcome == IngestionOutcome.DUPLICATE_SKIPPED:
                        self.events_duplicates_skipped_count += 1
                        last_processed_event_id = res.event_id
                    elif res.outcome in (
                        IngestionOutcome.UNKNOWN_PATIENT_REJECTED,
                        IngestionOutcome.MALFORMED_REJECTED,
                        IngestionOutcome.NOT_SIMULATED_REJECTED,
                        IngestionOutcome.UNSUPPORTED_UNITS_REJECTED,
                        IngestionOutcome.UNTRUSTED_PROVENANCE_REJECTED,
                    ):
                        self.events_rejected_count += 1
                        last_processed_event_id = res.event_id
                    elif res.outcome == IngestionOutcome.FAILED:
                        self.last_error_category = "database_error"
                        self.last_error_detail = res.detail
                        batch_failed = True
                        logger.error("Ingestion failed on event %s; pausing cursor advancement: %s", res.event_id, res.detail)
                        break

                # Opportunistic outbox drain only if MongoDB sync is explicitly enabled and batch succeeded
                if not batch_failed and self.settings.mongodb_sync_enabled and mongo_db is not None:
                    try:
                        from services.sync.outbox_service import OutboxSyncService
                        outbox_svc = OutboxSyncService(db, mongo_db, sync_enabled=True)
                        outbox_svc.process_outbox_batch(limit=10)
                    except Exception as outbox_exc:
                        logger.debug("Opportunistic outbox drain in worker cycle: %s", outbox_exc)

            # Advance cursor only according to verified batch outcome
            if not batch_failed:
                if next_cursor:
                    self.cursor = next_cursor
                elif last_processed_event_id:
                    self.cursor = last_processed_event_id

                self.last_poll_succeeded = True
                self.consecutive_failures = 0
                self.last_successful_poll_timestamp = datetime.now(timezone.utc).isoformat()
                self.last_error_category = "none"
                self.last_error_detail = None
            else:
                self.last_poll_succeeded = False
                self.consecutive_failures += 1
                # Partial failure protection:
                # Advance cursor to the last successfully processed event if any succeeded,
                # ensuring already committed events are not re-requested, while the failed
                # event will be the first item retried on the next polling cycle.
                if last_processed_event_id:
                    self.cursor = last_processed_event_id

            return {
                "status": "success" if not batch_failed else "partial_failure",
                "readings_in_cycle": len(readings),
                "cursor": self.cursor,
            }

        except httpx.ConnectError as ce:
            self.last_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            self.last_poll_succeeded = False
            self.consecutive_failures += 1
            self.last_error_category = "connection_refused"
            self.last_error_detail = f"Could not connect to simulator at {stream_url}: {ce}"
            logger.debug("Simulator connection refused (service offline).")
            return {"status": "error", "error": "connection_refused"}

        except (httpx.ConnectTimeout, httpx.ReadTimeout) as te:
            self.last_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            self.last_poll_succeeded = False
            self.consecutive_failures += 1
            self.last_error_category = "timeout"
            self.last_error_detail = f"Simulator poll timed out after {self.settings.simulator_poll_timeout_seconds}s: {te}"
            logger.warning("Simulator poll timeout.")
            return {"status": "error", "error": "timeout"}

        except Exception as exc:
            self.last_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            self.last_poll_succeeded = False
            self.consecutive_failures += 1
            self.last_error_category = "poll_exception"
            self.last_error_detail = str(exc)
            logger.error("Unexpected error polling simulator: %s", exc, exc_info=True)
            return {"status": "error", "error": "poll_exception"}

        finally:
            if owns_client and client is not None:
                await client.aclose()

    async def _run_loop(self) -> None:
        """Continuous background execution loop with graceful interruption and bounded exponential backoff."""
        logger.info(
            "Starting smartwatch simulator ingestion loop (target: %s, interval: %.1fs)",
            self.settings.sensor_simulator_base_url,
            self.settings.simulator_poll_interval_seconds,
        )

        async with httpx.AsyncClient(timeout=self.settings.simulator_poll_timeout_seconds) as client:
            while not self._stop_event.is_set():
                try:
                    await self.poll_once(client=client)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("Unhandled error in simulator worker iteration: %s", exc)

                # Determine sleep duration with bounded exponential backoff on repeated failures
                if self.last_poll_succeeded is False and self.consecutive_failures > 0:
                    backoff = min(
                        60.0,
                        self.settings.simulator_poll_interval_seconds * (1.5 ** min(self.consecutive_failures, 8)),
                    )
                else:
                    backoff = self.settings.simulator_poll_interval_seconds

                # Wait with early exit on stop signal
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=backoff,
                    )
                except asyncio.TimeoutError:
                    pass

        logger.info("Smartwatch simulator ingestion loop has terminated cleanly.")

    async def start(self) -> None:
        """Start the background polling worker task idempotently."""
        async with self._lock:
            if self.is_running:
                logger.info("Simulator ingestion worker is already running.")
                return

            if self.cursor is None:
                self.init_cursor_from_database()

            self._stop_event.clear()
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop(), name="simulator_ingestion_worker")
            logger.info("Launched simulator ingestion background task.")

    async def stop(self) -> None:
        """Signal and await background worker termination."""
        async with self._lock:
            if not self.is_running:
                return

            logger.info("Stopping simulator ingestion background task...")
            self._stop_event.set()
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await asyncio.wait_for(self._task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

            self.is_running = False
            self._task = None
            logger.info("Simulator ingestion background task stopped successfully.")

    def get_status(self) -> Dict[str, Any]:
        """Return operational diagnostic status dictionary for monitoring and dashboards."""
        pending_outbox_count = 0
        try:
            with self.session_factory() as session:
                from database.mysql.repositories.outbox_repository import OutboxRepository
                stats = OutboxRepository(session).get_outbox_stats()
                pending_outbox_count = stats.get("pending", 0) + stats.get("failed", 0)
        except Exception:
            pass

        persistence_healthy = self.last_error_category != "database_error"
        simulator_reachable = self.last_error_category not in ("connection_refused", "timeout")

        # Determine current simulator status
        if not self.is_enabled:
            sim_status = "disabled"
            pipeline_health = "disabled"
        elif not persistence_healthy:
            sim_status = "online" if simulator_reachable else "unreachable"
            pipeline_health = "persistence_failing"
        elif not self.is_running:
            sim_status = "stopped"
            pipeline_health = "stopped"
        elif not simulator_reachable:
            sim_status = "unreachable"
            pipeline_health = "simulator_unreachable"
        elif self.consecutive_failures > 0:
            sim_status = "degraded"
            pipeline_health = "degraded"
        elif self.last_poll_succeeded is True:
            sim_status = "online"
            pipeline_health = "healthy"
        else:
            sim_status = "initializing"
            pipeline_health = "initializing"

        return {
            "enabled": self.is_enabled,
            "running": self.is_running,
            "pipeline_health": pipeline_health,
            "current_simulator_status": sim_status,
            "simulator_base_url": self.settings.sensor_simulator_base_url,
            "poll_interval_seconds": self.settings.simulator_poll_interval_seconds,
            "poll_timeout_seconds": self.settings.simulator_poll_timeout_seconds,
            "last_poll_succeeded": self.last_poll_succeeded,
            "last_poll_timestamp": self.last_poll_timestamp,
            "last_successful_poll": self.last_successful_poll_timestamp,
            "last_successful_poll_timestamp": self.last_successful_poll_timestamp,
            "last_successfully_ingested_event": self.last_ingested_event_id,
            "latency_ms": self.last_latency_ms,
            "current_cursor": self.cursor,
            "pending_events": pending_outbox_count,
            "events_received_count": self.events_received_count,
            "events_accepted_count": self.events_accepted_count,
            "events_duplicates_skipped_count": self.events_duplicates_skipped_count,
            "events_rejected_count": self.events_rejected_count,
            "consecutive_failures": self.consecutive_failures,
            "latest_successful_database_synchronization": self.last_successful_db_sync_timestamp,
            "last_error_category": self.last_error_category,
            "last_error_detail": self._sanitize_error_detail(self.last_error_detail),
            "persistence_healthy": persistence_healthy,
            "simulator_reachable": simulator_reachable,
        }

    @staticmethod
    def _sanitize_error_detail(detail: Optional[str]) -> Optional[str]:
        if not detail:
            return None
        s = str(detail)
        s = re.sub(r"mongodb(\+srv)?://[^@]+@", "mongodb://***:***@", s)
        s = re.sub(r"(password|secret|key|token)=[^&\s]+", r"\1=***", s, flags=re.IGNORECASE)
        return s[:500]


def get_simulator_worker(settings: Optional[Settings] = None) -> SimulatorIngestionWorker:
    """Singleton provider for the simulator ingestion worker."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = SimulatorIngestionWorker(settings=settings)
    return _worker_instance
