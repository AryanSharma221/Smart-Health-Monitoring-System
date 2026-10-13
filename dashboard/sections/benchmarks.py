"""
Section G: SQL vs NoSQL Performance Benchmarks and Query Plan Explorer.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.components.charts import build_benchmark_latency_comparison_chart
from dashboard.components.metrics import render_badge, render_metric_card
from dashboard.data_access import (
    list_benchmark_runs,
    load_benchmark_details,
    load_benchmark_samples_df,
)


def render_benchmarks_section() -> None:
    """Render Section G: SQL vs NoSQL Benchmark Results."""
    st.subheader("SQL (InnoDB) vs. NoSQL (MongoDB Atlas) Performance Benchmarks")
    st.markdown(
        "Empirical latency, throughput, and equivalence comparisons across the 7 standardized "
        "coursework analytical workloads executed under controlled conditions."
    )

    # 1. Discover available benchmark runs
    runs = list_benchmark_runs()
    if not runs:
        st.warning(
            "**No Benchmark Artifacts Found**\n\n"
            "No `bench_*.json` result files were located in `benchmarks/results/`.\n"
            "To generate benchmark results, execute:\n"
            "```bash\npython -m benchmarks.run_benchmarks --iterations 20\n```"
        )
        return

    # 2. Benchmark Run Selector
    run_options = {r["run_id"]: f"{r['run_id']} ({r.get('timestamp_utc', '')[:16]} UTC | {r.get('iterations')} iters)" for r in runs}
    selected_run_id = st.selectbox(
        "Select Benchmark Execution Artifact:",
        options=list(run_options.keys()),
        format_func=lambda rid: run_options[rid],
        key="sec_g_benchmark_run_selector",
    )

    details = load_benchmark_details(selected_run_id)
    if not details:
        st.error(f"Failed to parse benchmark details for '{selected_run_id}'.")
        return

    meta = details.get("metadata", {})
    summary = details.get("summary", {})
    workloads = details.get("workload_results", [])
    env = meta.get("environment", {})

    # 3. Execution Metadata Header
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        render_metric_card(
            label="Total Workloads",
            value=summary.get("total_workloads", len(workloads)),
            help_text="Standardized analytical query workloads evaluated.",
        )
    with col_m2:
        eq_passed = summary.get("equivalence_passed_count", 0)
        tot_w = summary.get("total_workloads", len(workloads))
        render_metric_card(
            label="Mathematical Equivalence",
            value=f"{eq_passed}/{tot_w}",
            delta="100% Pass" if eq_passed == tot_w else f"{tot_w - eq_passed} Failed",
            delta_color="normal" if eq_passed == tot_w else "inverse",
            help_text="Verifies relational SQL and Mongo aggregation pipelines produce identical mathematical results.",
        )
    with col_m3:
        render_metric_card(
            label="Measured Iterations",
            value=meta.get("measured_iterations", 0),
            unit="runs/workload",
            help_text="Warmup iterations excluded from timing statistics.",
        )
    with col_m4:
        render_metric_card(
            label="Benchmark Duration",
            value=meta.get("duration_seconds", 0.0),
            unit="sec",
            help_text="Total execution time of the benchmark suite.",
        )

    st.caption(
        f"Environment: **Python {env.get('python_version', '--')}** on **{env.get('system_os', '--')} {env.get('os_release', '')} ({env.get('machine', '')})** | "
        f"Timestamp: **{meta.get('timestamp_utc', '')}**"
    )

    st.divider()

    # 4. Comparative Bar Charts
    st.markdown("##### Median Query Latency Comparison (ms)")
    chart = build_benchmark_latency_comparison_chart(workloads)
    st.altair_chart(chart, use_container_width=True)

    # 5. Workload Comparison Table
    st.markdown("##### Detailed Workload Performance & Parity Breakdown")

    rows = []
    for w in workloads:
        w_id = w.get("workload_id", "")
        w_name = w.get("name", "")
        eq_pass = w.get("equivalence_passed", False)
        s_stats = w.get("sql_stats", {})
        m_stats = w.get("mongo_stats", {})
        speed_ratio = w.get("speed_ratio", 0.0)

        rows.append({
            "Workload ID": w_id,
            "Workload Name": w_name,
            "Equivalence": "PASS" if eq_pass else "FAIL",
            "SQL Median (ms)": s_stats.get("median_ms", 0.0),
            "SQL P95 (ms)": s_stats.get("p95_ms", 0.0),
            "Mongo Median (ms)": m_stats.get("median_ms", 0.0),
            "Mongo P95 (ms)": m_stats.get("p95_ms", 0.0),
            "Speed Ratio (SQL/Mongo)": speed_ratio,
            "Result Items": w.get("sql_item_count", 0),
        })

    workload_df = pd.DataFrame(rows)
    st.dataframe(workload_df, use_container_width=True, hide_index=True)

    # 6. Raw Sample Latency Distributions (if CSV present)
    samples_df = load_benchmark_samples_df(selected_run_id)
    if samples_df is not None and not samples_df.empty:
        st.markdown("---")
        st.markdown("##### Raw Iteration Latency Distribution (ms)")
        st.caption("Individual timings across all measured iterations showing latency variance and stability.")

        sample_chart = (
            alt.Chart(samples_df)
            .mark_boxplot(extent="min-max")
            .encode(
                x=alt.X("engine:N", title="Database Engine"),
                y=alt.Y("latency_ms:Q", title="Execution Latency (ms)", scale=alt.Scale(type="log", base=10)),
                color=alt.Color("engine:N", scale=alt.Scale(domain=["MySQL/SQL", "MongoDB"], range=["#1f77b4", "#ff7f0e"])),
                column=alt.Column("workload_id:N", title="Workload"),
                tooltip=["workload_id:N", "engine:N", "latency_ms:Q", "iteration:Q"],
            )
            .properties(width=100, height=280)
        )
        st.altair_chart(sample_chart, use_container_width=True)

    # 7. Query Plan Findings Expander
    with st.expander("Inspect Workload Business Questions & Methodology"):
        for w in workloads:
            st.markdown(f"**{w.get('workload_id')}: {w.get('name')}**")
            st.markdown(f"- *Question:* {w.get('business_question')}")
            st.markdown(f"- *Equivalence:* `{'PASS' if w.get('equivalence_passed') else 'FAIL'}`")
            plans = w.get("query_plans", {})
            if plans:
                st.code(str(plans), language="json")
