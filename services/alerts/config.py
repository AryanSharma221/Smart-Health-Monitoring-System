"""
Alert Source Eligibility and Provenance Policy Configuration.

Enforces clear provenance boundaries:
- Live streaming and simulated data generate real-time alerts.
- Historical Kaggle dataset rows are NOT treated as active medical emergencies
  and are evaluated only during explicit, intentional backfill operations.
"""

from __future__ import annotations

from typing import Set

# Sources eligible for real-time live alert generation
LIVE_ELIGIBLE_SOURCES: Set[str] = {
    "simulator",
    "wearable",
    "live_stream",
    "mqtt_telemetry",
    "self_added",
}


def is_source_eligible_for_alerts(
    source: str,
    is_simulated: bool,
    allow_historical: bool = False,
) -> bool:
    """
    Determine whether an incoming observation source is eligible for alert evaluation.
    
    Rules:
    1. Simulated data (is_simulated=True) is always eligible for demo evaluation.
    2. Registered live sources (e.g. simulator, wearable) are eligible.
    3. Historical batch imports (e.g. source='kaggle', is_simulated=False) are
       strictly excluded from live alert generation unless allow_historical=True.
    """
    if is_simulated:
        return True

    if source.lower() in LIVE_ELIGIBLE_SOURCES:
        return True

    if source.lower() == "kaggle" or not is_simulated:
        return allow_historical

    return False
