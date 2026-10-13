"""
MongoDB Telemetry Mirror Repository.

Provides idempotent upsert, point queries, and time-series aggregations
for the telemetry_events collection in MongoDB Atlas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo.database import Database
from pymongo.errors import PyMongoError

from database.mongodb.collections import TELEMETRY_COLLECTION

logger = logging.getLogger(__name__)


class TelemetryMirrorRepository:
    """Encapsulates document operations for mirrored telemetry observations."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.collection = db[TELEMETRY_COLLECTION]

    def upsert_event(self, doc: Dict[str, Any]) -> bool:
        """
        Idempotently upsert a telemetry document using stable _id (event_id).
        Guarantees that repeated delivery of the same event updates rather than duplicates.
        """
        event_id = doc.get("_id") or doc.get("event_id")
        if not event_id:
            raise ValueError("Telemetry document must have a non-empty '_id' or 'event_id'.")

        doc["_id"] = str(event_id)
        doc["event_id"] = str(event_id)

        try:
            self.collection.replace_one(
                {"_id": doc["_id"]},
                doc,
                upsert=True,
            )
            return True
        except PyMongoError as exc:
            logger.error("Failed to upsert telemetry document %s: %s", event_id, exc)
            raise

    def get_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch single telemetry document by stable event_id."""
        return self.collection.find_one({"_id": str(event_id)})

    def find_by_patient(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query chronological telemetry events for a patient.
        Uses compound index (patient_id, measured_at DESC).
        """
        query: Dict[str, Any] = {"patient_id": patient_id}
        if start_time or end_time:
            time_filter: Dict[str, Any] = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query["measured_at"] = time_filter

        cursor = self.collection.find(query).sort("measured_at", -1).limit(limit)
        return list(cursor)

    def count_events(
        self,
        patient_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """Count matching telemetry documents."""
        query: Dict[str, Any] = {}
        if patient_id:
            query["patient_id"] = patient_id
        if source:
            query["source"] = source
        return self.collection.count_documents(query)
