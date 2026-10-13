"""
Section H: System Infrastructure Status, Connectivity Probes, and Mirror Synchronization.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.metrics import render_badge, render_metric_card
from dashboard.data_access import (
    fetch_dataset_overview,
    fetch_outbox_statistics,
    probe_system_connectivity,
)


def render_system_status_section(
    backend: str = "sql",
    force_fallback: bool = False,
) -> None:
    """Render Section H: System Status and Health Diagnostics."""
    st.subheader("System Infrastructure & Synchronization Status")
    st.markdown(
        "Live operational status of primary relational storage, analytics document mirror, "
        "transactional outbox synchronization queue, and data freshness boundaries."
    )

    # 1. Probe connectivity and metrics
    connectivity = probe_system_connectivity()
    outbox_data = fetch_outbox_statistics(force_fallback=force_fallback)
    overview = fetch_dataset_overview(backend=backend, force_fallback=force_fallback)

    # 2. Connectivity Cards
    col_c1, col_c2, col_c3 = st.columns(3)

    with col_c1:
        my_ok = connectivity.get("mysql_connected", False)
        my_stat = "success" if my_ok else "danger"
        render_metric_card(
            label="MySQL 8 (Authoritative Store)",
            value="ONLINE" if my_ok else "OFFLINE",
            delta=connectivity.get("mysql_status", "--"),
            delta_color="normal" if my_ok else "inverse",
            help_text="Primary relational database hosting canonical patients, readings, users, and audit records.",
        )

    with col_c2:
        mo_ok = connectivity.get("mongo_connected", False)
        mo_stat = "success" if mo_ok else "warning"
        render_metric_card(
            label="MongoDB Atlas (Analytics Mirror)",
            value="ONLINE" if mo_ok else "DEGRADED",
            delta=connectivity.get("mongo_status", "--"),
            delta_color="normal" if mo_ok else "inverse",
            help_text="Analytics document mirror hosting denormalized telemetry documents and aggregation pipelines.",
        )

    with col_c3:
        latest = overview.get("latest_measured_at")
        latest_str = latest.strftime("%Y-%m-%d %H:%M UTC") if latest else "--"
        render_metric_card(
            label="Data Freshness (Latest Record)",
            value=latest_str,
            help_text="Most recent observation timestamp persisted in the active database.",
        )

    st.divider()

    # 3. Transactional Outbox Synchronization Status
    st.markdown("##### Transactional Outbox Synchronization Queue")
    st.markdown(
        "Tracks reliable, idempotent synchronization of operational MySQL events "
        "to the MongoDB Atlas analytics mirror."
    )

    stats = outbox_data.get("stats", {})
    col_o1, col_o2, col_o3, col_o4 = st.columns(4)

    with col_o1:
        render_metric_card(
            label="Completed Syncs",
            value=f"{stats.get('completed', 0):,}",
            unit="events",
            help_text="Successfully mirrored events confirmed by Atlas write acknowledgment.",
        )
    with col_o2:
        render_metric_card(
            label="Pending Syncs",
            value=stats.get("pending", 0),
            unit="queued",
            help_text="Events waiting to be picked up by the Outbox processor.",
        )
    with col_o3:
        render_metric_card(
            label="Processing Syncs",
            value=stats.get("processing", 0),
            unit="active",
            help_text="Events currently inflight to MongoDB.",
        )
    with col_o4:
        failed_cnt = stats.get("failed", 0)
        render_metric_card(
            label="Failed / Exhausted Syncs",
            value=failed_cnt,
            delta="0 expected" if failed_cnt == 0 else f"{failed_cnt} failed",
            delta_color="normal" if failed_cnt == 0 else "inverse",
            help_text="Events that exceeded max retry attempts (moved to dead-letter queue).",
        )

    if "note" in outbox_data:
        st.caption(f"Note: {outbox_data['note']}")

    st.markdown("---")

    # 4. Security & Isolation Invariants
    st.markdown("##### Security and Credential Protection Policy")
    st.markdown(
        "- **Zero Credential Exposure:** Database passwords, SRV tokens, and JWT secrets are strictly "
        "redacted and never transmitted or rendered in dashboard components.\n"
        "- **Read-Only Analytics Layer:** The dashboard data access layer enforces read-only operations "
        "(`SELECT` / `.aggregate()`), guaranteeing operational data integrity.\n"
        "- **Degraded-Mode Resilience:** When cloud databases or network endpoints are unavailable, "
        "the dashboard operates safely in offline/fixture mode without hanging or leaking tracebacks."
    )
