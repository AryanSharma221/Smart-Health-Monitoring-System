"""
MongoDB Clinical Alerts Mirror Repository.

Provides idempotent upsert, out-of-order state conflict resolution,
and filtered queries for the alert_events collection in MongoDB Atlas.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pymongo.database import Database
from pymongo.errors import PyMongoError

from database.mongodb.collections import ALERT_STATUS_RANKS, ALERTS_COLLECTION

logger = logging.getLogger(__name__)


class AlertMirrorRepository:
    """Encapsulates document operations for mirrored clinical alerts."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.collection = db[ALERTS_COLLECTION]

    def upsert_alert(self, doc: Dict[str, Any]) -> bool:
        """
        Idempotently upsert an alert document with out-of-order state protection.
        
        Conflict Policy:
        - Alert state transitions are monotonic: NEW (1) -> ACKNOWLEDGED (2) -> RESOLVED (3).
        - If an existing document has a higher state_rank than the incoming document,
          the existing status and acknowledgement/resolution timestamps are preserved.
        """
        alert_id = doc.get("_id") or doc.get("alert_id")
        if not alert_id:
            raise ValueError("Alert document must have a non-empty '_id' or 'alert_id'.")

        doc["_id"] = str(alert_id)
        doc["alert_id"] = str(alert_id)

        incoming_status = doc.get("status", "NEW")
        incoming_rank = ALERT_STATUS_RANKS.get(incoming_status, 1)
        doc["state_rank"] = incoming_rank

        try:
            existing = self.collection.find_one({"_id": doc["_id"]})
            if existing is not None:
                existing_rank = existing.get("state_rank", 1)
                if incoming_rank < existing_rank:
                    logger.warning(
                        "Out-of-order alert event for %s: incoming status '%s' (rank %d) < existing '%s' (rank %d). "
                        "Preserving existing status and lifecycle timestamps.",
                        alert_id,
                        incoming_status,
                        incoming_rank,
                        existing.get("status"),
                        existing_rank,
                    )
                    # Preserve existing status and lifecycle attributes
                    doc["status"] = existing.get("status")
                    doc["state_rank"] = existing_rank
                    doc["acknowledged_by"] = existing.get("acknowledged_by")
                    doc["acknowledged_at"] = existing.get("acknowledged_at")
                    doc["resolved_by"] = existing.get("resolved_by")
                    doc["resolved_at"] = existing.get("resolved_at")

            self.collection.replace_one(
                {"_id": doc["_id"]},
                doc,
                upsert=True,
            )
            return True
        except PyMongoError as exc:
            logger.error("Failed to upsert alert document %s: %s", alert_id, exc)
            raise

    def get_by_id(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Fetch single alert document by stable alert_id."""
        return self.collection.find_one({"_id": str(alert_id)})

    def find_by_patient(
        self,
        patient_id: str,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query alerts for a patient filtered by status."""
        query: Dict[str, Any] = {"patient_id": patient_id}
        if status:
            query["status"] = status
        cursor = self.collection.find(query).sort("created_at", -1).limit(limit)
        return list(cursor)

    def count_alerts(
        self,
        patient_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count matching alert documents."""
        query: Dict[str, Any] = {}
        if patient_id:
            query["patient_id"] = patient_id
        if status:
            query["status"] = status
        return self.collection.count_documents(query)
