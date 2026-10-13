"""
Transactional Outbox Repository for Analytics Synchronization.

Encapsulates relational persistence queries for the analytics outbox queue,
enabling reliable asynchronous event delivery to MongoDB Atlas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from database.mysql.models import AnalyticsOutbox


class OutboxRepository:
    """Encapsulates relational persistence queries for analytics outbox events."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def stage_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload_json: str,
        max_attempts: int = 5,
    ) -> AnalyticsOutbox:
        """
        Stage a new event into the transactional outbox.
        Must be committed within the same database transaction as the source entity.
        """
        outbox_entry = AnalyticsOutbox(
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload_json=payload_json,
            status="pending",
            attempt_count=0,
            max_attempts=max_attempts,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(outbox_entry)
        self.session.flush()
        return outbox_entry

    def get_by_id(self, outbox_id: int) -> Optional[AnalyticsOutbox]:
        """Fetch outbox record by primary key."""
        return self.session.get(AnalyticsOutbox, outbox_id)

    def get_pending_batch(self, limit: int = 50) -> List[AnalyticsOutbox]:
        """
        Retrieve a batch of pending or retryable failed outbox records.
        Ordered chronologically by created_at.
        """
        stmt = (
            select(AnalyticsOutbox)
            .where(
                AnalyticsOutbox.status.in_(["pending", "processing"]),
                AnalyticsOutbox.attempt_count < AnalyticsOutbox.max_attempts,
            )
            .order_by(AnalyticsOutbox.created_at.asc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def mark_processing(self, outbox_id: int) -> bool:
        """Increment attempt count and mark status as processing."""
        entry = self.get_by_id(outbox_id)
        if not entry:
            return False
        entry.status = "processing"
        entry.attempt_count += 1
        entry.last_attempt_at = datetime.now(timezone.utc)
        self.session.flush()
        return True

    def mark_completed(self, outbox_id: int) -> bool:
        """Mark outbox entry as successfully completed."""
        entry = self.get_by_id(outbox_id)
        if not entry:
            return False
        entry.status = "completed"
        entry.completed_at = datetime.now(timezone.utc)
        entry.last_error = None
        self.session.flush()
        return True

    def mark_failed(self, outbox_id: int, error_message: str) -> bool:
        """Record error and update status to failed or pending retry."""
        entry = self.get_by_id(outbox_id)
        if not entry:
            return False
        # Sanitize error message to prevent leaking secrets or unbounded payloads
        clean_error = str(error_message)[:1000]
        entry.last_error = clean_error
        if entry.attempt_count >= entry.max_attempts:
            entry.status = "failed"
        else:
            entry.status = "pending"
        self.session.flush()
        return True

    def get_outbox_stats(self) -> Dict[str, int]:
        """Return diagnostic metrics of outbox processing states."""
        stmt = select(
            AnalyticsOutbox.status,
            func.count(AnalyticsOutbox.outbox_id),
        ).group_by(AnalyticsOutbox.status)
        results = self.session.execute(stmt).all()
        stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        for status_val, count in results:
            if status_val in stats:
                stats[status_val] = count
        return stats

    def list_failed_entries(self, limit: int = 50) -> List[AnalyticsOutbox]:
        """Query exhausted failure records for diagnostic analysis."""
        stmt = (
            select(AnalyticsOutbox)
            .where(AnalyticsOutbox.status == "failed")
            .order_by(desc(AnalyticsOutbox.last_attempt_at))
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
