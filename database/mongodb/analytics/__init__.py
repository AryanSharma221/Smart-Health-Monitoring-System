"""
MongoDB Analytics Package: Pipelines, Validators, and Normalizers.
"""

from database.mongodb.analytics.normalizers import (
    normalize_alert_summary,
    normalize_data_quality,
    normalize_dataset_overview,
    normalize_patient_vitals_summary,
    normalize_source_provenance,
    normalize_time_buckets,
)
from database.mongodb.analytics.pipelines import (
    build_alert_summary_pipeline,
    build_data_quality_pipeline,
    build_dataset_overview_pipeline,
    build_duplicate_source_identities_pipeline,
    build_patient_history_pipeline,
    build_patient_vitals_summary_pipeline,
    build_source_provenance_pipeline,
    build_time_bucketed_vitals_pipeline,
)
from database.mongodb.analytics.validators import (
    normalize_datetime,
    validate_bucket_interval,
    validate_pagination,
    validate_patient_id,
    validate_time_range,
)

__all__ = [
    # Validators
    "validate_patient_id",
    "normalize_datetime",
    "validate_time_range",
    "validate_bucket_interval",
    "validate_pagination",
    # Pipelines
    "build_dataset_overview_pipeline",
    "build_patient_vitals_summary_pipeline",
    "build_time_bucketed_vitals_pipeline",
    "build_patient_history_pipeline",
    "build_source_provenance_pipeline",
    "build_alert_summary_pipeline",
    "build_data_quality_pipeline",
    "build_duplicate_source_identities_pipeline",
    # Normalizers
    "normalize_dataset_overview",
    "normalize_patient_vitals_summary",
    "normalize_time_buckets",
    "normalize_source_provenance",
    "normalize_alert_summary",
    "normalize_data_quality",
]
