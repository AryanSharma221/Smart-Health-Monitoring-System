"""
Unit and regression tests for DA3 deliverables, documentation, and evidence integrity.
Verifies the existence, size, and critical content invariants of all required DA3 documents.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_DA3_DOCUMENTS = [
    "DA3_LIVE_DEMO_REQUIREMENTS.md",
    "DA3_FINAL_SUBMISSION_AUDIT.md",
    "DA3_EVIDENCE_INDEX.md",
    "DA3_DEMO_OPERATOR_GUIDE.md",
    "DA3_DATABASE_DEMONSTRATION_PACK.md",
    "DA3_TIMED_REHEARSAL.md",
    "DA3_VIVA_PREPARATION.md",
    "DA3_CURRENT_STATUS.md",
    "DA3_BACKUP_RECOVERY_EVIDENCE.md",
    "DA3_QUERY_OPTIMIZATION_EVIDENCE.md",
    "DA3_SQL_NOSQL_COMPARISON.md",
    "DA3_MYSQL_INTEGRITY_AND_TRANSACTIONS.md",
    "DA3_CLOUD_DATABASE_VERIFICATION.md",
    "DA3_SECURITY_AND_ACCESS_CONTROL.md",
    "DA3_SECURITY_REGRESSION_REPORT.md",
    "DA3_BACKUP_RECOVERY_REPORT.md",
    "DA3_QUERY_PERFORMANCE_REPORT.md",
    "DA3_DEMONSTRATION_RUNBOOK.md",
    "DA3_FULL_STACK_INTEGRATION_REPORT.md",
    "DA3_RELEASE_INTEGRITY_REPORT.md",
    "DA3_FAILURE_DRILL_REPORT.md",
    "DA3_EVALUATION_DAY_PREFLIGHT.md",
    "DA3_DEFECT_CLOSURE_REPORT.md",
    "DA3_INDEPENDENT_FINAL_AUDIT.md",
]

REQUIRED_SCREENSHOT_FILES = [
    "01_clinician_workstation_patients.png",
    "02_patient_vitals_timeseries.png",
    "03_clinical_alert_triage.png",
    "04_da3_evaluation_console.png",
    "05_fastapi_swagger_docs.png",
    "06_streamlit_analytics_visualizer.png",
    "07_preflight_terminal_diagnostics.png",
]


@pytest.mark.parametrize("doc_name", REQUIRED_DA3_DOCUMENTS)
def test_da3_core_document_exists_and_non_trivial(doc_name: str):
    """Verify that every required DA3 core document exists in root and exceeds 5 KB."""
    doc_path = PROJECT_ROOT / doc_name
    assert doc_path.exists(), f"Required DA3 document {doc_name} is missing from root directory."
    file_size = doc_path.stat().st_size
    assert file_size > 5000, f"Document {doc_name} is too small ({file_size} bytes); expected > 5,000 bytes."


def test_da3_operator_guide_structure():
    """Verify DA3_DEMO_OPERATOR_GUIDE.md contains essential operational stations."""
    guide_path = PROJECT_ROOT / "DA3_DEMO_OPERATOR_GUIDE.md"
    content = guide_path.read_text(encoding="utf-8")
    assert "Preflight Diagnostics" in content
    assert "CRUD Operations" in content
    assert "Baseline Deletion Guard" in content
    assert "MongoDB Atlas Cloud" in content
    assert "2,955" in content


def test_da3_viva_preparation_structure():
    """Verify DA3_VIVA_PREPARATION.md contains theoretical and defense Q&A sections."""
    viva_path = PROJECT_ROOT / "DA3_VIVA_PREPARATION.md"
    content = viva_path.read_text(encoding="utf-8")
    assert "Polyglot Persistence" in content
    assert "Boyce-Codd Normal Form" in content or "BCNF" in content
    assert "sp_safe_patient_discharge" in content
    assert "trg_alert_status_history_after_update" in content
    assert "idx_vitals_patient_metric_time" in content
    assert "Isolation Forest" in content


@pytest.mark.parametrize("screenshot_name", REQUIRED_SCREENSHOT_FILES)
def test_da3_screenshot_assets_exist(screenshot_name: str):
    """Verify that all 7 authentic high-resolution PNG screenshots are present."""
    screenshot_path = PROJECT_ROOT / "docs" / "screenshots" / screenshot_name
    assert screenshot_path.exists(), f"Required screenshot {screenshot_name} is missing from docs/screenshots/."
    file_size = screenshot_path.stat().st_size
    assert file_size > 30000, f"Screenshot {screenshot_name} appears corrupted or too small ({file_size} bytes)."


def test_da3_query_optimization_evidence_structure():
    """Verify DA3_QUERY_OPTIMIZATION_EVIDENCE.md contains required sections and invariants."""
    evidence_path = PROJECT_ROOT / "DA3_QUERY_OPTIMIZATION_EVIDENCE.md"
    content = evidence_path.read_text(encoding="utf-8")
    assert "idx_vitals_patient_measured" in content
    assert "idx_vitals_patient_metric_time" in content
    assert "USE TEMP B-TREE FOR ORDER BY" in content
    assert "14.88x" in content or "14.8" in content
    assert "2,955" in content
    assert "004_optimize_patient_timeseries_index" in content


def test_da3_sql_nosql_comparison_structure():
    """Verify DA3_SQL_NOSQL_COMPARISON.md contains required sections and invariants."""
    comparison_path = PROJECT_ROOT / "DA3_SQL_NOSQL_COMPARISON.md"
    content = comparison_path.read_text(encoding="utf-8")
    assert "Polyglot Persistence" in content
    assert "Transactional Outbox" in content
    assert "analytics_outbox" in content
    assert "2,955" in content
    assert "sp_safe_patient_discharge" in content
    assert "idx_telemetry_patient_measured" in content


def test_da3_mysql_integrity_structure():
    """Verify DA3_MYSQL_INTEGRITY_AND_TRANSACTIONS.md contains required sections and invariants."""
    integrity_path = PROJECT_ROOT / "DA3_MYSQL_INTEGRITY_AND_TRANSACTIONS.md"
    content = integrity_path.read_text(encoding="utf-8")
    assert "sp_safe_patient_discharge" in content
    assert "trg_alert_status_history_after_update" in content
    assert "v_latest_patient_vitals" in content
    assert "ON DELETE CASCADE" in content
    assert "SAVEPOINT" in content
    assert "2,955" in content


def test_da3_cloud_db_verification_structure():
    """Verify DA3_CLOUD_DATABASE_VERIFICATION.md contains required sections and invariants."""
    cloud_path = PROJECT_ROOT / "DA3_CLOUD_DATABASE_VERIFICATION.md"
    content = cloud_path.read_text(encoding="utf-8")
    assert "cluster0.offnaie.mongodb.net" in content
    assert "2,955" in content
    assert "sanitize_mongo_uri" in content
    assert "Transactional Outbox" in content
    assert "Dockerfile" in content
    assert "docker-compose.yml" in content
    assert "0.619 ms" in content or "Sub-millisecond" in content or "sub-millisecond" in content


def test_da3_security_and_access_control_structure():
    """Verify DA3_SECURITY_AND_ACCESS_CONTROL.md contains required sections and invariants."""
    sec_path = PROJECT_ROOT / "DA3_SECURITY_AND_ACCESS_CONTROL.md"
    content = sec_path.read_text(encoding="utf-8")
    assert "verify_patient_access" in content
    assert "DoctorPatientAssignment" in content
    assert "smart_health_app" in content
    assert "2,955" in content
    assert "sanitize_mongo_uri" in content
    assert "WebSocket" in content


def test_da3_security_regression_report_structure():
    """Verify DA3_SECURITY_REGRESSION_REPORT.md contains required sections and invariants."""
    report_path = PROJECT_ROOT / "DA3_SECURITY_REGRESSION_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "StrictReadOnlyMongoDatabase" in content
    assert "MongoWriteViolationError" in content
    assert "2,955" in content
    assert "isolated_db" in content
    assert "security_personas" in content
    assert "96" in content


def test_da3_backup_recovery_report_structure():
    """Verify DA3_BACKUP_RECOVERY_REPORT.md contains required sections and invariants."""
    report_path = PROJECT_ROOT / "DA3_BACKUP_RECOVERY_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "smart_health_recovery_isolated.db" in content
    assert "2,955" in content
    assert "scripts/backup_mysql.py" in content
    assert "scripts/restore_mysql.py" in content
    assert "scripts/verify_recovery.py" in content
    assert "scripts/cleanup_backups.py" in content
    assert "blocked_safety_violation" in content


def test_da3_query_performance_report_structure():
    """Verify DA3_QUERY_PERFORMANCE_REPORT.md contains required sections and invariants."""
    report_path = PROJECT_ROOT / "DA3_QUERY_PERFORMANCE_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "idx_vitals_patient_metric_time" in content
    assert "2,955" in content
    assert "scripts/benchmark_sql_nosql.py" in content
    assert "13.52" in content or "13.5" in content
    assert "executionStats" in content
    assert "totalKeysExamined" in content


def test_da3_demonstration_runbook_structure():
    """Verify DA3_DEMONSTRATION_RUNBOOK.md contains required sections, invariants, and tables."""
    runbook_path = PROJECT_ROOT / "DA3_DEMONSTRATION_RUNBOOK.md"
    content = runbook_path.read_text(encoding="utf-8")
    assert "scripts/preflight_check.py" in content
    assert "2,955" in content
    assert "evaluation_records" in content
    assert "sp_safe_patient_discharge" in content
    assert "idx_vitals_patient_metric_time" in content
    assert "ROLLBACK TO SAVEPOINT" in content
    assert "13.52" in content
    assert "Requirement-to-Live-Demonstration Mapping" in content or "Requirement-to-Live" in content


def test_da3_full_stack_integration_report_structure():
    """Verify DA3_FULL_STACK_INTEGRATION_REPORT.md contains required sections, invariants, and tables."""
    report_path = PROJECT_ROOT / "DA3_FULL_STACK_INTEGRATION_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "2,955" in content
    assert "Transactional Outbox" in content
    assert "idx_vitals_patient_metric_time" in content
    assert "Live Integration" in content
    assert "Isolated Integration" in content
    assert "Mocked Verification" in content
    assert "Static Inspection" in content
    assert "End-to-End Data Flow Mapping" in content or "Traceability Matrix" in content


def test_da3_release_integrity_report_structure():
    """Verify DA3_RELEASE_INTEGRITY_REPORT.md contains required sections, invariants, and verdict."""
    report_path = PROJECT_ROOT / "DA3_RELEASE_INTEGRITY_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "2,955" in content
    assert "Repositories Inspected" in content or "Repository Component" in content
    assert "AryanSharma221/Smart-Health-Monitoring-System" in content
    assert "AdityaDhakad1404/frontend-dbms" in content
    assert "HarnoorKant/Smart-Health-Monitoring-System" in content
    assert "507" in content or "479" in content
    assert "GO" in content


def test_da3_failure_drill_report_structure():
    """Verify DA3_FAILURE_DRILL_REPORT.md contains required failure scenarios, empirical results, and recovery paths."""
    report_path = PROJECT_ROOT / "DA3_FAILURE_DRILL_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "2,955" in content
    assert "Inventory of Critical Failure Scenarios" in content
    assert "Empirical Drill Results & Graceful Degradation Verification" in content
    assert "Automated Failure-Drill Test Suite Verification" in content
    assert "Operational Boundaries and Known Limitations" in content
    assert "Safe Manual Recovery Procedures" in content
    assert "Top Three Failure Scenarios to Rehearse Before Assessment" in content
    assert "Non-Negotiable Safety Attestation" in content
    assert "test_failure_drills.py" in content
    assert "failureDrills.test.ts" in content


def test_da3_evaluation_day_preflight_structure():
    """Verify DA3_EVALUATION_DAY_PREFLIGHT.md contains required preflight checklist, matrix, and verdict."""
    report_path = PROJECT_ROOT / "DA3_EVALUATION_DAY_PREFLIGHT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "2,955" in content
    assert "Executive Summary & Readiness Verdict" in content
    assert "Evaluation-Day Preflight Checklist & Sequence" in content
    assert "Prerequisites & Environment Verification" in content
    assert "Empirical Preflight Execution Outcomes" in content
    assert "Observable Application Behavior Verification" in content
    assert "Complete Mandatory Requirement Traceability Matrix" in content
    assert "Outstanding Disclosed Boundaries & Scope Limitations" in content
    assert "Safe Manual Recovery Instructions" in content
    assert "Non-Negotiable Safety Attestation" in content
    assert "GO (CERTIFIED READY FOR LIVE DEMONSTRATION)" in content


def test_da3_defect_closure_report_structure():
    """Verify DA3_DEFECT_CLOSURE_REPORT.md contains remediated defects and safety guarantees."""
    report_path = PROJECT_ROOT / "DA3_DEFECT_CLOSURE_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "DEF-001" in content
    assert "DEF-002" in content
    assert "DEF-003" in content
    assert "DEF-004" in content
    assert "DEF-005" in content
    assert "2,955" in content
    assert "ALL DEFECTS CLOSED" in content


def test_da3_independent_final_audit_structure():
    """Verify DA3_INDEPENDENT_FINAL_AUDIT.md contains all independent audit sections and GO verdict."""
    report_path = PROJECT_ROOT / "DA3_INDEPENDENT_FINAL_AUDIT.md"
    content = report_path.read_text(encoding="utf-8")
    assert "2,955" in content
    assert "Executive Summary & Audit Methodology" in content
    assert "Independent Audit Against Original Requirements" in content
    assert "Independent Physical Substantiation of Prior Antigravity Claims" in content
    assert "Honest Disclosure of Scope Boundaries and Limitations" in content
    assert "Final Submission & Demonstration Recommendation" in content
    assert "Complete 24-Item Requirement Compliance Matrix" in content
    assert "Top Three Remaining Risks and Viva Defense Q&A" in content
    assert "Non-Negotiable Safety Attestation & Explicit Read-Only Confirmation" in content
    assert "Actionable Pre-Demonstration Checklist for the Student" in content
    assert "GO (CERTIFIED READY FOR SUBMISSION AND LIVE DEMONSTRATION)" in content









