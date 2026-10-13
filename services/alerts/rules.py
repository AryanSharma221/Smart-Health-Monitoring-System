"""
Clinical Threshold Rule Definitions and Evaluation Logic.

Defines deterministic, configurable demonstration thresholds for vital sign anomalies.
NOTE: These thresholds are provisional demonstration defaults for software verification
and simulated telemetry — NOT FOR MEDICAL USE OR CLINICAL DIAGNOSIS.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from database.mysql.models import VitalsReading


@dataclass(frozen=True)
class AlertRuleDefinition:
    """Immutable rule configuration for deterministic health observation evaluation."""

    rule_id: str
    metric_code: str
    operator: str
    configured_value: Decimal
    unit: str
    severity: str
    category: str = "vital_threshold"
    is_enabled: bool = True
    is_demo_only: bool = True
    description: str = ""

    def evaluate(self, reading: VitalsReading) -> bool:
        """
        Evaluate reading against this rule.
        Returns True if condition is met (threshold breached), False otherwise.
        Strictly enforces:
        1. Rule is enabled.
        2. Reading quality_status is 'valid'.
        3. Measurement metric matches rule metric.
        4. Units match exactly (never mixes units).
        5. Reading value is present (never treats None as zero).
        """
        if not self.is_enabled:
            return False

        if getattr(reading, "quality_status", None) != "valid":
            return False

        if getattr(reading, "metric_code", None) != self.metric_code:
            return False

        if getattr(reading, "value", None) is None:
            return False

        # Unit verification guard
        if getattr(reading, "unit", None) != self.unit:
            return False

        try:
            val = Decimal(str(reading.value))
        except (ValueError, TypeError):
            return False

        threshold = self.configured_value

        if self.operator == ">":
            return val > threshold
        elif self.operator == "<":
            return val < threshold
        elif self.operator == ">=":
            return val >= threshold
        elif self.operator == "<=":
            return val <= threshold
        elif self.operator == "==":
            return val == threshold
        elif self.operator == "!=":
            return val != threshold

        return False


# =============================================================================
# Standard Clinical Demonstration Rules Catalog (Provisional Defaults)
# =============================================================================

DEFAULT_ALERT_RULES: List[AlertRuleDefinition] = [
    AlertRuleDefinition(
        rule_id="RULE_HR_HIGH",
        metric_code="heart_rate",
        operator=">",
        configured_value=Decimal("100.00"),
        unit="bpm",
        severity="HIGH",
        description="Heart rate exceeds 100 bpm (demonstration threshold for tachycardia).",
    ),
    AlertRuleDefinition(
        rule_id="RULE_HR_CRITICAL_HIGH",
        metric_code="heart_rate",
        operator=">",
        configured_value=Decimal("130.00"),
        unit="bpm",
        severity="CRITICAL",
        description="Heart rate exceeds 130 bpm (demonstration threshold for severe tachycardia).",
    ),
    AlertRuleDefinition(
        rule_id="RULE_HR_LOW",
        metric_code="heart_rate",
        operator="<",
        configured_value=Decimal("50.00"),
        unit="bpm",
        severity="MEDIUM",
        description="Heart rate is below 50 bpm (demonstration threshold for bradycardia).",
    ),
    AlertRuleDefinition(
        rule_id="RULE_SPO2_LOW",
        metric_code="spo2",
        operator="<",
        configured_value=Decimal("90.00"),
        unit="%",
        severity="HIGH",
        description="Blood oxygen saturation is below 90% (demonstration threshold for hypoxemia).",
    ),
    AlertRuleDefinition(
        rule_id="RULE_SPO2_CRITICAL_LOW",
        metric_code="spo2",
        operator="<",
        configured_value=Decimal("85.00"),
        unit="%",
        severity="CRITICAL",
        description="Blood oxygen saturation is below 85% (demonstration threshold for severe hypoxemia).",
    ),
    AlertRuleDefinition(
        rule_id="RULE_TEMP_HIGH",
        metric_code="temperature",
        operator=">",
        configured_value=Decimal("38.00"),
        unit="degC",
        severity="MEDIUM",
        description="Body temperature exceeds 38.0°C / 100.4°F (demonstration threshold for fever).",
    ),
    AlertRuleDefinition(
        rule_id="RULE_TEMP_CRITICAL_HIGH",
        metric_code="temperature",
        operator=">",
        configured_value=Decimal("39.50"),
        unit="degC",
        severity="CRITICAL",
        description="Body temperature exceeds 39.5°C / 103.1°F (demonstration threshold for high fever).",
    ),
    AlertRuleDefinition(
        rule_id="RULE_TEMP_LOW",
        metric_code="temperature",
        operator="<",
        configured_value=Decimal("35.00"),
        unit="degC",
        severity="HIGH",
        description="Body temperature is below 35.0°C / 95.0°F (demonstration threshold for hypothermia).",
    ),
]

RULES_BY_ID: Dict[str, AlertRuleDefinition] = {r.rule_id: r for r in DEFAULT_ALERT_RULES}
