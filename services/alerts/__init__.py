"""
Clinical Alerts and Threshold Evaluation Package.
"""

from services.alerts.config import LIVE_ELIGIBLE_SOURCES, is_source_eligible_for_alerts
from services.alerts.evaluator import AlertEvaluator, generate_deterministic_alert_id
from services.alerts.rules import DEFAULT_ALERT_RULES, AlertRuleDefinition

__all__ = [
    "AlertRuleDefinition",
    "DEFAULT_ALERT_RULES",
    "LIVE_ELIGIBLE_SOURCES",
    "is_source_eligible_for_alerts",
    "AlertEvaluator",
    "generate_deterministic_alert_id",
]
