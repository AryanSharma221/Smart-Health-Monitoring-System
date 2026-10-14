"""
Unit tests for the centralized configuration foundation.

Verifies:
1. Safe default settings for development.
2. Environment-variable overrides.
3. Robust CORS origin parsing (list, comma-separated string, JSON string).
4. Validation of port bounds and log levels.
5. URL-encoding and masking of MySQL credentials.
6. Enforcement of production security invariants (JWT secret length, DB password).
7. MongoDB Atlas validation on demand.
8. Dataset path resolution.
9. Masking of secrets in string representation.
10. FastAPI integration with /health endpoint.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.api.config import Settings, get_settings
from services.api.main import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Ensure settings cache is cleared before and after each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_default_development_settings(monkeypatch):
    """Verify non-sensitive default development settings."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    settings = Settings()
    assert settings.app_name == "Smart Health Monitoring System"
    assert settings.app_env == "development"
    assert settings.app_debug is False
    assert settings.api_port == 8000
    assert settings.mysql_host == "localhost"
    assert settings.mysql_port == 3306
    assert settings.mysql_database == "smart_health"
    assert settings.mysql_user == "smart_health_app"
    assert settings.mysql_password == ""
    assert settings.dataset_source_timezone == "UTC"
    assert len(settings.cors_origins) >= 1


def test_environment_variable_override(monkeypatch):
    """Verify that environment variables properly override defaults."""
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("API_PORT", "9050")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("MYSQL_DATABASE", "smart_health_test_db")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings()
    assert settings.app_env == "testing"
    assert settings.api_port == 9050
    assert settings.app_debug is True
    assert settings.mysql_database == "smart_health_test_db"
    assert settings.log_level == "DEBUG"


def test_cors_origins_parsing():
    """Verify flexible parsing of CORS origins."""
    # 1. Native list
    s1 = Settings(cors_origins=["http://localhost:3000", "http://localhost:5173"])
    assert s1.cors_origins == ["http://localhost:3000", "http://localhost:5173"]

    # 2. JSON string
    s2 = Settings(cors_origins='["https://doctor.hospital.org", "https://patient.app"]')
    assert s2.cors_origins == ["https://doctor.hospital.org", "https://patient.app"]

    # 3. Comma-separated string
    s3 = Settings(cors_origins="http://example.com:8080, http://test.org")
    assert s3.cors_origins == ["http://example.com:8080", "http://test.org"]

    # 4. Empty string
    s4 = Settings(cors_origins="")
    assert s4.cors_origins == []


def test_invalid_api_port():
    """Verify port bounds validation."""
    with pytest.raises(ValidationError):
        Settings(api_port=0)

    with pytest.raises(ValidationError):
        Settings(api_port=70000)


def test_invalid_log_level():
    """Verify rejection of invalid logging level strings."""
    with pytest.raises(ValidationError):
        Settings(log_level="VERBOSE")


def test_mysql_url_special_characters():
    """Verify that special characters in credentials are properly URL-encoded."""
    raw_user = "health:admin@vit"
    raw_pass = "p@$$w0rd:with/slashes&symbols!#%^"
    settings = Settings(
        mysql_user=raw_user,
        mysql_password=raw_pass,
        mysql_host="db.internal.cluster",
        mysql_port=3307,
        mysql_database="health_db",
    )

    url = settings.get_mysql_url(driver="mysqlconnector")
    expected_user = quote_plus(raw_user)
    expected_pass = quote_plus(raw_pass)

    assert f"{expected_user}:{expected_pass}" in url
    assert f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}" in url
    assert url.startswith("mysql+mysqlconnector://")

    # Verify safe URL masks password
    safe_url = settings.get_safe_mysql_url()
    assert expected_pass not in safe_url
    assert raw_pass not in safe_url
    assert f"{expected_user}:***@" in safe_url


def test_production_invariants_jwt_secret():
    """Verify production requires a secure, non-default JWT secret of >= 32 chars."""
    # Weak/default secret in production must fail
    with pytest.raises(ValueError, match="JWT_SECRET must be at least 32 characters"):
        Settings(
            app_env="production",
            jwt_secret="insecure_dev_secret_key_must_be_changed_in_production_at_least_32_chars",
            mysql_password="valid_strong_password_123",
            ingestion_api_key="production_simulator_key_999",
        )

    # Short secret in production must fail
    with pytest.raises(ValueError, match="JWT_SECRET must be at least 32 characters"):
        Settings(
            app_env="production",
            jwt_secret="too_short_key",
            mysql_password="valid_strong_password_123",
            ingestion_api_key="production_simulator_key_999",
        )

    # Missing MySQL password in production must fail
    with pytest.raises(ValueError, match="MYSQL_PASSWORD cannot be empty"):
        Settings(
            app_env="production",
            jwt_secret="a_very_strong_production_signing_key_32_chars_long",
            mysql_password="",
            ingestion_api_key="production_simulator_key_999",
        )

    # Valid production settings pass
    prod_settings = Settings(
        app_env="production",
        jwt_secret="a_very_strong_production_signing_key_32_chars_long",
        mysql_password="super_secure_db_password_2026",
        ingestion_api_key="secure_internal_ingest_key_888",
    )
    assert prod_settings.app_env == "production"


def test_mongodb_ready_validation():
    """Verify on-demand MongoDB Atlas configuration validation."""
    settings = Settings(mongodb_uri="")
    with pytest.raises(ValueError, match="MongoDB Atlas configuration is missing"):
        settings.validate_mongodb_ready()

    invalid_scheme = Settings(mongodb_uri="http://atlas.com/db")
    with pytest.raises(ValueError, match="Invalid MONGODB_URI scheme"):
        invalid_scheme.validate_mongodb_ready()

    valid_mongo = Settings(
        mongodb_uri="mongodb://localhost:27017/?retryWrites=true"
    )
    # Should not raise
    valid_mongo.validate_mongodb_ready()


def test_get_resolved_dataset_path():
    """Verify that dataset path resolves to a Path object without failing if absent."""
    settings = Settings(kaggle_dataset_path="data/test_file.csv")
    resolved = settings.get_resolved_dataset_path()
    assert isinstance(resolved, Path)
    assert resolved.name == "test_file.csv"


def test_secret_masking_in_repr():
    """Verify that secrets are masked when printing or logging the settings instance."""
    settings = Settings(
        jwt_secret="super_secret_jwt_token_key_123456",
        mysql_password="secret_db_password_789",
    )
    rep = repr(settings)
    string_rep = str(settings)

    assert "super_secret_jwt_token_key_123456" not in rep
    assert "secret_db_password_789" not in rep
    assert "jwt_secret='***'" in rep
    assert "***" in rep
    assert rep == string_rep


def test_fastapi_health_endpoint():
    """Verify FastAPI integration and /health endpoint using custom settings."""
    test_settings = Settings(
        app_name="Test Health Gateway",
        app_env="testing",
    )
    app = create_app(settings=test_settings)
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "Test Health Gateway"
    assert data["environment"] == "testing"
    assert data["version"] == "3.0.0"
    assert data["is_simulated"] is True
    assert "NOT FOR MEDICAL USE" in data["notice"]
