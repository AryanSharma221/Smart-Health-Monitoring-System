"""
Section E: Data Quality Diagnostics, Audit Indicators, and Mirror Reconciliation.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.metrics import render_badge, render_metric_card
from dashboard.data_access import (
    fetch_data_quality_report,
    fetch_database_reconciliation,
    fetch_patient_ids,
    fetch_patient_vitals_summary,
    probe_system_connectivity,
)


def render_data_quality_section(
    backend: str = "sql",
    force_fallback: bool = False,
) -> None:
    """Render Section E: Data Quality and Integrity Diagnostics."""
    st.subheader("Data Quality Diagnostics & Mirror Reconciliation")
    st.markdown(
        "Comprehensive validation covering field completeness, physiologic plausibility boundaries, "
        "duplicate source detection, and relational-to-document mirror reconciliation."
    )

    # 1. Fetch data quality and reconciliation reports
    try:
        report = fetch_data_quality_report(backend=backend, force_fallback=force_fallback)
        reconcile = fetch_database_reconciliation(force_fallback=force_fallback)
        connectivity = probe_system_connectivity()
    except Exception as exc:
        st.error(f"Failed to execute data quality audit: {exc}")
        return

    # 2. Top-Level Integrity Metrics
    tot_checked = report.get("total_checked", 0)
    missing_fields = report.get("missing_fields", {})
    implausible = report.get("implausible_values", {})
    dups = report.get("duplicate_source_identities", 0)

    total_missing = sum(missing_fields.values())
    total_implausible = sum(implausible.values())

    col_q1, col_q2, col_q3, col_q4 = st.columns(4)
    with col_q1:
        render_metric_card(
            label="Audited Records",
            value=f"{tot_checked:,}",
            unit="events",
            help_text="Total ingestion events evaluated across quality assertions.",
        )
    with col_q2:
        render_metric_card(
            label="Missing Essential Fields",
            value=total_missing,
            delta="0 expected" if total_missing == 0 else f"{total_missing} flagged",
            delta_color="normal" if total_missing == 0 else "inverse",
            help_text="Events missing patient_id, measured_at, or source metadata.",
        )
    with col_q3:
        render_metric_card(
            label="Implausible Readings",
            value=total_implausible,
            delta="0 expected" if total_implausible == 0 else f"{total_implausible} flagged",
            delta_color="normal" if total_implausible == 0 else "inverse",
            help_text="Values exceeding physiological bounds (HR 30-250, SpO2 50-100%, Temp 90-115°F).",
        )
    with col_q4:
        render_metric_card(
            label="Duplicate Source IDs",
            value=dups,
            delta="0 expected" if dups == 0 else f"{dups} duplicates",
            delta_color="normal" if dups == 0 else "inverse",
            help_text="Collisions in (source, source_event_id) composite identity.",
        )

    st.divider()

    # 3. Quality Breakdown Tables
    col_t1, col_t2 = st.columns(2)

    with col_t1:
        st.markdown("##### Essential Field Completeness")
        field_df = pd.DataFrame([
            {"Field": "patient_id", "Missing Count": missing_fields.get("missing_patient_id", 0), "Status": "PASS" if missing_fields.get("missing_patient_id", 0) == 0 else "FAIL"},
            {"Field": "measured_at", "Missing Count": missing_fields.get("missing_measured_at", 0), "Status": "PASS" if missing_fields.get("missing_measured_at", 0) == 0 else "FAIL"},
            {"Field": "source", "Missing Count": missing_fields.get("missing_source", 0), "Status": "PASS" if missing_fields.get("missing_source", 0) == 0 else "FAIL"},
        ])
        st.dataframe(field_df, use_container_width=True, hide_index=True)

    with col_t2:
        st.markdown("##### Physiological Boundary Violations")
        bound_df = pd.DataFrame([
            {"Metric": "Heart Rate", "Boundary Rule": "30 - 250 bpm", "Violations": implausible.get("implausible_heart_rate", 0)},
            {"Metric": "Oxygen Saturation (SpO2)", "Boundary Rule": "50.0 - 100.0 %", "Violations": implausible.get("implausible_spo2", 0)},
            {"Metric": "Body Temperature", "Boundary Rule": "90.0 - 115.0 °F", "Violations": implausible.get("implausible_temperature_f", 0)},
        ])
        st.dataframe(bound_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 4. Database Mirror Synchronization & Reconciliation
    st.markdown("##### MySQL ↔ MongoDB Mirror Population Reconciliation")
    st.markdown(
        "Verifies that authoritative relational records in MySQL match the mirrored document "
        "population in MongoDB Atlas without dropouts or unacknowledged desynchronization."
    )

    col_rec1, col_rec2 = st.columns([1, 1])

    with col_rec1:
        reconcile_df = pd.DataFrame([
            {"Metric / Entity": "Relational Documents (MySQL)", "Value": f"{reconcile.get('sql_count', 0):,}", "Mode": reconcile.get("sql_mode", "--")},
            {"Metric / Entity": "Document Mirror (MongoDB)", "Value": f"{reconcile.get('mongo_count', 0):,}", "Mode": reconcile.get("mongo_mode", "--")},
            {"Metric / Entity": "Population Discrepancy", "Value": str(reconcile.get("discrepancy", 0)), "Mode": "Exact Parity" if reconcile.get("is_in_sync") else "Desynchronized"},
            {"Metric / Entity": "Distinct Patients (MySQL)", "Value": str(reconcile.get("sql_patients", 0)), "Mode": "Cohort Size"},
            {"Metric / Entity": "Distinct Patients (MongoDB)", "Value": str(reconcile.get("mongo_patients", 0)), "Mode": "Cohort Size"},
        ])
        st.dataframe(reconcile_df, use_container_width=True, hide_index=True)

    with col_rec2:
        if reconcile.get("is_in_sync"):
            st.success("State: **100% Mirror Parity Verified**")
            st.markdown(
                "Both the relational store and the document mirror reflect identical document "
                "populations with zero record dropouts or orphan telemetry events."
            )
        else:
            st.warning(f"State: **Discrepancy of {reconcile.get('discrepancy', 0)} documents detected.**")
            st.caption("Check the Transactional Outbox processor in Section H for pending or retryable synchronization batches.")

        st.caption(
            "Audit Rule: Data quality issues (e.g. missing fields, implausible values) are "
            "strictly distinguished from network or infrastructure connectivity states."
        )
