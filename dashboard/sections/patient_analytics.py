"""
Section B: Patient-Level Telemetry Analytics and Bounded History.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

from dashboard.components.metrics import render_metric_card
from dashboard.data_access import (
    fetch_patient_ids,
    fetch_patient_telemetry_history,
    fetch_patient_vitals_summary,
)


def render_patient_analytics_section(
    selected_patient_id: Optional[str] = None,
    backend: str = "sql",
    force_fallback: bool = False,
) -> None:
    """Render Section B: Patient Analytics."""
    st.subheader("Patient Telemetry & Vital Signs Summary")
    st.markdown(
        "Individualized physiological telemetry summaries, measurement distributions, "
        "and bounded chronological observation histories."
    )

    # 1. Patient Selector
    patient_ids = fetch_patient_ids(backend=backend, force_fallback=force_fallback)
    if not patient_ids:
        st.warning("No patient records found in the database.")
        return

    # Use passed selection or local selectbox
    current_idx = 0
    if selected_patient_id and selected_patient_id in patient_ids:
        current_idx = patient_ids.index(selected_patient_id)

    pat_col, hist_limit_col = st.columns([2, 1])
    with pat_col:
        patient_id = st.selectbox(
            "Select Patient Identifier:",
            options=patient_ids,
            index=current_idx,
            key="sec_b_patient_selector",
        )
    with hist_limit_col:
        history_limit = st.selectbox(
            "History Records to Display:",
            options=[25, 50, 100, 200],
            index=1,
            key="sec_b_history_limit",
        )

    if not patient_id:
        st.info("Please select a patient identifier to view vital sign analytics.")
        return

    # 2. Fetch Patient Summary
    try:
        summary_list = fetch_patient_vitals_summary(
            patient_id=patient_id,
            backend=backend,
            force_fallback=force_fallback,
        )
    except Exception as exc:
        st.error(f"Error fetching vitals summary for {patient_id}: {exc}")
        return

    if not summary_list:
        st.info(f"No telemetry observations recorded for patient '{patient_id}'.")
        return

    p_data = summary_list[0]
    hr_data = p_data.get("heart_rate", {})
    spo2_data = p_data.get("spo2", {})
    temp_data = p_data.get("temperature_f", {})

    st.markdown(f"#### Vital Sign Statistics: `{patient_id}`")
    st.caption("Baseline metrics computed over all available observations for this patient.")

    # 3. Metric KPI Cards Grid
    col_hr, col_spo2, col_temp, col_obs = st.columns(4)

    with col_hr:
        st.markdown("**Heart Rate (bpm)**")
        render_metric_card(
            label="Average HR",
            value=hr_data.get("avg"),
            unit="bpm",
            help_text="Physiologic range typically 60-100 bpm resting.",
        )
        st.caption(f"Min: **{hr_data.get('min', '--')}** | Max: **{hr_data.get('max', '--')}** | Count: **{hr_data.get('valid_count', 0)}**")

    with col_spo2:
        st.markdown("**Blood Oxygen (SpO2)**")
        render_metric_card(
            label="Average SpO2",
            value=spo2_data.get("avg"),
            unit="%",
            help_text="Standard resting levels typically 95-100%.",
        )
        st.caption(f"Min: **{spo2_data.get('min', '--')}%** | Max: **{spo2_data.get('max', '--')}%** | Count: **{spo2_data.get('valid_count', 0)}**")

    with col_temp:
        st.markdown("**Body Temperature (°F)**")
        render_metric_card(
            label="Average Temp",
            value=temp_data.get("avg"),
            unit="°F",
            help_text="Normal baseline body temperature typically ~98.6°F.",
        )
        st.caption(f"Min: **{temp_data.get('min', '--')}°F** | Max: **{temp_data.get('max', '--')}°F** | Count: **{temp_data.get('valid_count', 0)}**")

    with col_obs:
        st.markdown("**Observation Count**")
        render_metric_card(
            label="Total Readings",
            value=f"{p_data.get('total_observations', 0):,}",
            unit="events",
            help_text="Number of distinct telemetry events recorded for this patient.",
        )

    st.divider()

    # 4. Telemetry History Table
    st.markdown(f"#### Recent Telemetry Ingestion History (`{patient_id}`)")
    st.caption(f"Bounded chronological observation events (most recent {history_limit} records).")

    try:
        history_records = fetch_patient_telemetry_history(
            patient_id=patient_id,
            limit=history_limit,
            backend=backend,
            force_fallback=force_fallback,
        )
    except Exception as exc:
        st.error(f"Failed to load telemetry history: {exc}")
        return

    if not history_records:
        st.info("No detailed history events available.")
        return

    table_rows = []
    for r in history_records:
        m = r.get("metrics", {})
        table_rows.append({
            "Measured At (UTC)": r.get("measured_at"),
            "Heart Rate (bpm)": m.get("heart_rate"),
            "SpO2 (%)": m.get("spo2"),
            "Temp (°F)": m.get("temperature_f"),
            "Temp (°C)": m.get("temperature_c"),
            "Source System": r.get("source"),
            "Simulated?": "Yes" if r.get("is_simulated") else "No",
        })

    hist_df = pd.DataFrame(table_rows)
    st.dataframe(hist_df, use_container_width=True, hide_index=True)
    st.caption(
        "Note: Historical data timestamps are stored in canonical UTC. "
        "Null values reflect non-recorded channels without synthetic zero-filling."
    )
