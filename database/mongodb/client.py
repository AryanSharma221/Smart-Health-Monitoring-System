"""
Centralized MongoDB Atlas Client Lifecycle and Connection Provider.

Provides:
- Singleton client lifecycle management with timeouts.
- Safe diagnostic formatting (strictly redacts credentials).
- Index initialization for analytics collections.
- Non-blocking startup policy: application operates safely in degraded mode if Atlas is unavailable.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

import pymongo
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, PyMongoError

from database.mongodb.collections import (
    ALERT_INDEXES,
    ALERTS_COLLECTION,
    TELEMETRY_COLLECTION,
    TELEMETRY_INDEXES,
)
from services.api.config import Settings, get_settings

logger = logging.getLogger(__name__)

_mongo_client: Optional[MongoClient] = None


def sanitize_mongo_uri(uri: str) -> str:
    """
    Redact credentials and query string secrets from a MongoDB connection string.
    Example: mongodb+srv://user:pass@cluster.mongodb.net/db -> mongodb+srv://***:***@cluster.mongodb.net/db
    """
    if not uri:
        return "<not-configured>"
    try:
        pattern = r"^(?P<scheme>[^:]+)://(?P<user>[^:]+):(?P<pass>.+)@(?P<host>[^/@?#]+)(?P<rest>.*)$"
        match = re.match(pattern, uri)
        if match:
            return f"{match.group('scheme')}://***:***@{match.group('host')}{match.group('rest')}"
        return re.sub(r"://([^:]+):(.*)@", r"://***:***@", uri)
    except Exception:
        return "<redacted-uri>"


def get_mongo_client(settings: Optional[Settings] = None) -> Optional[MongoClient]:
    """
    Retrieve or initialize the centralized PyMongo MongoClient.
    Returns None if MONGODB_URI is not configured (offline / local development mode).
    """
    global _mongo_client
    if _mongo_client is not None:
        return _mongo_client

    app_settings = settings or get_settings()
    if not app_settings.mongodb_uri:
        logger.debug("MongoDB Atlas URI not configured. Running in offline/relational-only mode.")
        return None

    try:
        clean_uri = sanitize_mongo_uri(app_settings.mongodb_uri)
        logger.info("Initializing MongoDB Atlas client for endpoint: %s", clean_uri)
        _mongo_client = MongoClient(
            app_settings.mongodb_uri,
            serverSelectionTimeoutMS=app_settings.mongodb_server_selection_timeout_ms,
            connectTimeoutMS=app_settings.mongodb_connect_timeout_ms,
            appname=app_settings.app_name,
        )
        return _mongo_client
    except Exception as exc:
        logger.error("Failed to construct MongoDB client: %s", str(exc))
        return None


def get_mongo_database(settings: Optional[Settings] = None) -> Optional[Database]:
    """
    Retrieve the configured analytics Database handle.
    Returns None if client is unavailable or unconfigured.
    """
    client = get_mongo_client(settings=settings)
    if client is None:
        return None
    app_settings = settings or get_settings()
    return client[app_settings.mongodb_database]


def check_mongo_connectivity(settings: Optional[Settings] = None) -> Tuple[bool, str]:
    """
    Verify live connectivity to MongoDB Atlas by executing a ping command.
    Returns (is_connected, safe_status_description).
    """
    app_settings = settings or get_settings()
    if not app_settings.mongodb_uri:
        return False, "not_configured"

    client = get_mongo_client(settings=app_settings)
    if client is None:
        return False, "client_initialization_failed"

    try:
        client.admin.command("ping")
        return True, "connected"
    except ConnectionFailure as exc:
        logger.warning("MongoDB ping failed: ConnectionFailure (%s)", str(exc)[:200])
        return False, f"connection_failure: {str(exc)[:100]}"
    except PyMongoError as exc:
        logger.warning("MongoDB ping failed: PyMongoError (%s)", str(exc)[:200])
        return False, f"driver_error: {str(exc)[:100]}"
    except Exception as exc:
        logger.warning("MongoDB ping unexpected error: %s", str(exc)[:200])
        return False, f"error: {str(exc)[:100]}"


def ensure_indexes(db: Database) -> Dict[str, List[str]]:
    """
    Create necessary compound and single-field indexes on analytics collections.
    Returns a dictionary of collection_name -> list_of_created_index_names.
    """
    created_indexes: Dict[str, List[str]] = {
        TELEMETRY_COLLECTION: [],
        ALERTS_COLLECTION: [],
    }

    # 1. Telemetry collection indexes
    telemetry_col = db[TELEMETRY_COLLECTION]
    for idx_spec in TELEMETRY_INDEXES:
        name = telemetry_col.create_index(
            idx_spec["keys"],
            name=idx_spec["name"],
            unique=idx_spec.get("unique", False),
            background=True,
        )
        created_indexes[TELEMETRY_COLLECTION].append(name)

    # 2. Alert collection indexes
    alert_col = db[ALERTS_COLLECTION]
    for idx_spec in ALERT_INDEXES:
        name = alert_col.create_index(
            idx_spec["keys"],
            name=idx_spec["name"],
            unique=idx_spec.get("unique", False),
            background=True,
        )
        created_indexes[ALERTS_COLLECTION].append(name)

    logger.info("Successfully verified MongoDB analytics indexes on %s", list(created_indexes.keys()))
    return created_indexes


def close_mongo_client() -> None:
    """Close active client connection pool and release resources."""
    global _mongo_client
    if _mongo_client is not None:
        logger.info("Closing MongoDB Atlas connection pool.")
        try:
            _mongo_client.close()
        except Exception as exc:
            logger.warning("Error closing MongoDB client: %s", exc)
        finally:
            _mongo_client = None
