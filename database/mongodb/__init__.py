"""
MongoDB Atlas Analytics Package.
"""

from database.mongodb.client import (
    check_mongo_connectivity,
    close_mongo_client,
    ensure_indexes,
    get_mongo_client,
    get_mongo_database,
    sanitize_mongo_uri,
)
from database.mongodb.collections import (
    ALERT_INDEXES,
    ALERTS_COLLECTION,
    TELEMETRY_COLLECTION,
    TELEMETRY_INDEXES,
)
from database.mongodb.repositories import (
    AlertMirrorRepository,
    TelemetryMirrorRepository,
)

__all__ = [
    "get_mongo_client",
    "get_mongo_database",
    "close_mongo_client",
    "check_mongo_connectivity",
    "sanitize_mongo_uri",
    "ensure_indexes",
    "TELEMETRY_COLLECTION",
    "ALERTS_COLLECTION",
    "TELEMETRY_INDEXES",
    "ALERT_INDEXES",
    "TelemetryMirrorRepository",
    "AlertMirrorRepository",
]
