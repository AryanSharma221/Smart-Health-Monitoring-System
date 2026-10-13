"""
Altair Chart Components for Streamlit Health Analytics Dashboard.

Enforces:
- Explicit units on all axes (bpm, %, °F, ms).
- Independent time-series charts to avoid misleading scale compressions.
- Honest gap rendering (no synthetic interpolation of missing timestamps).
- Comparative benchmark visualizations for median and p95 latencies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import altair as alt
import pandas as pd


def build_vitals_time_series_chart(
    df: pd.DataFrame,
    time_col: str,
    val_col: str,
    title: str,
    y_axis_title: str,
    line_color: str = "#1f77b4",
    min_val_col: Optional[str] = None,
    max_val_col: Optional[str] = None,
) -> alt.Chart:
    """
    Construct an Altair time-series chart with optional min/max boundary envelopes.
    Missing intervals are rendered honestly without artificial smoothing or interpolation.
    """
    if df.empty or time_col not in df.columns or val_col not in df.columns:
        return alt.Chart(pd.DataFrame({"msg": ["No data available"]})).mark_text().encode(text="msg")

    clean_df = df.copy()
    clean_df[time_col] = pd.to_datetime(clean_df[time_col])
    clean_df = clean_df.dropna(subset=[val_col]).sort_values(by=time_col)

    base = alt.Chart(clean_df).encode(
        x=alt.X(f"{time_col}:T", title="Timestamp (UTC)", axis=alt.Axis(format="%Y-%m-%d %H:%M")),
    )

    layers = []

    # Optional min-max envelope for bucketed aggregates
    if min_val_col and max_val_col and min_val_col in clean_df.columns and max_val_col in clean_df.columns:
        area = base.mark_area(opacity=0.18, color=line_color).encode(
            y=alt.Y(f"{min_val_col}:Q", title=y_axis_title),
            y2=alt.Y2(f"{max_val_col}:Q"),
        )
        layers.append(area)

    # Primary line with distinct data points
    line = base.mark_line(color=line_color, strokeWidth=2).encode(
        y=alt.Y(f"{val_col}:Q", title=y_axis_title, scale=alt.Scale(zero=False)),
        tooltip=[
            alt.Tooltip(f"{time_col}:T", title="Time", format="%Y-%m-%d %H:%M"),
            alt.Tooltip(f"{val_col}:Q", title=y_axis_title, format=".1f"),
        ],
    )
    points = base.mark_circle(size=30, color=line_color).encode(
        y=alt.Y(f"{val_col}:Q"),
        tooltip=[
            alt.Tooltip(f"{time_col}:T", title="Time", format="%Y-%m-%d %H:%M"),
            alt.Tooltip(f"{val_col}:Q", title=y_axis_title, format=".1f"),
        ],
    )
    layers.extend([line, points])

    chart = alt.layer(*layers).properties(
        title=title,
        height=260,
    ).interactive()

    return chart


def build_patient_comparison_bar_chart(
    df: pd.DataFrame,
    metric_name: str,
    y_axis_title: str,
    bar_color: str = "#2ca02c",
) -> alt.Chart:
    """
    Construct side-by-side comparative bar chart across patients for a given metric.
    """
    if df.empty or "patient_id" not in df.columns:
        return alt.Chart(pd.DataFrame({"msg": ["No comparison data"]})).mark_text().encode(text="msg")

    chart = (
        alt.Chart(df)
        .mark_bar(color=bar_color, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("patient_id:N", title="Patient ID", sort="ascending"),
            y=alt.Y(f"{metric_name}:Q", title=y_axis_title, scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("patient_id:N", title="Patient"),
                alt.Tooltip(f"{metric_name}:Q", title=y_axis_title, format=".2f"),
                alt.Tooltip("valid_count:Q", title="Observations"),
            ],
        )
        .properties(height=260)
    )
    return chart


def build_benchmark_latency_comparison_chart(workloads: List[Dict[str, Any]]) -> alt.Chart:
    """
    Construct comparative grouped bar chart of MySQL vs MongoDB median latencies.
    """
    records = []
    for w in workloads:
        w_name = w.get("name", w.get("workload_id", "Unknown"))
        sql_median = w.get("sql_stats", {}).get("median_ms", 0.0)
        mongo_median = w.get("mongo_stats", {}).get("median_ms", 0.0)
        sql_p95 = w.get("sql_stats", {}).get("p95_ms", 0.0)
        mongo_p95 = w.get("mongo_stats", {}).get("p95_ms", 0.0)

        records.append({
            "Workload": w_name,
            "Database": "MySQL (InnoDB)",
            "Median Latency (ms)": sql_median,
            "P95 Latency (ms)": sql_p95,
        })
        records.append({
            "Workload": w_name,
            "Database": "MongoDB Atlas",
            "Median Latency (ms)": mongo_median,
            "P95 Latency (ms)": mongo_p95,
        })

    df = pd.DataFrame(records)
    if df.empty:
        return alt.Chart(pd.DataFrame({"msg": ["No benchmark results available"]})).mark_text().encode(text="msg")

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("Database:N", title=None),
            y=alt.Y("Median Latency (ms):Q", title="Median Query Latency (ms)"),
            color=alt.Color("Database:N", scale=alt.Scale(domain=["MySQL (InnoDB)", "MongoDB Atlas"], range=["#1f77b4", "#ff7f0e"])),
            column=alt.Column("Workload:N", title="Workload", header=alt.Header(labelAngle=-25)),
            tooltip=["Workload:N", "Database:N", "Median Latency (ms):Q", "P95 Latency (ms):Q"],
        )
        .properties(width=100, height=280)
    )
    return chart


def build_provenance_chart(breakdown: List[Dict[str, Any]]) -> alt.Chart:
    """
    Construct bar chart breakdown of telemetry records by origin source.
    """
    df = pd.DataFrame(breakdown)
    if df.empty:
        return alt.Chart(pd.DataFrame({"msg": ["No provenance records"]})).mark_text().encode(text="msg")

    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("source:N", title="Source System"),
            y=alt.Y("document_count:Q", title="Total Records"),
            color=alt.Color("is_simulated:N", title="Simulated?", scale=alt.Scale(domain=[True, False], range=["#ffbb78", "#1f77b4"])),
            tooltip=["source:N", "document_count:Q", "is_simulated:N"],
        )
        .properties(height=240)
    )
    return chart
