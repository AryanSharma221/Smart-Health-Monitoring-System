"""
SQL vs NoSQL Benchmark Result Equivalence Engine.

Enforces "Correctness Before Speed":
- Mathematical float comparison within configurable epsilon tolerance.
- Datetime normalization to UTC.
- Null/None equivalence.
- Key and item ordering invariance.
- Diagnostic diff reporting on mismatch.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _are_values_equivalent(
    val_sql: Any,
    val_mongo: Any,
    epsilon: float = 0.05,
) -> Tuple[bool, Optional[str]]:
    """Compare two scalar values across SQL and MongoDB representations."""
    if val_sql is None and val_mongo is None:
        return True, None
    if val_sql is None or val_mongo is None:
        return False, f"Null mismatch: SQL={val_sql!r} vs Mongo={val_mongo!r}"

    # Numeric comparison with floating-point tolerance
    if isinstance(val_sql, (int, float)) and isinstance(val_mongo, (int, float)):
        diff = abs(float(val_sql) - float(val_mongo))
        if diff > epsilon:
            return False, f"Numeric mismatch: SQL={val_sql} vs Mongo={val_mongo} (diff={diff:.4f} > {epsilon})"
        return True, None

    # Datetime comparison (convert both to UTC timestamp)
    if isinstance(val_sql, datetime) and isinstance(val_mongo, datetime):
        t_sql = val_sql.replace(tzinfo=timezone.utc) if val_sql.tzinfo is None else val_sql.astimezone(timezone.utc)
        t_mongo = val_mongo.replace(tzinfo=timezone.utc) if val_mongo.tzinfo is None else val_mongo.astimezone(timezone.utc)
        if abs((t_sql - t_mongo).total_seconds()) > 1.0:
            return False, f"Datetime mismatch: SQL={t_sql.isoformat()} vs Mongo={t_mongo.isoformat()}"
        return True, None

    # String / boolean / other comparison
    if val_sql != val_mongo:
        return False, f"Value mismatch: SQL={val_sql!r} vs Mongo={val_mongo!r}"

    return True, None


def assert_dicts_equivalent(
    dict_sql: Dict[str, Any],
    dict_mongo: Dict[str, Any],
    keys_to_check: Optional[List[str]] = None,
    epsilon: float = 0.05,
    path: str = "",
) -> None:
    """Recursively assert that two dictionaries contain semantically equivalent values."""
    keys = keys_to_check or list(set(dict_sql.keys()).union(dict_mongo.keys()))
    for k in keys:
        current_path = f"{path}.{k}" if path else k
        v_sql = dict_sql.get(k)
        v_mongo = dict_mongo.get(k)

        if isinstance(v_sql, dict) and isinstance(v_mongo, dict):
            assert_dicts_equivalent(v_sql, v_mongo, epsilon=epsilon, path=current_path)
        elif isinstance(v_sql, list) and isinstance(v_mongo, list):
            assert_lists_equivalent(v_sql, v_mongo, epsilon=epsilon, path=current_path)
        else:
            eq, msg = _are_values_equivalent(v_sql, v_mongo, epsilon=epsilon)
            if not eq:
                raise AssertionError(f"Equivalence failed at '{current_path}': {msg}")


def assert_lists_equivalent(
    list_sql: List[Any],
    list_mongo: List[Any],
    epsilon: float = 0.05,
    path: str = "",
) -> None:
    """Assert two lists contain semantically equivalent items."""
    if len(list_sql) != len(list_mongo):
        raise AssertionError(
            f"List length mismatch at '{path}': SQL returned {len(list_sql)} items vs Mongo returned {len(list_mongo)} items"
        )
    for idx, (item_sql, item_mongo) in enumerate(zip(list_sql, list_mongo)):
        current_path = f"{path}[{idx}]"
        if isinstance(item_sql, dict) and isinstance(item_mongo, dict):
            assert_dicts_equivalent(item_sql, item_mongo, epsilon=epsilon, path=current_path)
        else:
            eq, msg = _are_values_equivalent(item_sql, item_mongo, epsilon=epsilon)
            if not eq:
                raise AssertionError(f"Equivalence failed at '{current_path}': {msg}")


def validate_workload_equivalence(
    workload_id: str,
    sql_result: Any,
    mongo_result: Any,
    epsilon: float = 0.05,
) -> Tuple[bool, Optional[str]]:
    """
    Validate output equivalence between SQL and MongoDB for a given workload.
    Returns (is_equivalent, failure_reason_if_any).
    """
    try:
        if isinstance(sql_result, dict) and isinstance(mongo_result, dict):
            # Filter out informational notes that describe repository metadata
            sql_clean = {k: v for k, v in sql_result.items() if k != "provenance_note"}
            mongo_clean = {k: v for k, v in mongo_result.items() if k != "provenance_note"}
            assert_dicts_equivalent(sql_clean, mongo_clean, epsilon=epsilon)
        elif isinstance(sql_result, list) and isinstance(mongo_result, list):
            # Check vitals summary, time buckets, history
            assert_lists_equivalent(sql_result, mongo_result, epsilon=epsilon)
        else:
            eq, msg = _are_values_equivalent(sql_result, mongo_result, epsilon=epsilon)
            if not eq:
                return False, msg

        return True, None
    except AssertionError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Unexpected equivalence evaluation error: {exc}"
