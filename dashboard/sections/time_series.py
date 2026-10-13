"""
Section C: Chronological Time-Series Trends and Bucketed Aggregations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from dashboard.components.charts import build_vitals_time_series_chart
from dashboard.data_access import (
    fetch_patient_ids,
    fetch_time_bucketed_vitals,
)


def render_time_series_section(
    selected_patient_id: Optional[str] = None,
    backend: str = "sql",
    force_fallback: bool = False,
) -> None:
    """Render Section C: Time-Series Trends."""
    st.subheader("Physiological Time-Series Trends")
    st.markdown(
        "Chronological visualization of patient vital signs over time. "
        "Heart Rate, SpO2, and Body Temperature are charted on independent vertical scales "
        "to prevent misleading scale distortions. Gaps in observation are preserved honestly."
    )

    # 1. Filters row
    patient_ids = fetch_patient_ids(backend=backend, force_fallback=force_fallback)
    filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])

    with filter_col1:
        options = ["All Cohort (Aggregate)"] + patient_ids
        default_idx = 0
        if selected_patient_id and selected_patient_id in patient_ids:
            default_idx = options.index(selected_patient_id)
        chosen_patient = st.selectbox(
            "Filter Patient:",
            options=options,
            index=default_idx,
            key="sec_c_patient_filter",
        )
        patient_filter = None if chosen_patient.startswith("All Cohort") else chosen_patient

    with filter_col2:
        interval = st.selectbox(
            "Time Aggregation Bucket:",
            options=["hour", "day"],
            format_func=lambda x: "Hourly Interval" if x == "hour" else "Daily Interval",
            index=0,
            key="sec_c_bucket_interval",
        )

    with filter_col3:
        metric_view = st.selectbox(
            "Channel Display:",
            options=["All Three Channels", "Heart Rate Only", "SpO2 Only", "Temperature Only"],
            index=0,
            key="sec_c_channel_display",
        )

    # 2. Fetch bucketed data
    try:
        bucketed_data = fetch_time_bucketed_vitals(
            patient_id=patient_filter,
            interval=interval,
            backend=backend,
            force_fallback=force_fallback,
        )
    except Exception as exc:
        st.error(f"Failed to retrieve bucketed vitals: {exc}")
        return

    if not bucketed_data:
        st.info("No time-bucketed observations found matching the selected filter criteria.")
        return

    df = pd.DataFrame(bucketed_data)
    # Ensure time_bucket is datetime
    df["time_bucket"] = pd.to_datetime(df["time_bucket"])

    # 3. Independent Altair Charts
    st.markdown("---")

    show_hr = metric_view in ["All Three Channels", "Heart Rate Only"]
    show_spo2 = metric_view in ["All Three Channels", "SpO2 Only"]
    show_temp = metric_view in ["All Three Channels", "Temperature Only"]

    if show_hr:
        st.markdown("##### 1. Heart Rate Trend (bpm)")
        chart_hr = build_vitals_time_series_chart(
            df=df,
            time_col="time_bucket",
            val_col="avg_heart_rate",
            title=f"Heart Rate Over Time ({interval.capitalize()} Buckets)" + (f" - Patient {patient_filter}" if patient_filter else " - Cohort Mean"),
            y_axis_title="Heart Rate (bpm)",
            line_color="#d62728",
            min_val_col="min_heart_rate" if "min_heart_rate" in df.columns else None,
            max_val_col="max_heart_rate" if "max_heart_rate" in df.columns else None,
        )
        st.altair_chart(chart_hr, use_container_width=True)

    if show_spo2:
        st.markdown("##### 2. Blood Oxygen Saturation Trend (%)")
        chart_spo2 = build_vitals_time_series_chart(
            df=df,
            time_col="time_bucket",
            val_col="avg_spo2",
            title=f"Blood Oxygen (SpO2) Over Time ({interval.capitalize()} Buckets)" + (f" - Patient {patient_filter}" if patient_filter else " - Cohort Mean"),
            y_axis_title="SpO2 (%)",
            line_color="#1f77b4",
        )
        st.altair_chart(chart_spo2, use_container_width=True)

    if show_temp:
        st.markdown("##### 3. Body Temperature Trend (°F)")
        chart_temp = build_vitals_time_series_chart(
            df=df,
            time_col="time_bucket",
            val_col="avg_temperature_f",
            title=f"Body Temperature Over Time ({interval.capitalize()} Buckets)" + (f" - Patient {patient_filter}" if patient_filter else " - Cohort Mean"),
            y_axis_title="Body Temperature (°F)",
            line_color="#ff7f0e",
        )
        st.altair_chart(chart_temp, use_container_width=True)

    # 4. Raw Bucketed Data Expander
    with st.expander(f"View Tabular Bucketed Values ({len(df)} time buckets)"):
        st.dataframe(
            df.rename(columns={
                "time_bucket": "Time Bucket (UTC)",
                "observation_count": "Observations",
                "avg_heart_rate": "Avg HR (bpm)",
                "min_heart_rate": "Min HR (bpm)",
                "max_heart_rate": "Max HR (bpm)",
                "avg_spo2": "Avg SpO2 (%)",
                "avg_temperature_f": "Avg Temp (°F)",
            }),
            use_container_width=True,
            hide_index=True,
        )
