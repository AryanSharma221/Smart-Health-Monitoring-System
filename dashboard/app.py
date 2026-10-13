"""
Smart Health Monitoring System — Streamlit Analytics & Evidence Dashboard.

Comprehensive, read-only analytics dashboard demonstrating:
1. Patient telemetry analytics.
2. Heart-rate, SpO2, and temperature trends (hourly and daily).
3. Patient-level and time-based aggregation.
4. Data quality diagnostics and dataset coverage.
5. Clinical alert triage and lifecycle response.
6. SQL vs. NoSQL benchmark results from Part 3C.
7. Database connectivity and transactional mirror synchronization status.

Usage:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import streamlit as st

# Configure wide layout and page metadata
st.set_page_config(
    page_title="Smart Health Analytics Dashboard",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom High-Contrast Healthcare CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1a365d;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #4a5568;
        margin-bottom: 1.2rem;
    }
    .disclaimer-banner {
        background-color: #fffaf0;
        border-left: 4px solid #dd6b20;
        padding: 8px 12px;
        border-radius: 4px;
        color: #7b341e;
        font-size: 0.85rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

from dashboard.data_access import (
    fetch_patient_ids,
    probe_system_connectivity,
)
from dashboard.sections.alert_analytics import render_alert_analytics_section
from dashboard.sections.benchmarks import render_benchmarks_section
from dashboard.sections.data_quality import render_data_quality_section
from dashboard.sections.overview import render_overview_section
from dashboard.sections.patient_analytics import render_patient_analytics_section
from dashboard.sections.patient_comparison import render_patient_comparison_section
from dashboard.sections.system_status import render_system_status_section
from dashboard.sections.time_series import render_time_series_section


def main() -> None:
    """Streamlit Application Entrypoint."""
    
    # -------------------------------------------------------------------------
    # Sidebar Controls & Global Configuration
    # -------------------------------------------------------------------------
    with st.sidebar:
        st.markdown("### 🏥 System Navigation")
        st.markdown("---")

        # 1. Connectivity Status Preview
        connectivity = probe_system_connectivity()
        st.markdown("**Infrastructure Status:**")
        mysql_color = "🟢" if connectivity["mysql_connected"] else "🔴"
        mongo_color = "🟢" if connectivity["mongo_connected"] else "🟡"
        st.caption(f"{mysql_color} MySQL: `{connectivity['mysql_status']}`")
        st.caption(f"{mongo_color} MongoDB: `{connectivity['mongo_status']}`")

        st.markdown("---")

        # 2. Execution Mode Selection
        st.markdown("**Data Source Mode:**")
        force_fallback = st.checkbox(
            "Force Local Dataset Fixture",
            value=not connectivity["mysql_connected"],
            help="When checked or when live databases are offline, uses the verified Kaggle dataset fixture in memory.",
        )

        backend_choice = st.radio(
            "Active Query Engine:",
            options=["SQL (Relational)", "MongoDB (Document Mirror)"],
            index=0,
            help="Select which database engine processes the analytical aggregation queries.",
        )
        backend = "sql" if "SQL" in backend_choice else "mongodb"

        st.markdown("---")

        # 3. Global Patient Filter
        st.markdown("**Cohort Filter:**")
        patient_ids = fetch_patient_ids(backend=backend, force_fallback=force_fallback)
        global_patient_id = None
        if patient_ids:
            sel_opt = ["All Patients"] + patient_ids
            chosen = st.selectbox("Active Patient:", options=sel_opt, index=0)
            if chosen != "All Patients":
                global_patient_id = chosen

        st.markdown("---")

        # 4. Refresh Button
        if st.button("🔄 Refresh Analytics Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.caption(f"Environment: **{connectivity['app_env']}**")
        st.caption("Antigravity DA3 Health Telemetry Suite")

    # -------------------------------------------------------------------------
    # Hero Title and Healthcare Disclaimer Banner
    # -------------------------------------------------------------------------
    st.markdown('<div class="main-header">Smart Health Monitoring System</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">'
        'Coursework Analytics & Empirical Evidence Dashboard: '
        'Telemetry Streams, Parity Benchmarks, and Data Quality Diagnostics'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="disclaimer-banner">'
        '⚠️ <b>Clinical & Academic Notice:</b> This dashboard is an analytics and coursework-evidence interface. '
        'Vital sign summaries are computed from authoritative records and must not be used for autonomous medical diagnosis. '
        'This interface does not replace the clinician application or backend API gateway.'
        '</div>',
        unsafe_allow_html=True,
    )

    # -------------------------------------------------------------------------
    # Main Navigation Tabs (All 8 Core Sections)
    # -------------------------------------------------------------------------
    tab_overview, tab_patient, tab_series, tab_comp, tab_quality, tab_alerts, tab_bench, tab_status = st.tabs([
        "📊 Overview",
        "👤 Patient Analytics",
        "📈 Time-Series Trends",
        "👥 Patient Comparison",
        "🔍 Data Quality",
        "🚨 Clinical Alerts",
        "⚡ SQL vs NoSQL Benchmarks",
        "⚙️ System Status",
    ])

    with tab_overview:
        render_overview_section(backend=backend, force_fallback=force_fallback)

    with tab_patient:
        render_patient_analytics_section(
            selected_patient_id=global_patient_id,
            backend=backend,
            force_fallback=force_fallback,
        )

    with tab_series:
        render_time_series_section(
            selected_patient_id=global_patient_id,
            backend=backend,
            force_fallback=force_fallback,
        )

    with tab_comp:
        render_patient_comparison_section(backend=backend, force_fallback=force_fallback)

    with tab_quality:
        render_data_quality_section(backend=backend, force_fallback=force_fallback)

    with tab_alerts:
        render_alert_analytics_section(backend=backend, force_fallback=force_fallback)

    with tab_bench:
        render_benchmarks_section()

    with tab_status:
        render_system_status_section(backend=backend, force_fallback=force_fallback)


if __name__ == "__main__":
    main()
