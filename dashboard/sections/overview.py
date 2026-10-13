"""
Section A: High-Level Dataset Overview and System Connectivity.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from dashboard.components.charts import build_provenance_chart
from dashboard.components.metrics import render_badge, render_metric_card
from dashboard.data_access import (
    fetch_data_quality_report,
    fetch_dataset_overview,
    fetch_source_provenance,
    probe_system_connectivity,
)


def render_overview_section(backend: str = "sql", force_fallback: bool = False) -> None:
    """Render Section A: Overview."""
    st.subheader("System & Dataset Overview")
    st.markdown(
        "Real-time operational summary of authoritative patient telemetry records, "
        "coverage boundaries, data provenance, and database connectivity."
    )

    # 1. Fetch live metrics
    try:
        overview = fetch_dataset_overview(backend=backend, force_fallback=force_fallback)
        connectivity = probe_system_connectivity()
        quality = fetch_data_quality_report(backend=backend, force_fallback=force_fallback)
        provenance = fetch_source_provenance(backend=backend, force_fallback=force_fallback)
    except Exception as exc:
        st.error(f"Failed to load dataset overview: {exc}")
        return

    # 2. Status Badges Row
    col_stat1, col_stat2, col_stat3 = st.columns([1, 1, 2])
    with col_stat1:
        my_stat = "success" if connectivity["mysql_connected"] else "danger"
        st.markdown(f"**MySQL 8 (InnoDB):** {render_badge(my_stat, connectivity['mysql_status'])}", unsafe_allow_html=True)
    with col_stat2:
        mo_stat = "success" if connectivity["mongo_connected"] else "warning"
        st.markdown(f"**MongoDB Atlas:** {render_badge(mo_stat, connectivity['mongo_status'])}", unsafe_allow_html=True)
    with col_stat3:
        mode_label = overview.get("_active_mode", "Unknown")
        st.markdown(f"**Active Mode:** {render_badge('info', mode_label)}", unsafe_allow_html=True)

    st.divider()

    # 3. Primary KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_metric_card(
            label="Total Telemetry Events",
            value=f"{overview.get('total_documents', 0):,}",
            unit="records",
            help_text="Canonical ingestion events recorded in the database.",
        )
    with col2:
        render_metric_card(
            label="Monitored Patients",
            value=overview.get("distinct_patients_count", 0),
            unit="cohort",
            help_text="Distinct patient identifiers with recorded observations.",
        )
    with col3:
        earliest = overview.get("earliest_measured_at")
        latest = overview.get("latest_measured_at")
        earliest_str = earliest.strftime("%Y-%m-%d") if earliest else "--"
        latest_str = latest.strftime("%Y-%m-%d") if latest else "--"
        render_metric_card(
            label="Observation Time Span",
            value=f"{earliest_str} to {latest_str}",
            help_text="Earliest and latest recorded timestamps (UTC).",
        )
    with col4:
        # Data Quality Score
        missing_count = sum(quality.get("missing_fields", {}).values())
        dup_count = quality.get("duplicate_source_identities", 0)
        tot = overview.get("total_documents", 1)
        clean_pct = round(((tot - missing_count - dup_count) / tot) * 100.0, 1) if tot > 0 else 0.0
        render_metric_card(
            label="Data Completeness",
            value=clean_pct,
            unit="%",
            help_text="Percentage of records without missing essential fields or duplicate source IDs.",
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # 4. Secondary Breakdown: Provenance & Simulation
    col_prov1, col_prov2 = st.columns([1, 1])

    with col_prov1:
        st.markdown("##### Telemetry Data Origin")
        breakdown = provenance.get("provenance_breakdown", [])
        if breakdown:
            chart = build_provenance_chart(breakdown)
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No provenance breakdown records available.")

    with col_prov2:
        st.markdown("##### Patient Cohort Distribution")
        pat_ids = overview.get("distinct_patient_ids", [])
        sim_data = overview.get("documents_by_simulation", {})
        
        cohort_df = pd.DataFrame({
            "Metric": ["Patient Identifiers", "Non-Simulated Records (Historical)", "Simulated Test Stream"],
            "Value": [", ".join(pat_ids) if pat_ids else "None", f"{sim_data.get('non_simulated', 0):,}", f"{sim_data.get('simulated', 0):,}"],
        })
        st.dataframe(cohort_df, use_container_width=True, hide_index=True)
        
        st.caption(
            "Provenance Note: Historical records originate from the verified Kaggle patient dataset. "
            "Simulated readings arrive via the real-time ingestion API with `is_simulated=True`."
        )
