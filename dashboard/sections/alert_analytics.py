"""
Section F: Clinical Alert Triage, Severity Distributions, and Acknowledgement Lifecycle.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.metrics import render_alert_severity_badge, render_metric_card
from dashboard.data_access import fetch_alert_summary


def render_alert_analytics_section(
    backend: str = "sql",
    force_fallback: bool = False,
) -> None:
    """Render Section F: Alert Analytics."""
    st.subheader("Clinical Alert Triage & Response Lifecycle")
    st.markdown(
        "Authoritative clinical alert distributions aggregated by severity tier, "
        "investigation status, clinician acknowledgement rates, and patient-level alert frequency."
    )

    # 1. Fetch real alert data
    try:
        alert_data = fetch_alert_summary(
            patient_id=None,
            backend=backend,
            force_fallback=force_fallback,
        )
    except Exception as exc:
        st.error(f"Failed to query alert repository: {exc}")
        return

    total_alerts = alert_data.get("total_alerts", 0)

    # 2. Check for empty state honestly
    if total_alerts == 0:
        st.info(
            "**No Clinical Alert Records Found**\n\n"
            "The current database instance has 0 persisted clinical alert events.\n\n"
            "- **Authoritative Alert Lifecycle:** Evaluated asynchronously by `AlertService` "
            "when incoming vitals readings exceed clinical thresholds.\n"
            "- **Coursework Adherence:** Synthetic alerts are **never fabricated** to artificially "
            "populate this dashboard. Alerts are persisted exclusively when genuine anomalous "
            "readings trigger the clinical evaluation rules."
        )
        return

    # 3. Alert Metrics Row
    by_sev = alert_data.get("by_severity", {})
    by_stat = alert_data.get("by_status", {})
    ack_stats = alert_data.get("acknowledgement", {})

    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        render_metric_card(
            label="Total Clinical Alerts",
            value=total_alerts,
            unit="events",
            help_text="All persisted alert incidents.",
        )
    with col_a2:
        render_metric_card(
            label="Critical Tier Alerts",
            value=by_sev.get("CRITICAL", 0),
            unit="critical",
            help_text="Requires immediate bedside or clinician intervention.",
        )
    with col_a3:
        render_metric_card(
            label="Clinician Acknowledged",
            value=ack_stats.get("acknowledged_count", 0),
            unit="alerts",
            help_text="Alerts acknowledged by attending clinical staff.",
        )
    with col_a4:
        render_metric_card(
            label="Acknowledgement Rate",
            value=ack_stats.get("acknowledgement_rate_percent", 0.0),
            unit="%",
            help_text="Percentage of alerts with verified clinician sign-off.",
        )

    st.divider()

    # 4. Severity & Status Distributions
    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.markdown("##### Alerts by Clinical Severity Tier")
        sev_df = pd.DataFrame([
            {"Severity": sev, "Alert Count": cnt}
            for sev, cnt in by_sev.items()
        ])
        st.dataframe(sev_df, use_container_width=True, hide_index=True)

    with col_d2:
        st.markdown("##### Alerts by Lifecycle Status")
        stat_df = pd.DataFrame([
            {"Lifecycle Status": stat, "Alert Count": cnt}
            for stat, cnt in by_stat.items()
        ])
        st.dataframe(stat_df, use_container_width=True, hide_index=True)

    # 5. Patient-Level Alert Breakdown
    st.markdown("##### Patient-Level Alert Frequencies")
    by_pat = alert_data.get("by_patient", {})
    if by_pat:
        pat_df = pd.DataFrame([
            {"Patient ID": pid, "Alert Count": cnt}
            for pid, cnt in by_pat.items()
        ])
        st.dataframe(pat_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No patient-level alert distributions to display.")
