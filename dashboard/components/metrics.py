"""
Custom Metric Cards and Status Badges for Streamlit Health Analytics Dashboard.

Provides healthcare-styled UI components with explicit units and clinical disclaimers.
"""

from __future__ import annotations

from typing import Any, Optional
import streamlit as st


def render_metric_card(
    label: str,
    value: Any,
    unit: Optional[str] = None,
    delta: Optional[str] = None,
    help_text: Optional[str] = None,
) -> None:
    """
    Render a clean, high-contrast metric card with explicit units and optional delta.
    """
    display_val = str(value) if value is not None else "--"
    if unit and display_val != "--":
        display_val = f"{display_val} {unit}"

    st.metric(
        label=label,
        value=display_val,
        delta=delta,
        help=help_text,
    )


def render_badge(status: str, text: str) -> str:
    """
    Generate an HTML/markdown badge for statuses and connectivity.
    """
    colors = {
        "success": ("#e6f4ea", "#137333", "#ceead6"),
        "danger": ("#fce8e6", "#c5221f", "#fad2cf"),
        "warning": ("#fef7e0", "#b06000", "#feefc3"),
        "info": ("#e8f0fe", "#1a73e8", "#d2e3fc"),
        "neutral": ("#f1f3f4", "#3c4043", "#dadce0"),
    }
    bg, fg, border = colors.get(status, colors["neutral"])
    return (
        f'<span style="background-color: {bg}; color: {fg}; border: 1px solid {border}; '
        f'padding: 3px 8px; border-radius: 12px; font-size: 0.82rem; font-weight: 600; '
        f'display: inline-block; margin-right: 4px;">{text}</span>'
    )


def render_alert_severity_badge(severity: str) -> str:
    """Badge for clinical alert severity."""
    sev = str(severity).upper()
    if sev == "CRITICAL":
        return render_badge("danger", "CRITICAL")
    elif sev == "HIGH":
        return render_badge("warning", "HIGH")
    elif sev == "MEDIUM":
        return render_badge("info", "MEDIUM")
    return render_badge("neutral", sev)
