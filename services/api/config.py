"""
Centralized Configuration Module for Smart Health Monitoring System.

This module provides validated, environment-based configuration using Pydantic Settings.
It ensures that:
1. Environment variables and local .env files are loaded predictably.
2. Credentials and secrets are never printed in logs or string representations.
3. Database connection URLs handle special characters safely using URL-encoding.
4. MongoDB Atlas settings are validated only when NoSQL functionality is initialized.
5. Production environments strictly forbid missing or default secrets.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Literal
from urllib.parse import quote_plus, urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application-wide settings validated at runtime."""

    # -------------------------------------------------------------------------
    # 1. Application & Server Settings
    # -------------------------------------------------------------------------
    app_name: str = Field(
        default="Smart Health Monitoring System",
        description="Public title of the service",
    )
    app_env: Literal["development", "testing", "production"] = Field(
        default="development",
        description="Deployment environment name",
    )
    app_debug: bool = Field(
        default=False,
        description="Enable debug mode and verbose tracebacks",
    )
    api_host: str = Field(
        default="127.0.0.1",
        description="Binding host address for ASGI server",
    )
    api_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port for the API gateway",
    )
    api_v1_prefix: str = Field(
        default="/api/v1",
        description="Route prefix for Version 1 REST API",
    )
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Allowed origins for Cross-Origin Resource Sharing",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # -------------------------------------------------------------------------
    # 2. MySQL Relational Database (Authoritative System of Record)
    # -------------------------------------------------------------------------
    mysql_host: str = Field(
        default="localhost",
        description="MySQL server hostname or IP",
    )
    mysql_port: int = Field(
        default=3306,
        ge=1,
        le=65535,
        description="MySQL port",
    )
    mysql_database: str = Field(
        default="smart_health",
        description="Primary relational database name",
    )
    mysql_user: str = Field(
        default="smart_health_app",
        description="Application database user with least privileges",
    )
    mysql_password: str = Field(
        default="",
        description="Database password",
    )
    mysql_connect_timeout: int = Field(
        default=10,
        ge=1,
        description="Database connection timeout in seconds",
    )
    mysql_driver: str = Field(
        default="mysqlconnector",
        description="SQLAlchemy driver name (e.g. mysqlconnector or pymysql)",
    )

    # -------------------------------------------------------------------------
    # 3. MongoDB Atlas (DA3 Telemetry Mirror & Aggregations)
    # -------------------------------------------------------------------------
    mongodb_uri: str = Field(
        default="",
        description="MongoDB Atlas connection URI. Optional for offline/unit tests.",
    )
    mongodb_database: str = Field(
        default="smart_health_analytics",
        description="Analytics document database name",
    )
    mongodb_server_selection_timeout_ms: int = Field(
        default=5000,
        ge=100,
        description="MongoDB server selection timeout in milliseconds",
    )
    mongodb_connect_timeout_ms: int = Field(
        default=5000,
        ge=100,
        description="MongoDB connection timeout in milliseconds",
    )

    # -------------------------------------------------------------------------
    # 4. Authentication & Security (JWT & Internal Service Keys)
    # -------------------------------------------------------------------------
    jwt_secret: str = Field(
        default="insecure_dev_secret_key_must_be_changed_in_production_at_least_32_chars",
        description="Secret key for signing JWT tokens",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT cryptographic algorithm",
    )
    access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        description="JWT token validity lifetime",
    )
    ingestion_api_key: str = Field(
        default="dev_simulator_key",
        description="Internal header key required for simulator ingestion",
    )

    # -------------------------------------------------------------------------
    # 5. Kaggle Historical Dataset & Ingestion Settings
    # -------------------------------------------------------------------------
    kaggle_dataset_path: str = Field(
        default=r"E:\kaggle_health_dataset.csv",
        description="Path to the verified 1,500-row Kaggle historical dataset CSV",
    )
    dataset_source_timezone: str = Field(
        default="UTC",
        description="Explicit source timezone assumption for historical data",
    )

    # -------------------------------------------------------------------------
    # 6. Machine Learning Settings
    # -------------------------------------------------------------------------
    model_artifact_dir: str = Field(
        default="packages/health_analysis/artifacts",
        description="Directory containing trained model artifacts",
    )
    model_version: str = Field(
        default="iforest-v1",
        description="Model version identifier for audit tracking",
    )

    # -------------------------------------------------------------------------
    # Pydantic Settings Configuration
    # -------------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        protected_namespaces=(),
    )

    # -------------------------------------------------------------------------
    # Field Validators
    # -------------------------------------------------------------------------
    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        """Support JSON string list or comma-separated string for CORS origins."""
        if isinstance(v, list):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return []
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                try:
                    parsed = json.loads(v_stripped)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if str(origin).strip()]
                except json.JSONDecodeError:
                    pass
            # Fallback: comma-separated values
            return [origin.strip() for origin in v_stripped.split(",") if origin.strip()]
        return []

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate logging level against standard Python log levels."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.strip().upper()
        if upper_v not in valid_levels:
            raise ValueError(f"Invalid log_level '{v}'. Must be one of {valid_levels}")
        return upper_v

    # -------------------------------------------------------------------------
    # Model Validators (Cross-field & Environment Invariants)
    # -------------------------------------------------------------------------
    @model_validator(mode="after")
    def validate_production_invariants(self) -> Settings:
        """Enforce strict security constraints when running in production."""
        if self.app_env == "production":
            # 1. JWT secret must be strong and not the default dev string
            if (
                not self.jwt_secret
                or "insecure_dev" in self.jwt_secret
                or len(self.jwt_secret) < 32
            ):
                raise ValueError(
                    "In production (APP_ENV=production), JWT_SECRET must be at least 32 "
                    "characters and cannot use the development default."
                )

            # 2. Ingestion service key cannot be default dev key
            if not self.ingestion_api_key or self.ingestion_api_key == "dev_simulator_key":
                raise ValueError(
                    "In production, INGESTION_API_KEY must be a distinct, secure secret."
                )

            # 3. MySQL password cannot be empty in production
            if not self.mysql_password or self.mysql_password.startswith("replace_"):
                raise ValueError(
                    "In production, MYSQL_PASSWORD cannot be empty or a template placeholder."
                )

        return self

    # -------------------------------------------------------------------------
    # Safe Helper Methods
    # -------------------------------------------------------------------------
    def get_mysql_url(self, driver: str | None = None) -> str:
        """
        Construct a database URL safely escaping special characters in credentials.
        
        Uses quote_plus so passwords containing '@', ':', '#', '%', '!', etc.
        never break connection string parsing.
        """
        drv = driver or self.mysql_driver
        safe_user = quote_plus(self.mysql_user)
        safe_password = quote_plus(self.mysql_password)
        return (
            f"mysql+{drv}://{safe_user}:{safe_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    def get_safe_mysql_url(self, driver: str | None = None) -> str:
        """Return database URL with password masked for safe logging and debugging."""
        drv = driver or self.mysql_driver
        safe_user = quote_plus(self.mysql_user)
        return (
            f"mysql+{drv}://{safe_user}:***"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    def validate_mongodb_ready(self) -> None:
        """
        Verify that MongoDB Atlas configuration is provided.
        Called on-demand when NoSQL features are initialized, rather than at import time.
        """
        if not self.mongodb_uri:
            raise ValueError(
                "MongoDB Atlas configuration is missing. MONGODB_URI must be provided "
                "to use the DA3 telemetry mirror or aggregation pipelines."
            )
        parsed = urlparse(self.mongodb_uri)
        if parsed.scheme not in ("mongodb", "mongodb+srv"):
            raise ValueError(
                f"Invalid MONGODB_URI scheme '{parsed.scheme}'. Must be 'mongodb' or 'mongodb+srv'."
            )

    @property
    def is_mongo_configured(self) -> bool:
        """Return True if MongoDB Atlas connection URI is configured."""
        return bool(self.mongodb_uri)

    def get_resolved_dataset_path(self) -> Path:
        """
        Resolve the configured dataset path.
        Does not raise if the file is missing; allows caller to check path.exists().
        """
        configured = Path(self.kaggle_dataset_path).resolve()
        if configured.exists():
            return configured
        # If default dataset path is configured but absent on non-Windows runner, check repo bundled copy
        if "kaggle_health_dataset.csv" in configured.name or "DOC-20261013-WA0056" in configured.name:
            repo_data = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "kaggle_health_dataset.csv"
            if repo_data.exists():
                return repo_data
        return configured

    def resolve_model_artifact_dir(self) -> Path:
        """
        Locate the Isolation Forest model artifact directory.
        Checks configured directory, environment variable, sibling ML repo, and local path.
        """
        import os

        env_dir = os.environ.get("MODEL_ARTIFACT_DIR") or os.environ.get("ML_MODEL_DIR")
        if env_dir:
            p = Path(env_dir).resolve()
            if p.exists():
                return p

        configured = Path(self.model_artifact_dir).resolve()
        if configured.exists() and (configured / "model.joblib").exists():
            return configured

        candidates = [
            Path(__file__).resolve().parent.parent.parent.parent / "HarnoorKant-Smart-Health-Monitoring-System" / "models" / "iforest_v1",
            Path(__file__).resolve().parent.parent.parent / "models" / "iforest_v1",
            Path("models/iforest_v1").resolve(),
            Path("packages/health_analysis/artifacts").resolve(),
        ]
        for candidate in candidates:
            if candidate.exists() and (candidate / "model.joblib").exists():
                return candidate.resolve()

        return configured


    def __repr__(self) -> str:
        """Sanitized string representation masking all secrets."""
        safe_db_url = self.get_safe_mysql_url()
        has_mongo = bool(self.mongodb_uri)
        return (
            f"<Settings app_name='{self.app_name}' env='{self.app_env}' "
            f"api='{self.api_host}:{self.api_port}' db='{safe_db_url}' "
            f"mongo_configured={has_mongo} jwt_secret='***'>"
        )

    def __str__(self) -> str:
        return self.__repr__()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached accessor for application settings.
    Ensures settings are only instantiated and validated once.
    Use get_settings.cache_clear() in tests when altering environment variables.
    """
    return Settings()
