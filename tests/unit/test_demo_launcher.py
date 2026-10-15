"""
Unit tests for Part 6M — Smart Health Monitoring System Demo Launcher & Preflight Suite.
Verifies preflight checks, secrets redaction, port detection, and simulator stopped baseline.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

from scripts.preflight_check import (
    check_configuration,
    check_local_database,
    check_ml_artifacts,
    check_runtimes,
    record_check,
    results,
    run_preflight,
)
from simulator.config import SimulatorSettings
from simulator.generator import TelemetryGenerator


@pytest.fixture(autouse=True)
def clean_results():
    """Clear preflight check global results list between tests."""
    results.clear()
    yield
    results.clear()


def test_simulator_default_stopped_baseline():
    """Requirement 4: Verify simulator settings default to auto_start=False."""
    settings = SimulatorSettings()
    assert settings.auto_start is False, "Simulator must not auto-start random data generation on boot."
    gen = TelemetryGenerator(settings)
    assert gen.is_running is False
    assert gen.lifecycle_state == "STOPPED"


def test_preflight_offline_run_passes():
    """Verify offline preflight verification passes without requiring active server ports."""
    success = run_preflight(live_checks=False)
    assert success is True, "Offline preflight check must pass in standard repository state."

    # Verify check categories
    ids = {r["id"] for r in results}
    assert "RUNTIME-PYTHON" in ids
    assert "CONFIG-ENV-FILE" in ids
    assert "DB-FILE" in ids
    assert "DB-SCHEMA-TABLES" in ids
    assert "ML-MODEL-FILE" in ids

    # Ensure zero failures
    fails = [r for r in results if r["status"] == "FAIL"]
    assert len(fails) == 0, f"Unexpected failures in offline preflight: {fails}"


def test_preflight_secrets_are_redacted(capsys):
    """Requirement 2: Validate presence of configuration files without printing secret values."""
    check_configuration()
    captured = capsys.readouterr()

    # Read real .env to get actual secrets
    jwt_secret = None
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if line.startswith("JWT_SECRET="):
                    jwt_secret = line.split("=", 1)[1].strip().strip("'\"")

    if jwt_secret:
        assert jwt_secret not in captured.out, "Plaintext JWT_SECRET must NEVER be printed in stdout."

    # Look for redaction label
    jwt_results = [r for r in results if r["id"] == "CONFIG-JWT-SECRET"]
    assert len(jwt_results) == 1
    assert "[REDACTED]" in jwt_results[0]["detail"]


def test_preflight_warn_does_not_fail_optional_services():
    """Requirement 3: An unavailable optional analytics dashboard must not be reported as a total failure."""
    record_check(
        check_id="SVC-UI-STREAMLIT",
        category="Analytics",
        name="Streamlit DA3 Visualizer (:8501)",
        status="WARN",
        detail="Streamlit offline (Optional DA3 analytics dashboard)",
    )
    # Filter non-failures
    has_fails = any(r["status"] == "FAIL" for r in results)
    assert not has_fails, "WARN status on optional Streamlit dashboard must not trigger a FAIL status."


def test_preflight_handles_missing_database_gracefully(tmp_path):
    """Verify preflight cleanly marks missing database as FAIL without unhandled exception."""
    with patch("os.path.exists", side_effect=lambda path: False if "smart_health_local.db" in str(path) else os.path.exists(path)):
        check_local_database()
        db_results = [r for r in results if r["id"] == "DB-FILE"]
        assert len(db_results) == 1
        assert db_results[0]["status"] == "FAIL"
        assert "not found" in db_results[0]["detail"]


def test_preflight_handles_missing_env_file():
    """Verify preflight cleanly marks missing .env as FAIL without crashing."""
    with patch("os.path.exists", side_effect=lambda path: False if str(path).endswith(".env") else os.path.exists(path)):
        check_configuration()
        env_results = [r for r in results if r["id"] == "CONFIG-ENV-FILE"]
        assert len(env_results) == 1
        assert env_results[0]["status"] == "FAIL"
        assert ".env file not found" in env_results[0]["detail"]
