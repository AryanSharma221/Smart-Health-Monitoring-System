"""
Query Plan and Index Usage Inspection for MySQL and MongoDB.

Captures empirical evidence of index utilization:
- MySQL: EXPLAIN FORMAT=JSON / EXPLAIN QUERY PLAN (identifying key used, type, rows examined).
- MongoDB: .explain("executionStats") (identifying IXSCAN vs COLLSCAN, keysExamined, docsExamined).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from pymongo.collection import Collection
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def capture_mysql_plan(
    session: Session,
    sql_query_text: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Capture execution plan for a SQL query in MySQL (or SQLite fallback).
    """
    bind = getattr(session, "bind", None)
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "mysql")

    plan_info: Dict[str, Any] = {
        "engine": dialect_name,
        "raw_plan": None,
        "index_used": None,
        "access_type": None,
        "rows_examined": None,
    }

    try:
        if dialect_name == "mysql":
            explain_sql = f"EXPLAIN FORMAT=JSON {sql_query_text}"
            res = session.execute(text(explain_sql), params or {}).scalar()
            if isinstance(res, str):
                try:
                    plan_json = json.loads(res)
                    plan_info["raw_plan"] = plan_json
                    query_block = plan_json.get("query_block", {})
                    table_info = query_block.get("table", {})
                    plan_info["index_used"] = table_info.get("key")
                    plan_info["access_type"] = table_info.get("access_type")
                    plan_info["rows_examined"] = table_info.get("rows_examined_per_scan")
                except Exception:
                    plan_info["raw_plan"] = res
            else:
                plan_info["raw_plan"] = str(res)
        elif dialect_name == "sqlite":
            explain_sql = f"EXPLAIN QUERY PLAN {sql_query_text}"
            rows = session.execute(text(explain_sql), params or {}).all()
            plan_lines = [f"{r[0]}|{r[1]}|{r[2]}|{r[3]}" if len(r) >= 4 else str(r) for r in rows]
            plan_info["raw_plan"] = "\n".join(plan_lines)
            for line in plan_lines:
                if "USING INDEX" in line:
                    plan_info["index_used"] = line.split("USING INDEX")[-1].strip()
                    plan_info["access_type"] = "INDEX SCAN/SEEK"
                elif "SCAN" in line:
                    plan_info["access_type"] = "SCAN TABLE"
    except Exception as exc:
        logger.debug("Could not capture SQL query plan: %s", exc)
        plan_info["error"] = str(exc)

    return plan_info


def capture_mongo_plan(
    collection: Collection,
    pipeline_or_filter: Any,
    is_aggregation: bool = True,
) -> Dict[str, Any]:
    """
    Capture execution statistics and stage details from MongoDB Atlas.
    """
    plan_info: Dict[str, Any] = {
        "engine": "mongodb",
        "stage": "UNKNOWN",
        "total_keys_examined": 0,
        "total_docs_examined": 0,
        "execution_time_millis": 0,
        "is_mock": False,
    }

    # Check for mongomock
    if type(collection).__module__.startswith("mongomock"):
        plan_info["is_mock"] = True
        plan_info["stage"] = "MONGOMOCK_IN_MEMORY"
        plan_info["note"] = "In-memory mock execution; live Atlas executionStats requires live cluster connection."
        return plan_info

    try:
        if is_aggregation:
            db = collection.database
            explain_cmd = {
                "explain": {
                    "aggregate": collection.name,
                    "pipeline": pipeline_or_filter,
                    "cursor": {},
                },
                "verbosity": "executionStats",
            }
            explain_res = db.command(explain_cmd)
        else:
            explain_res = collection.find(pipeline_or_filter).explain("executionStats")

        plan_info["raw_plan"] = explain_res
        exec_stats = explain_res.get("executionStats", {})
        plan_info["total_keys_examined"] = exec_stats.get("totalKeysExamined", 0)
        plan_info["total_docs_examined"] = exec_stats.get("totalDocsExamined", 0)
        plan_info["execution_time_millis"] = exec_stats.get("executionTimeMillis", 0)

        # Extract winning plan stage
        query_planner = explain_res.get("queryPlanner", {})
        winning_plan = query_planner.get("winningPlan", {})
        plan_info["stage"] = winning_plan.get("stage", "AGGREGATION_PIPELINE")
        input_stage = winning_plan.get("inputStage", {})
        if "stage" in input_stage:
            plan_info["stage"] = f"{plan_info['stage']} -> {input_stage['stage']}"
    except Exception as exc:
        logger.debug("Could not capture MongoDB explain plan: %s", exc)
        plan_info["error"] = str(exc)

    return plan_info
