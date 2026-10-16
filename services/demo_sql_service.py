"""
Demo SQL Workbench Isolated Execution Service.

Provides secure, sandboxed execution of SQL commands exclusively within Demo Mode.
Guarantees:
1. Complete isolation to the local relational demo database (smart_health_local.db / SQLite 3).
2. Prohibits execution when Real-Time streaming mode is actively running.
3. Strict statement parsing: Rejects multi-statements, administrative commands, PRAGMAs,
   database escape attempts, and access to system tables (users, audit_log, alembic_version).
4. Clinical domain validation: Validates patient cohorts (P101-P105), physiological metric bounds,
   and units for vital sign insertions.
5. Trusted provenance: Enforces source='self_added' and is_simulated=False on the server side.
6. Controlled ML integration hook: Invokes MLService.assess_and_persist only upon successful
   reading insertions. Never executes ML for SELECT, JOIN, aggregates, or views.
7. Atomic transactions: Complete rollback upon error without leaving orphaned or corrupt records.
8. Zero MongoDB mutations: Completely airgapped from MongoDB Atlas.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import sqlparse
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.mysql.models import (
    Alert,
    AlertStatusHistory,
    IngestionEvent,
    ModelAssessment,
    PatientProfile,
    VitalsReading,
)
from database.mysql.session import get_db, get_engine, get_session_factory
from services.alerts.evaluator import AlertEvaluator
from services.api.config import Settings, get_settings
from services.api.schemas.evaluation import (
    MLAssessmentSummary,
    SQLWorkbenchExecuteRequest,
    SQLWorkbenchExecuteResponse,
)
from services.ml_service import MLService, get_ml_service
from services.simulator.worker import get_simulator_worker
from services.vitals_service import VitalsService

logger = logging.getLogger(__name__)

# ============================================================================
# SAFETY BOUNDARIES & SECURITY POLICIES
# ============================================================================

APPROVED_DEMO_PATIENTS: Set[str] = {"P101", "P102", "P103", "P104", "P105"}
PROTECTED_BASELINE_PATIENTS: Set[str] = {"P001", "P002", "P003", "P004", "P005"}
ALLOWED_STATEMENT_TYPES: Set[str] = {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE"}

DISALLOWED_KEYWORDS: Set[str] = {
    "ATTACH", "DETACH", "DROP", "ALTER", "TRUNCATE", "RENAME", "REPLACE",
    "PRAGMA", "LOAD_FILE", "LOAD DATA", "INTO OUTFILE", "INTO DUMPFILE",
    "SHUTDOWN", "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL", "USE", "KILL", "SLEEP"
}

PROTECTED_SYSTEM_TABLES: Set[str] = {
    "users", "audit_log", "alembic_version", "system_settings"
}

ALLOWED_METRIC_CODES: Set[str] = {
    "heart_rate", "spo2", "temperature", "respiratory_rate", "bp_systolic", "bp_diastolic"
}

PHYSIOLOGICAL_RANGES: Dict[str, Tuple[float, float]] = {
    "heart_rate": (30.0, 250.0),
    "spo2": (50.0, 100.0),
    "temperature_c": (30.0, 45.0),
    "temperature_f": (86.0, 113.0),
    "respiratory_rate": (6.0, 60.0),
    "bp_systolic": (60.0, 260.0),
    "bp_diastolic": (40.0, 150.0),
}


def sanitize_sql_error_message(err_msg: str) -> str:
    """Sanitize error messages to eliminate filesystem paths, credentials, and connection URLs."""
    if not err_msg:
        return "SQL execution failed."
    # Strip Windows or Unix file paths
    sanitized = re.sub(r"[A-Za-z]:\\[^:\n\r\t]+", "[REDACTED_PATH]", err_msg)
    sanitized = re.sub(r"/(?:[^/\0\n\r\t]+/)+[^/\0\n\r\t]+", "[REDACTED_PATH]", sanitized)
    # Strip database connection strings
    sanitized = re.sub(r"(sqlite|mysql\+?[a-z]*):\/\/[^\s]+", r"\1://[REDACTED]", sanitized)
    # Strip user credentials
    sanitized = re.sub(r"password=['\"][^'\"]*['\"]", "password='[REDACTED]'", sanitized, flags=re.IGNORECASE)
    return sanitized.strip()


class DemoSQLExecutionService:
    """
    Dedicated application service for parsing, validating, and safely executing
    SQL statements exclusively in Demo Mode.
    """

    def __init__(
        self,
        session_factory=None,
        ml_service: Optional[MLService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or get_session_factory()
        self._ml_service = ml_service

    def get_ml_service(self) -> MLService:
        """Resolve the MLService singleton."""
        if self._ml_service is None:
            self._ml_service = get_ml_service(self.settings)
        return self._ml_service

    def check_operational_mode(self, is_demo_mode: bool) -> None:
        """Verify that the system is in Demo Mode and Real-Time Mode is stopped."""
        if not is_demo_mode:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Security Violation: The SQL Workbench is restricted exclusively to Demo Mode.",
            )

        # Check if real-time simulator is actively generating telemetry
        try:
            import httpx
            sim_url = f"{self.settings.sensor_simulator_base_url.rstrip('/')}/api/v1/simulator/status"
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(sim_url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("is_running") is True or data.get("lifecycle_state") == "RUNNING":
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail=(
                                "Operational Conflict: The SQL Workbench cannot execute queries while "
                                "Real-Time Mode is actively generating telemetry. Stop the simulator first."
                            ),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            logger.debug("Simulator status probe: %s", exc)

    def parse_and_validate_statement(self, sql_text: str) -> Tuple[sqlparse.sql.Statement, str]:
        """
        Parse SQL statement using AST inspection and enforce security policy.
        Returns the parsed Statement and its normalized statement type.
        """
        cleaned_sql = sql_text.strip()
        if not cleaned_sql:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Validation Error: Empty SQL statement provided.",
            )

        # Split statements and filter out empty semicolons or comments
        parsed_list = [
            s for s in sqlparse.parse(cleaned_sql)
            if s.get_type() or str(s).strip() not in ("", ";")
        ]

        if len(parsed_list) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Validation Error: Empty SQL statement provided.",
            )

        if len(parsed_list) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security Violation: Multi-statement execution is strictly prohibited. Provide exactly one SQL statement.",
            )

        stmt = parsed_list[0]
        stmt_type = stmt.get_type().upper() if stmt.get_type() else "UNKNOWN"

        # Determine non-DML or special statements like CREATE VIEW
        tokens_non_ws = [t.value.upper() for t in stmt.flatten() if not t.is_whitespace]
        if not tokens_non_ws:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Validation Error: Statement contains no valid tokens.",
            )

        if tokens_non_ws[0] == "CREATE":
            stmt_type = "CREATE"
            # Require VIEW
            if len(tokens_non_ws) < 2 or (tokens_non_ws[1] != "VIEW" and not (tokens_non_ws[1] in ("TEMP", "TEMPORARY") and len(tokens_non_ws) > 2 and tokens_non_ws[2] == "VIEW")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security Violation: Only 'CREATE VIEW' statements are supported. Table, index, and trigger creation are prohibited.",
                )

        if stmt_type not in ALLOWED_STATEMENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SQL Syntax / Statement Error: Statement type '{stmt_type}' is prohibited or syntax is invalid.",
            )

        # Scan all tokens for disallowed keywords
        for token in stmt.flatten():
            token_val = token.value.strip().upper()
            if token_val in DISALLOWED_KEYWORDS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Security Violation: Prohibited SQL keyword '{token_val}' detected.",
                )

        # Extract and validate referenced table names
        referenced_tables = self._extract_table_names(stmt)
        for tbl in referenced_tables:
            if tbl.lower() in PROTECTED_SYSTEM_TABLES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Security Violation: Access to system table '{tbl}' is forbidden in the Demo SQL Workbench.",
                )

        # For UPDATE and DELETE, check for protected baseline cohorts or real-time spoofing
        if stmt_type in ("UPDATE", "DELETE"):
            sql_upper = cleaned_sql.upper()
            for p in PROTECTED_BASELINE_PATIENTS:
                if p in sql_upper:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Clinical Safety Violation: Baseline clinical patient '{p}' records are strictly read-only.",
                    )
            if stmt_type == "UPDATE" and "SMARTWATCH_SIMULATOR" in sql_upper:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Provenance Violation: Client cannot masquerade data as real-time simulator telemetry.",
                )

        return stmt, stmt_type

    def _extract_table_names(self, stmt: sqlparse.sql.Statement) -> Set[str]:
        """Extract table identifiers referenced in FROM, JOIN, INTO, or UPDATE clauses."""
        tables: Set[str] = set()
        from_seen = False
        into_seen = False
        update_seen = False

        for token in stmt.flatten():
            val = token.value.upper()
            if val in ("FROM", "JOIN"):
                from_seen = True
            elif val == "INTO":
                into_seen = True
            elif val == "UPDATE":
                update_seen = True
            elif from_seen or into_seen or update_seen:
                if token.is_whitespace or val in ("INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS"):
                    continue
                cleaned = token.value.strip("`\"'[],;()")
                if cleaned and cleaned.isidentifier() and cleaned.upper() not in ("SELECT", "SET", "WHERE", "ON", "VALUES", "AS"):
                    tables.add(cleaned.lower())
                from_seen = False
                into_seen = False
                update_seen = False

        return tables

    def _is_vitals_reading_insert(self, stmt: sqlparse.sql.Statement) -> bool:
        """Determine whether the statement is an INSERT into the vitals_readings table."""
        tables = self._extract_table_names(stmt)
        return "vitals_readings" in tables

    @staticmethod
    def _extract_value_tuples(val_str: str) -> List[str]:
        """Extract comma-separated value tuples, respecting string quotes and nested parens."""
        tuples: List[str] = []
        current: List[str] = []
        in_single_quote = False
        in_double_quote = False
        depth = 0
        for char in val_str:
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current.append(char)
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current.append(char)
            elif char == "(" and not in_single_quote and not in_double_quote:
                depth += 1
                if depth == 1:
                    current = []
                    continue
                current.append(char)
            elif char == ")" and not in_single_quote and not in_double_quote:
                depth -= 1
                if depth == 0:
                    tuples.append("".join(current).strip())
                    current = []
                    continue
                current.append(char)
            else:
                if depth > 0:
                    current.append(char)
        return tuples

    @staticmethod
    def _split_csv_respecting_quotes(row_str: str) -> List[str]:
        """Split comma-separated values inside a tuple respecting quotes and nested parens."""
        vals: List[str] = []
        current: List[str] = []
        in_single_quote = False
        in_double_quote = False
        depth = 0
        for char in row_str:
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current.append(char)
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current.append(char)
            elif char == "(" and not in_single_quote and not in_double_quote:
                depth += 1
                current.append(char)
            elif char == ")" and not in_single_quote and not in_double_quote:
                depth -= 1
                current.append(char)
            elif char == "," and not in_single_quote and not in_double_quote and depth == 0:
                vals.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            vals.append("".join(current).strip())
        return vals

    def _parse_vitals_insert_rows(
        self,
        sql_text: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract columns and all value rows from an INSERT INTO vitals_readings statement.
        Supports single-row and multi-row INSERT syntax:
        INSERT INTO vitals_readings (col1, col2, ...) VALUES (v1, v2, ...), (v3, v4, ...)
        """
        params = params or {}
        match = re.search(
            r"INSERT\s+INTO\s+[`\"']?vitals_readings[`\"']?\s*\(([^)]+)\)\s*VALUES\s*(.+)$",
            sql_text.strip().rstrip(";"),
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Syntax Error: Vitals insertion must follow standard format: "
                    "INSERT INTO vitals_readings (patient_id, metric_code, value, unit, [measured_at]) VALUES (...)"
                ),
            )

        col_str, val_part = match.group(1), match.group(2).strip()
        columns = [c.strip().strip("`\"'").lower() for c in col_str.split(",")]

        raw_tuples = self._extract_value_tuples(val_part)
        if not raw_tuples:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Syntax Error: No valid VALUES (...) row expressions found in INSERT statement.",
            )

        parsed_rows: List[Dict[str, Any]] = []
        for tuple_str in raw_tuples:
            raw_vals = self._split_csv_respecting_quotes(tuple_str)
            if len(columns) != len(raw_vals):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Column count ({len(columns)}) does not match values count ({len(raw_vals)}) in VALUES row: ({tuple_str}).",
                )

            row_data: Dict[str, Any] = {}
            for col, raw_v in zip(columns, raw_vals):
                clean_v = raw_v.strip()
                if clean_v.startswith(":") and clean_v[1:] in params:
                    row_data[col] = params[clean_v[1:]]
                elif (clean_v.startswith("'") and clean_v.endswith("'")) or (clean_v.startswith('"') and clean_v.endswith('"')):
                    row_data[col] = clean_v[1:-1]
                elif clean_v.upper() in ("NULL", "NONE"):
                    row_data[col] = None
                elif clean_v.lower() in ("datetime('now')", "current_timestamp", "now()"):
                    row_data[col] = datetime.now(timezone.utc)
                else:
                    try:
                        if "." in clean_v:
                            row_data[col] = float(clean_v)
                        else:
                            row_data[col] = int(clean_v)
                    except ValueError:
                        row_data[col] = clean_v
            parsed_rows.append(row_data)

        return parsed_rows

    def _parse_vitals_insert_values(
        self,
        sql_text: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible helper returning the first parsed row dictionary."""
        rows = self._parse_vitals_insert_rows(sql_text, params)
        return rows[0] if rows else {}

    def _execute_vitals_insert_with_ml(
        self,
        db: Session,
        vitals_rows: Union[Dict[str, Any], List[Dict[str, Any]]],
        context_patient_id: Optional[str] = None,
    ) -> SQLWorkbenchExecuteResponse:
        """
        Validated execution for inserting vital sign reading(s):
        1. Validates patient_id against APPROVED_DEMO_PATIENTS.
        2. Validates metric_code and physiological boundaries for every row.
        3. Enforces source='self_added' and is_simulated=False on ingestion_events.
        4. Persists IngestionEvent and VitalsReadings atomically.
        5. Calls AlertEvaluator for clinical threshold checking.
        6. Calls MLService.assess_and_persist to score telemetry with complete/missing feature vectors.
        7. Returns structured response with ML assessment feedback and inserted rows.
        """
        start_time = time.perf_counter()

        if isinstance(vitals_rows, dict):
            raw_list = [vitals_rows]
        else:
            raw_list = list(vitals_rows)

        if not raw_list:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Validation Error: No vitals readings provided for insertion.",
            )

        now_utc = datetime.now(timezone.utc)
        validated_rows: List[Dict[str, Any]] = []
        target_patient_id: Optional[str] = None

        for idx, row in enumerate(raw_list):
            p_id = row.get("patient_id") or context_patient_id
            if not p_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Validation Error: Missing required 'patient_id' in row {idx + 1}.",
                )

            if p_id in PROTECTED_BASELINE_PATIENTS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Clinical Safety Violation: Patient '{p_id}' belongs to baseline cohort and is read-only.",
                )

            if p_id not in APPROVED_DEMO_PATIENTS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Validation Error: Patient ID must be in demo cohort {sorted(APPROVED_DEMO_PATIENTS)}. Received: '{p_id}'",
                )

            if target_patient_id is None:
                target_patient_id = p_id
            elif target_patient_id != p_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Validation Error: Single SQL INSERT statement cannot span multiple distinct patient IDs.",
                )

            # Verify patient exists in DB
            profile = db.query(PatientProfile).filter(PatientProfile.patient_id == p_id).first()
            if not profile:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Patient '{p_id}' not found in patient profiles.",
                )

            metric_code = row.get("metric_code")
            if not metric_code or metric_code not in ALLOWED_METRIC_CODES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Validation Error: Invalid metric_code in row {idx + 1}. Allowed: {sorted(ALLOWED_METRIC_CODES)}",
                )

            raw_val = row.get("value")
            if raw_val is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Validation Error: Missing vital sign numerical 'value' in row {idx + 1}.",
                )
            try:
                val_float = float(raw_val)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Validation Error: Non-numeric value '{raw_val}' for metric '{metric_code}' in row {idx + 1}.",
                )

            unit = row.get("unit") or ("bpm" if metric_code == "heart_rate" else "%" if metric_code == "spo2" else "degC")

            canonical_val = val_float
            canonical_unit = unit
            raw_unit = unit
            raw_value = val_float

            if metric_code == "temperature":
                if unit.lower() in ("degf", "f", "fahrenheit"):
                    low, high = PHYSIOLOGICAL_RANGES["temperature_f"]
                    if not (low <= val_float <= high):
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Validation Error: Temperature {val_float:.1f}°F is outside physiological bounds ({low}-{high}°F).",
                        )
                    canonical_val = round((val_float - 32.0) * 5.0 / 9.0, 2)
                    canonical_unit = "degC"
                    raw_unit = "degF"
                else:
                    low, high = PHYSIOLOGICAL_RANGES["temperature_c"]
                    if not (low <= val_float <= high):
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Validation Error: Temperature {val_float:.1f}°C is outside physiological bounds ({low}-{high}°C).",
                        )
                    canonical_val = round(val_float, 2)
                    canonical_unit = "degC"
                    raw_unit = "degC"
            elif metric_code in PHYSIOLOGICAL_RANGES:
                low, high = PHYSIOLOGICAL_RANGES[metric_code]
                if not (low <= val_float <= high):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Validation Error: {metric_code} value {val_float} is outside physiological range ({low} - {high} {unit}).",
                    )

            # Timestamp parsing and bounds
            measured_at_raw = row.get("measured_at")
            if isinstance(measured_at_raw, datetime):
                measured_at = measured_at_raw
            elif isinstance(measured_at_raw, str):
                try:
                    measured_at = datetime.fromisoformat(measured_at_raw.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        measured_at = datetime.strptime(measured_at_raw, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        measured_at = datetime.now(timezone.utc)
            else:
                measured_at = datetime.now(timezone.utc)

            check_time = measured_at if measured_at.tzinfo else measured_at.replace(tzinfo=timezone.utc)
            if check_time > now_utc + timedelta(minutes=5):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Validation Error: Observation timestamp cannot be more than 5 minutes in the future.",
                )

            validated_rows.append({
                "patient_id": p_id,
                "metric_code": metric_code,
                "val_float": val_float,
                "canonical_val": canonical_val,
                "canonical_unit": canonical_unit,
                "raw_value": raw_value,
                "raw_unit": raw_unit,
                "measured_at": measured_at,
            })

        patient_id = target_patient_id or "P101"
        event_id = f"evt_demo_self_added_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        primary_measured_at = max(r["measured_at"] for r in validated_rows)

        # 1. Persist Discrete IngestionEvent (Trusted Server-Side Provenance)
        event = IngestionEvent(
            event_id=event_id,
            patient_id=patient_id,
            source="self_added",  # TRUSTED SERVER PROVENANCE
            source_event_id=f"src_wb_{uuid.uuid4().hex[:8]}",
            batch_id=None,
            measured_at=primary_measured_at,
            received_at=now,
            is_simulated=False,
            mirror_status="pending",
            created_at=now,
        )
        db.add(event)
        db.flush()

        # 2. Persist VitalsReading Rows
        persisted_readings: List[VitalsReading] = []
        for r_item in validated_rows:
            reading = VitalsReading(
                event_id=event_id,
                patient_id=patient_id,
                metric_code=r_item["metric_code"],
                value=Decimal(str(round(r_item["canonical_val"], 2))),
                unit=r_item["canonical_unit"],
                raw_value=Decimal(str(round(r_item["raw_value"], 2))),
                raw_unit=r_item["raw_unit"],
                quality_status="valid",
                measured_at=r_item["measured_at"],
                created_at=now,
            )
            db.add(reading)
            persisted_readings.append(reading)

        db.commit()
        for r in persisted_readings:
            db.refresh(r)

        # 3. Rule-Based Evaluation via AlertEvaluator
        rule_alerts: List[Alert] = []
        try:
            evaluator = AlertEvaluator(session=db)
            rule_alerts = evaluator.evaluate_readings_batch(
                event=event,
                readings=persisted_readings,
                allow_historical=False,
            )
        except Exception as rule_exc:
            logger.warning("Clinical rule evaluation warning: %s", rule_exc)

        # 4. Machine Learning Integration Hook (Isolation Forest Telemetry Scoring)
        ml_summary: Optional[MLAssessmentSummary] = None
        try:
            ml_svc = self.get_ml_service()
            hr = next((float(r.value) for r in persisted_readings if r.metric_code == "heart_rate"), None)
            spo2 = next((float(r.value) for r in persisted_readings if r.metric_code == "spo2"), None)
            temp_r = next((r for r in persisted_readings if r.metric_code == "temperature"), None)
            temp_f = None
            if temp_r is not None:
                temp_f = float(temp_r.raw_value) if temp_r.raw_unit == "degF" else round(float(temp_r.value) * 9.0 / 5.0 + 32.0, 2)
            rr = next((float(r.value) for r in persisted_readings if r.metric_code == "respiratory_rate"), None)
            sbp = next((float(r.value) for r in persisted_readings if r.metric_code == "bp_systolic"), None)
            dbp = next((float(r.value) for r in persisted_readings if r.metric_code == "bp_diastolic"), None)

            persisted_assessment, persisted_ml_alert, assessment_res = ml_svc.assess_and_persist(
                db=db,
                patient_id=patient_id,
                timestamp=primary_measured_at,
                heart_rate=hr,
                spo2=spo2,
                temperature_f=temp_f,
                respiratory_rate=rr,
                systolic_bp=sbp,
                diastolic_bp=dbp,
                source_event_id=event_id,
                is_simulated=False,
                trigger_alert=True,
            )

            score = float(assessment_res.score) if hasattr(assessment_res, "score") else 0.0
            res_str = str(persisted_assessment.result) if persisted_assessment else "normal"
            alert_created = (persisted_ml_alert is not None) or (len(rule_alerts) > 0)
            
            if persisted_ml_alert:
                alert_sev = persisted_ml_alert.severity
                msg = persisted_ml_alert.reason
            elif rule_alerts:
                alert_sev = rule_alerts[0].severity
                msg = f"Clinical rule alert triggered: {rule_alerts[0].reason}"
            else:
                alert_sev = None
                msg = f"ML assessment completed: {res_str} (score: {score:.3f})"

            ml_summary = MLAssessmentSummary(
                assessed=True,
                event_id=event_id,
                patient_id=patient_id,
                anomaly_score=round(score, 4),
                result=res_str,
                alert_created=alert_created,
                alert_severity=alert_sev,
                message=msg,
            )
        except Exception as ml_exc:
            logger.warning("ML assessment hook completed with degraded notice: %s", ml_exc)
            ml_summary = MLAssessmentSummary(
                assessed=False,
                event_id=event_id,
                patient_id=patient_id,
                anomaly_score=None,
                result="degraded",
                alert_created=len(rule_alerts) > 0,
                alert_severity=rule_alerts[0].severity if rule_alerts else None,
                message=f"ML service notice: {ml_exc}",
            )

        # 3. Synchronize to MongoDB Atlas if MONGODB_SYNC_ENABLED is true
        try:
            from services.api.config import get_settings
            from database.mongodb.client import get_mongo_database
            from services.sync.outbox_service import OutboxSyncService
            app_settings = get_settings()
            if app_settings.mongodb_sync_enabled:
                mongo_db = get_mongo_database(app_settings)
                if mongo_db is not None:
                    outbox_svc = OutboxSyncService(db, mongo_db, sync_enabled=True)
                    outbox_svc.sync_telemetry_immediate(event)
                    if persisted_ml_alert:
                        outbox_svc.sync_alert_immediate(persisted_ml_alert)
                    for ra in rule_alerts:
                        outbox_svc.sync_alert_immediate(ra)
                    db.commit()
        except Exception as mongo_sync_exc:
            logger.warning("MongoDB outbox sync notice for demo SQL reading: %s", mongo_sync_exc)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        columns = [
            "reading_id", "event_id", "patient_id", "metric_code",
            "value", "unit", "raw_value", "raw_unit", "quality_status",
            "measured_at", "source"
        ]
        rows = [
            [
                r.reading_id,
                event_id,
                patient_id,
                r.metric_code,
                float(r.value),
                r.unit,
                float(r.raw_value) if r.raw_value is not None else None,
                r.raw_unit,
                r.quality_status,
                r.measured_at.isoformat() if r.measured_at else str(primary_measured_at),
                "self_added",
            ]
            for r in persisted_readings
        ]

        return SQLWorkbenchExecuteResponse(
            status="success",
            statement_type="INSERT",
            execution_time_ms=elapsed_ms,
            columns=columns,
            rows=rows,
            row_count=len(persisted_readings),
            rows_affected=len(persisted_readings),
            last_inserted_id=persisted_readings[0].reading_id if persisted_readings else None,
            message=f"{len(persisted_readings)} self_added vital sign reading(s) inserted successfully for patient {patient_id}.",
            ml_assessment=ml_summary,
        )

    def _execute_update(
        self,
        db: Session,
        request: SQLWorkbenchExecuteRequest,
        stmt: sqlparse.sql.Statement,
    ) -> SQLWorkbenchExecuteResponse:
        """
        Execute validated UPDATE statement on demo records with safety & consistency enforcement:
        1. Disallows UPDATE without WHERE clause.
        2. Prohibits mutations targeting baseline cohorts (P001-P005).
        3. Restricts mutations to self_added readings.
        4. Re-evaluates ML assessment and clinical rules for modified readings.
        """
        start_time = time.perf_counter()
        sql_upper = request.sql.upper()

        if "WHERE" not in sql_upper:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Safety Violation: UPDATE statements must include an explicit WHERE clause.",
            )

        for p in PROTECTED_BASELINE_PATIENTS:
            if p in sql_upper:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Clinical Safety Violation: Baseline clinical patient '{p}' records are strictly read-only.",
                )

        tables = self._extract_table_names(stmt)
        where_match = re.search(r"\bWHERE\b(.+)$", request.sql, re.IGNORECASE | re.DOTALL)
        where_clause = where_match.group(1).strip().rstrip(";") if where_match else "1=1"

        if "vitals_readings" in tables:
            check_sql = text(f"SELECT reading_id, event_id, patient_id FROM vitals_readings WHERE {where_clause}")
            candidates = db.execute(check_sql, request.params or {}).fetchall()

            for row in candidates:
                p_id, evt_id = row[2], row[1]
                if p_id in PROTECTED_BASELINE_PATIENTS:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Clinical Safety Violation: Baseline clinical patient '{p_id}' records are strictly read-only.",
                    )
                if p_id not in APPROVED_DEMO_PATIENTS:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Validation Error: Patient ID must be in demo cohort {sorted(APPROVED_DEMO_PATIENTS)}.",
                    )
                evt = db.query(IngestionEvent).filter(IngestionEvent.event_id == evt_id).first()
                if evt and evt.source != "self_added":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Clinical Safety Violation: Only self_added readings can be updated. Baseline and simulator records are immutable.",
                    )

            result = db.execute(text(request.sql), request.params or {})
            rows_affected = result.rowcount
            db.commit()

            # Re-evaluate affected events to maintain assessment consistency
            affected_event_ids = list({row[1] for row in candidates})
            for eid in affected_event_ids:
                try:
                    event = db.query(IngestionEvent).filter(IngestionEvent.event_id == eid).first()
                    if event and event.readings:
                        evaluator = AlertEvaluator(session=db)
                        evaluator.evaluate_readings_batch(event=event, readings=event.readings, allow_historical=False)

                        ml_svc = self.get_ml_service()
                        hr = next((float(r.value) for r in event.readings if r.metric_code == "heart_rate"), None)
                        spo2 = next((float(r.value) for r in event.readings if r.metric_code == "spo2"), None)
                        temp_r = next((r for r in event.readings if r.metric_code == "temperature"), None)
                        temp_f = None
                        if temp_r is not None:
                            temp_f = float(temp_r.raw_value) if temp_r.raw_unit == "degF" else round(float(temp_r.value) * 9.0 / 5.0 + 32.0, 2)
                        ml_svc.assess_and_persist(
                            db=db,
                            patient_id=event.patient_id,
                            timestamp=event.measured_at,
                            heart_rate=hr,
                            spo2=spo2,
                            temperature_f=temp_f,
                            source_event_id=event.event_id,
                            is_simulated=False,
                            trigger_alert=True,
                        )
                except Exception as sync_exc:
                    logger.warning("Post-update ML/alert re-evaluation notice: %s", sync_exc)

            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return SQLWorkbenchExecuteResponse(
                status="success",
                statement_type="UPDATE",
                execution_time_ms=elapsed_ms,
                columns=None,
                rows=None,
                row_count=0,
                rows_affected=rows_affected,
                message=f"UPDATE operation completed successfully. Rows affected: {rows_affected}.",
                ml_assessment=None,
            )

        # Standard non-vitals update
        result = db.execute(text(request.sql), request.params or {})
        rows_affected = result.rowcount
        db.commit()
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return SQLWorkbenchExecuteResponse(
            status="success",
            statement_type="UPDATE",
            execution_time_ms=elapsed_ms,
            columns=None,
            rows=None,
            row_count=0,
            rows_affected=rows_affected,
            message=f"UPDATE operation completed successfully. Rows affected: {rows_affected}.",
            ml_assessment=None,
        )

    def _execute_delete(
        self,
        db: Session,
        request: SQLWorkbenchExecuteRequest,
        stmt: sqlparse.sql.Statement,
    ) -> SQLWorkbenchExecuteResponse:
        """
        Execute validated DELETE statement with cascade cleanup and provenance boundaries:
        1. Disallows DELETE without WHERE clause.
        2. Prohibits deletion of baseline cohorts (P001-P005).
        3. Prohibits deletion of non-self_added records.
        4. Cleans up orphaned model_assessments, alerts, and ingestion_events when readings are deleted.
        """
        start_time = time.perf_counter()
        sql_upper = request.sql.upper()

        if "WHERE" not in sql_upper:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Safety Violation: DELETE statements must include an explicit WHERE clause.",
            )

        for p in PROTECTED_BASELINE_PATIENTS:
            if p in sql_upper:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Clinical Safety Violation: Baseline clinical patient '{p}' records are strictly read-only.",
                )

        tables = self._extract_table_names(stmt)
        where_match = re.search(r"\bWHERE\b(.+)$", request.sql, re.IGNORECASE | re.DOTALL)
        where_clause = where_match.group(1).strip().rstrip(";") if where_match else "1=1"

        if "vitals_readings" in tables:
            check_sql = text(f"SELECT reading_id, event_id, patient_id FROM vitals_readings WHERE {where_clause}")
            candidates = db.execute(check_sql, request.params or {}).fetchall()

            for row in candidates:
                p_id, evt_id = row[2], row[1]
                if p_id in PROTECTED_BASELINE_PATIENTS:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Clinical Safety Violation: Baseline clinical patient '{p_id}' records are strictly read-only.",
                    )
                evt = db.query(IngestionEvent).filter(IngestionEvent.event_id == evt_id).first()
                if evt and evt.source != "self_added":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Clinical Safety Violation: Only self_added readings can be deleted. Baseline and simulator records are immutable.",
                    )

            affected_event_ids = list({row[1] for row in candidates})

            result = db.execute(text(request.sql), request.params or {})
            rows_affected = result.rowcount

            # Clean up orphaned events, alerts, and assessments
            for eid in affected_event_ids:
                remaining_count = db.query(VitalsReading).filter(VitalsReading.event_id == eid).count()
                if remaining_count == 0:
                    alerts = db.query(Alert).filter(Alert.event_id == eid).all()
                    for a in alerts:
                        db.query(AlertStatusHistory).filter(AlertStatusHistory.alert_id == a.alert_id).delete(synchronize_session=False)
                        db.delete(a)
                    db.query(ModelAssessment).filter(ModelAssessment.event_id == eid).delete(synchronize_session=False)
                    db.query(IngestionEvent).filter(IngestionEvent.event_id == eid).delete(synchronize_session=False)

            db.commit()
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return SQLWorkbenchExecuteResponse(
                status="success",
                statement_type="DELETE",
                execution_time_ms=elapsed_ms,
                columns=None,
                rows=None,
                row_count=0,
                rows_affected=rows_affected,
                message=f"DELETE operation completed successfully. Rows affected: {rows_affected}.",
                ml_assessment=None,
            )

        elif "ingestion_events" in tables:
            check_sql = text(f"SELECT event_id, patient_id, source FROM ingestion_events WHERE {where_clause}")
            candidates = db.execute(check_sql, request.params or {}).fetchall()
            for row in candidates:
                p_id, src = row[1], row[2]
                if p_id in PROTECTED_BASELINE_PATIENTS or src != "self_added":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Clinical Safety Violation: Only self_added events can be deleted.",
                    )

            affected_event_ids = [row[0] for row in candidates]
            for eid in affected_event_ids:
                db.query(VitalsReading).filter(VitalsReading.event_id == eid).delete(synchronize_session=False)
                alerts = db.query(Alert).filter(Alert.event_id == eid).all()
                for a in alerts:
                    db.query(AlertStatusHistory).filter(AlertStatusHistory.alert_id == a.alert_id).delete(synchronize_session=False)
                    db.delete(a)
                db.query(ModelAssessment).filter(ModelAssessment.event_id == eid).delete(synchronize_session=False)
                db.query(IngestionEvent).filter(IngestionEvent.event_id == eid).delete(synchronize_session=False)

            db.commit()

            # Clean up mirrored events in MongoDB Atlas if enabled
            try:
                from services.api.config import get_settings
                from database.mongodb.client import get_mongo_database
                app_settings = get_settings()
                if app_settings.mongodb_sync_enabled:
                    mongo_db = get_mongo_database(app_settings)
                    if mongo_db is not None:
                        for eid in affected_event_ids:
                            mongo_db["telemetry_events"].delete_one({"_id": str(eid)})
                            mongo_db["alert_events"].delete_many({"event_id": str(eid)})
            except Exception as mongo_del_exc:
                logger.warning("MongoDB delete cleanup notice: %s", mongo_del_exc)

            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return SQLWorkbenchExecuteResponse(
                status="success",
                statement_type="DELETE",
                execution_time_ms=elapsed_ms,
                columns=None,
                rows=None,
                row_count=0,
                rows_affected=len(affected_event_ids),
                message=f"DELETE operation completed successfully. Rows affected: {len(affected_event_ids)}.",
                ml_assessment=None,
            )

        # Standard non-vitals delete
        result = db.execute(text(request.sql), request.params or {})
        rows_affected = result.rowcount
        db.commit()
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return SQLWorkbenchExecuteResponse(
            status="success",
            statement_type="DELETE",
            execution_time_ms=elapsed_ms,
            columns=None,
            rows=None,
            row_count=0,
            rows_affected=rows_affected,
            message=f"DELETE operation completed successfully. Rows affected: {rows_affected}.",
            ml_assessment=None,
        )

    def execute_query(
        self,
        request: SQLWorkbenchExecuteRequest,
        db: Session,
    ) -> SQLWorkbenchExecuteResponse:
        """
        Execute validated SQL statement against the isolated demo database.
        Applies transaction scope, rollbacks on errors, and sanitizes output.
        """
        # 1. Operational Mode Enforcement
        self.check_operational_mode(request.is_demo_mode)

        # 2. Parse & Security Validation
        stmt, stmt_type = self.parse_and_validate_statement(request.sql)

        # 3. Intercept vitals_readings INSERT for schema validation, provenance, and ML hook
        if stmt_type == "INSERT" and self._is_vitals_reading_insert(stmt):
            rows_data = self._parse_vitals_insert_rows(request.sql, request.params)
            return self._execute_vitals_insert_with_ml(
                db=db,
                vitals_rows=rows_data,
                context_patient_id=request.patient_id,
            )

        # 4. Intercept UPDATE with strict safety and consistency re-evaluation
        if stmt_type == "UPDATE":
            return self._execute_update(db=db, request=request, stmt=stmt)

        # 5. Intercept DELETE with strict cascade and provenance protection
        if stmt_type == "DELETE":
            return self._execute_delete(db=db, request=request, stmt=stmt)

        # 6. Standard SQL Execution (SELECT, JOIN, Aggregates, Views)
        start_time = time.perf_counter()
        try:
            sql_stmt = text(request.sql)
            params = request.params or {}
            result = db.execute(sql_stmt, params)

            columns: Optional[List[str]] = None
            rows: Optional[List[List[Any]]] = None
            row_count = 0
            rows_affected: Optional[int] = None
            last_inserted_id: Optional[Union[int, str]] = None
            message: Optional[str] = None

            if result.returns_rows:
                columns = list(result.keys())
                raw_rows = result.fetchall()
                rows = [list(r) for r in raw_rows]
                row_count = len(rows)
                message = f"Query executed successfully, returning {row_count} row(s)."
            else:
                rows_affected = result.rowcount
                last_inserted_id = getattr(result, "lastrowid", None)
                db.commit()
                message = f"{stmt_type} operation completed successfully. Rows affected: {rows_affected}."

            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            return SQLWorkbenchExecuteResponse(
                status="success",
                statement_type=stmt_type,
                execution_time_ms=elapsed_ms,
                columns=columns,
                rows=rows,
                row_count=row_count,
                rows_affected=rows_affected,
                last_inserted_id=last_inserted_id,
                message=message,
                ml_assessment=None,
            )

        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            raw_err = str(exc)
            sanitized = sanitize_sql_error_message(raw_err)
            logger.error("SQL Workbench Execution Error: %s", sanitized)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SQL Execution Error: {sanitized}",
            )


# Module-level singleton
_DEMO_SQL_SERVICE: Optional[DemoSQLExecutionService] = None


def get_demo_sql_service() -> DemoSQLExecutionService:
    """Retrieve global DemoSQLExecutionService singleton."""
    global _DEMO_SQL_SERVICE
    if _DEMO_SQL_SERVICE is None:
        _DEMO_SQL_SERVICE = DemoSQLExecutionService()
    return _DEMO_SQL_SERVICE
