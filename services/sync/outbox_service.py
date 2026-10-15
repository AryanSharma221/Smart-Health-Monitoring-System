"""
Transactional Outbox Synchronization Service for MongoDB Atlas Analytics Mirror.

Enforces:
1. MySQL authority: Writes to MySQL always succeed regardless of MongoDB availability.
2. Idempotent delivery: All writes to MongoDB use stable IDs (_id = event_id / alert_id).
3. Failure recovery: Transient network or Atlas outages leave records in 'pending' or 'failed'
   status in analytics_outbox, which are retried safely by outbox batch processing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pymongo.database import Database
from pymongo.errors import PyMongoError
from sqlalchemy.orm import Session

from database.mongodb.repositories.alert_mirror_repository import AlertMirrorRepository
from database.mongodb.repositories.telemetry_mirror_repository import (
    TelemetryMirrorRepository,
)
from database.mysql.models import Alert, AnalyticsOutbox, IngestionEvent
from database.mysql.repositories.outbox_repository import OutboxRepository
from services.sync.serialization import (
    build_alert_document,
    build_telemetry_document,
    document_to_json,
    json_to_document,
)

logger = logging.getLogger(__name__)


class OutboxSyncService:
    """Coordinates event staging, opportunistic delivery, and batch failure recovery."""

    def __init__(
        self,
        session: Session,
        mongo_db: Optional[Database] = None,
        sync_enabled: Optional[bool] = None,
    ) -> None:
        self.session = session
        if sync_enabled is not None:
            self.sync_enabled = sync_enabled
        else:
            self.sync_enabled = mongo_db is not None

        self.mongo_db = mongo_db if self.sync_enabled else None
        self.outbox_repo = OutboxRepository(session)
        self.telemetry_repo = TelemetryMirrorRepository(self.mongo_db) if self.mongo_db is not None else None
        self.alert_repo = AlertMirrorRepository(self.mongo_db) if self.mongo_db is not None else None

    def stage_telemetry(self, event: IngestionEvent) -> AnalyticsOutbox:
        """Stage an IngestionEvent into the analytics outbox within the current transaction."""
        doc = build_telemetry_document(event)
        payload_json = document_to_json(doc)
        return self.outbox_repo.stage_event(
            event_type="telemetry_event",
            aggregate_id=event.event_id,
            payload_json=payload_json,
        )

    def stage_alert(self, alert: Alert) -> AnalyticsOutbox:
        """Stage an Alert lifecycle event into the analytics outbox within the current transaction."""
        doc = build_alert_document(alert)
        payload_json = document_to_json(doc)
        return self.outbox_repo.stage_event(
            event_type="alert_event",
            aggregate_id=alert.alert_id,
            payload_json=payload_json,
        )

    def sync_telemetry_immediate(self, event: IngestionEvent) -> bool:
        """
        Stage event and attempt immediate opportunistic write to MongoDB Atlas.
        If MongoDB is offline, disabled, or fails, the event remains pending in outbox.
        MySQL success is never aborted due to MongoDB mirror issues.
        """
        outbox_entry = self.stage_telemetry(event)

        if not self.sync_enabled or self.telemetry_repo is None or self.mongo_db is None:
            logger.debug(
                "MongoDB Atlas sync disabled or unavailable; telemetry event %s queued in outbox (pending).",
                event.event_id,
            )
            return False

        try:
            doc = build_telemetry_document(event)
            self.telemetry_repo.upsert_event(doc)
            self.outbox_repo.mark_completed(outbox_entry.outbox_id)
            event.mirror_status = "mirrored"
            self.session.flush()
            logger.info("Successfully mirrored telemetry event %s to MongoDB.", event.event_id)
            return True
        except PyMongoError as exc:
            logger.warning(
                "Immediate MongoDB mirror failed for telemetry %s: %s (queued in outbox)",
                event.event_id,
                exc,
            )
            self.outbox_repo.mark_failed(outbox_entry.outbox_id, str(exc))
            self.session.flush()
            return False
        except Exception as exc:
            logger.error("Unexpected error during telemetry mirror: %s", exc)
            self.outbox_repo.mark_failed(outbox_entry.outbox_id, str(exc))
            self.session.flush()
            return False

    def sync_alert_immediate(self, alert: Alert) -> bool:
        """
        Stage alert and attempt immediate opportunistic write to MongoDB Atlas.
        """
        outbox_entry = self.stage_alert(alert)

        if not self.sync_enabled or self.alert_repo is None or self.mongo_db is None:
            logger.debug(
                "MongoDB Atlas sync disabled or unavailable; alert %s queued in outbox (pending).",
                alert.alert_id,
            )
            return False

        try:
            doc = build_alert_document(alert)
            self.alert_repo.upsert_alert(doc)
            self.outbox_repo.mark_completed(outbox_entry.outbox_id)
            self.session.flush()
            logger.info("Successfully mirrored alert %s to MongoDB.", alert.alert_id)
            return True
        except PyMongoError as exc:
            logger.warning(
                "Immediate MongoDB mirror failed for alert %s: %s (queued in outbox)",
                alert.alert_id,
                exc,
            )
            self.outbox_repo.mark_failed(outbox_entry.outbox_id, str(exc))
            self.session.flush()
            return False
        except Exception as exc:
            logger.error("Unexpected error during alert mirror: %s", exc)
            self.outbox_repo.mark_failed(outbox_entry.outbox_id, str(exc))
            self.session.flush()
            return False

    def process_outbox_batch(self, limit: int = 50) -> Dict[str, Any]:
        """
        Process a batch of pending or retryable outbox entries.
        Recovers from transient outages and replays unmirrored events.
        """
        if not self.sync_enabled or self.mongo_db is None:
            status_desc = "sync_disabled" if (self.mongo_db is not None and not self.sync_enabled) else "mongodb_unavailable"
            return {
                "status": status_desc,
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
            }

        entries = self.outbox_repo.get_pending_batch(limit=limit)
        if not entries:
            return {
                "status": "idle",
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
            }

        succeeded = 0
        failed = 0

        for entry in entries:
            self.outbox_repo.mark_processing(entry.outbox_id)
            try:
                doc = json_to_document(entry.payload_json)

                if entry.event_type == "telemetry_event":
                    TelemetryMirrorRepository(self.mongo_db).upsert_event(doc)
                    self.outbox_repo.mark_completed(entry.outbox_id)
                    # Update source IngestionEvent mirror_status if present
                    source_event = self.session.get(IngestionEvent, entry.aggregate_id)
                    if source_event:
                        source_event.mirror_status = "mirrored"

                elif entry.event_type == "alert_event":
                    AlertMirrorRepository(self.mongo_db).upsert_alert(doc)
                    self.outbox_repo.mark_completed(entry.outbox_id)

                succeeded += 1
            except Exception as exc:
                failed += 1
                logger.warning(
                    "Outbox retry failed for %s (%s): %s",
                    entry.event_type,
                    entry.aggregate_id,
                    exc,
                )
                self.outbox_repo.mark_failed(entry.outbox_id, str(exc))
                # If exhausted attempts, update source IngestionEvent mirror_status to failed
                if entry.event_type == "telemetry_event" and entry.status == "failed":
                    source_event = self.session.get(IngestionEvent, entry.aggregate_id)
                    if source_event:
                        source_event.mirror_status = "failed"

        self.session.flush()
        return {
            "status": "processed",
            "processed": len(entries),
            "succeeded": succeeded,
            "failed": failed,
        }
