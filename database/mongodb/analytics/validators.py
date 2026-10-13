"""
Input Validation and Normalization for MongoDB Analytics Workloads.

Guarantees:
- Strict parameter validation preventing NoSQL / pipeline injection.
- Consistent UTC datetime coercion and interval boundary validation.
- Boundary enforcement for pagination and result limits.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Set, Tuple

PATIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_TIME_BUCKET_INTERVALS: Set[str] = {"hour", "day"}
MAX_QUERY_LIMIT: int = 1000
DEFAULT_QUERY_LIMIT: int = 100


def validate_patient_id(patient_id: str) -> str:
    """
    Validate and sanitize patient domain identifier.
    Must be a non-empty alphanumeric string matching ^[A-Za-z0-9_-]{1,64}$.
    Rejects dictionaries, injection operators, or invalid characters.
    """
    if not isinstance(patient_id, str):
        raise ValueError(f"patient_id must be a string, got {type(patient_id).__name__}")
    
    clean_id = patient_id.strip()
    if not clean_id:
        raise ValueError("patient_id cannot be empty or whitespace only")
    
    if not PATIENT_ID_PATTERN.match(clean_id):
        raise ValueError(
            f"Invalid patient_id format '{clean_id}'. "
            "Must be 1-64 characters containing only alphanumeric characters, underscores, or hyphens."
        )
    return clean_id


def normalize_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize datetime object to UTC timezone.
    If datetime is naive, assign UTC timezone.
    If datetime has a non-UTC timezone, convert it to UTC.
    """
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        raise ValueError(f"Expected datetime object, got {type(dt).__name__}")
    
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_time_range(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Validate and normalize start and end datetime bounds.
    Enforces that start_time <= end_time.
    """
    norm_start = normalize_datetime(start_time)
    norm_end = normalize_datetime(end_time)

    if norm_start is not None and norm_end is not None:
        if norm_start > norm_end:
            raise ValueError(
                f"start_time ({norm_start.isoformat()}) must be less than or equal to end_time ({norm_end.isoformat()})"
            )

    return norm_start, norm_end


def validate_bucket_interval(interval: str) -> str:
    """
    Validate time bucket aggregation interval.
    Allowed values: {'hour', 'day'}.
    """
    if not isinstance(interval, str):
        raise ValueError(f"interval must be a string, got {type(interval).__name__}")
    
    clean_interval = interval.strip().lower()
    if clean_interval not in ALLOWED_TIME_BUCKET_INTERVALS:
        raise ValueError(
            f"Invalid time bucket interval '{interval}'. Allowed values are: {sorted(ALLOWED_TIME_BUCKET_INTERVALS)}"
        )
    return clean_interval


def validate_pagination(
    limit: int = DEFAULT_QUERY_LIMIT,
    offset: int = 0,
    max_limit: int = MAX_QUERY_LIMIT,
) -> Tuple[int, int]:
    """
    Validate bounded limit and non-negative offset for pagination.
    """
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit must be a positive integer >= 1, got {limit}")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError(f"offset must be a non-negative integer >= 0, got {offset}")
    
    bounded_limit = min(limit, max_limit)
    return bounded_limit, offset
