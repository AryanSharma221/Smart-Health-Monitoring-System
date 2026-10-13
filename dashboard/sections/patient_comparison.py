"""
Section D: Cross-Patient Population Variance and Statistical Comparison.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.charts import build_patient_comparison_bar_chart
from dashboard.data_access import fetch_patient_vitals_summary


def render_patient_comparison_section(
    backend: str = "sql",
    force_fallback: bool = False,
) -> None:
    """Render Section D: Patient Comparison."""
    st.subheader("Cross-Patient Cohort Comparison")
    st.markdown(
        "Comparative statistical analysis across all monitored patients evaluated over "
        "an identical observation time window and standardized aggregation methodology."
    )

    # 1. Fetch cohort summary
    try:
        summaries = fetch_patient_vitals_summary(
            patient_id=None,
            backend=backend,
            force_fallback=force_fallback,
        )
    except Exception as exc:
        st.error(f"Failed to load patient comparisons: {exc}")
        return

    if not summaries or len(summaries) < 2:
        st.info("Insufficient patient records to perform cross-cohort comparison (minimum 2 patients required).")
        return

    # 2. Build structured comparison dataframe
    rows = []
    for s in summaries:
        pid = s.get("patient_id")
        obs_count = s.get("total_observations", 0)
        hr = s.get("heart_rate", {})
        spo2 = s.get("spo2", {})
        temp = s.get("temperature_f", {})

        rows.append({
            "patient_id": pid,
            "total_observations": obs_count,
            "hr_avg": hr.get("avg"),
            "hr_min": hr.get("min"),
            "hr_max": hr.get("max"),
            "spo2_avg": spo2.get("avg"),
            "spo2_min": spo2.get("min"),
            "spo2_max": spo2.get("max"),
            "temp_avg": temp.get("avg"),
            "temp_min": temp.get("min"),
            "temp_max": temp.get("max"),
            "valid_count": hr.get("valid_count", 0),
        })

    comp_df = pd.DataFrame(rows)

    # 3. Clinical Safety Disclaimer
    st.info(
        "Clinical Disclaimer: Patient baseline averages reflect recorded physiological telemetry. "
        "Do not classify or rank patients as 'healthy' or 'unhealthy' solely on baseline averages; "
        "individual clinical histories, medications, and physician assessments must govern patient care."
    )

    # 4. Comparative Bar Charts Grid
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("##### Mean Heart Rate Comparison (bpm)")
        chart_hr = build_patient_comparison_bar_chart(
            df=comp_df,
            metric_name="hr_avg",
            y_axis_title="Average Heart Rate (bpm)",
            bar_color="#d62728",
        )
        st.altair_chart(chart_hr, use_container_width=True)

    with col_c2:
        st.markdown("##### Mean Blood Oxygen (SpO2 %)")
        chart_spo2 = build_patient_comparison_bar_chart(
            df=comp_df,
            metric_name="spo2_avg",
            y_axis_title="Average SpO2 (%)",
            bar_color="#1f77b4",
        )
        st.altair_chart(chart_spo2, use_container_width=True)

    col_c3, col_c4 = st.columns(2)
    with col_c3:
        st.markdown("##### Mean Body Temperature (°F)")
        chart_temp = build_patient_comparison_bar_chart(
            df=comp_df,
            metric_name="temp_avg",
            y_axis_title="Average Body Temp (°F)",
            bar_color="#ff7f0e",
        )
        st.altair_chart(chart_temp, use_container_width=True)

    with col_c4:
        st.markdown("##### Total Observations Per Patient")
        chart_obs = build_patient_comparison_bar_chart(
            df=comp_df,
            metric_name="total_observations",
            y_axis_title="Recorded Events",
            bar_color="#2ca02c",
        )
        st.altair_chart(chart_obs, use_container_width=True)

    # 5. Cohort Statistical Table
    st.markdown("##### Detailed Cohort Baseline Summary")
    display_df = comp_df.rename(columns={
        "patient_id": "Patient ID",
        "total_observations": "Total Observations",
        "hr_avg": "HR Mean (bpm)",
        "hr_min": "HR Min",
        "hr_max": "HR Max",
        "spo2_avg": "SpO2 Mean (%)",
        "spo2_min": "SpO2 Min",
        "spo2_max": "SpO2 Max",
        "temp_avg": "Temp Mean (°F)",
        "temp_min": "Temp Min",
        "temp_max": "Temp Max",
    })
    st.dataframe(display_df.drop(columns=["valid_count"], errors="ignore"), use_container_width=True, hide_index=True)
