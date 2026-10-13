"""
Validation Engine for Kaggle Health Monitoring CSV Datasets.

Performs strict structural and record-level validation:
1. Structural integrity: file existence, headers, duplicate or missing columns, non-empty content.
2. Record integrity: patient ID presence, numeric format & domain bounds for vitals, timestamp parsing.
3. Unit & precision preservation: Fahrenheit preserved raw, canonical Celsius derived explicitly.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional, Set
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EXPECTED_COLUMNS = ["patient_id", "heart_rate", "spo2", "temperature_f", "timestamp"]


@dataclass
class ValidationErrorDetail:
    """Detailed description of a single validation failure."""
    row_number: int  # 1-based CSV line number (including header)
    field: str
    value: str
    message: str


@dataclass
class ParsedKaggleRow:
    """Strongly-typed, validated record ready for relational persistence."""
    row_ordinal: int  # 1-based record index (excluding header)
    patient_id: str
    heart_rate: Decimal
    spo2: Decimal
    temperature_f: Decimal
    temperature_c: Decimal
    raw_timestamp: str
    measured_at: datetime


@dataclass
class DatasetValidationResult:
    """Complete summary of dataset inspection and validation."""
    file_path: Path
    file_sha256: str
    total_rows_inspected: int = 0
    valid_records: List[ParsedKaggleRow] = field(default_factory=list)
    errors: List[ValidationErrorDetail] = field(default_factory=list)
    distinct_patient_ids: Set[str] = field(default_factory=set)

    @property
    def is_valid(self) -> bool:
        """Returns True if the file has rows and zero validation errors."""
        return len(self.errors) == 0 and self.total_rows_inspected > 0

    @property
    def valid_count(self) -> int:
        return len(self.valid_records)

    @property
    def error_count(self) -> int:
        return len(self.errors)


def compute_file_sha256(path: Path) -> str:
    """Compute the SHA-256 checksum of an input file without loading entirely into memory."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_timestamp_with_timezone(
    raw_str: str,
    tz_name: str = "UTC",
    row_num: int = 0,
) -> tuple[Optional[datetime], Optional[str]]:
    """
    Parse timestamp string into an aware datetime preserving timezone semantics.
    Supports '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', and '%Y-%m-%dT%H:%M:%S'.
    """
    cleaned = raw_str.strip()
    if not cleaned:
        return None, "Timestamp value is empty"

    parsed_dt: Optional[datetime] = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed_dt = datetime.strptime(cleaned, fmt)
            break
        except ValueError:
            continue

    if parsed_dt is None:
        return None, f"Unrecognized timestamp format '{cleaned}'. Expected YYYY-MM-DD HH:MM:SS"

    # Resolve target timezone
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    # Attach explicit timezone
    return parsed_dt.replace(tzinfo=tz), None


def fahrenheit_to_celsius(deg_f: Decimal) -> Decimal:
    """
    Convert Fahrenheit to Celsius with exact decimal precision:
    C = (F - 32) * 5 / 9, rounded to 2 decimal places.
    """
    c = (deg_f - Decimal("32")) * Decimal("5") / Decimal("9")
    return round(c, 2)


def validate_kaggle_csv(
    file_path: str | Path,
    source_timezone: str = "UTC",
) -> DatasetValidationResult:
    """
    Validate a Kaggle CSV file structurally and at the record level.
    Never alters or mutates the source file.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source dataset not found at path: {path}")
    if not path.is_file():
        raise ValueError(f"Specified path is not a regular file: {path}")

    file_sha256 = compute_file_sha256(path)
    result = DatasetValidationResult(file_path=path, file_sha256=file_sha256)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            result.errors.append(
                ValidationErrorDetail(
                    row_number=1,
                    field="header",
                    value="",
                    message="Source file is completely empty",
                )
            )
            return result

        # Normalize header keys
        cleaned_header = [col.strip().lower() for col in header]

        # Check for required columns
        missing_cols = [col for col in EXPECTED_COLUMNS if col not in cleaned_header]
        if missing_cols:
            result.errors.append(
                ValidationErrorDetail(
                    row_number=1,
                    field="header",
                    value=",".join(header),
                    message=f"Missing required columns: {missing_cols}",
                )
            )
            return result

        # Check for duplicate column names in header
        if len(cleaned_header) != len(set(cleaned_header)):
            result.errors.append(
                ValidationErrorDetail(
                    row_number=1,
                    field="header",
                    value=",".join(header),
                    message="Header contains duplicate column names",
                )
            )
            return result

        col_indices = {col: cleaned_header.index(col) for col in EXPECTED_COLUMNS}

        row_idx = 0
        for line_num, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                # Skip blank trailing lines
                continue

            row_idx += 1
            result.total_rows_inspected += 1

            if len(row) < len(EXPECTED_COLUMNS):
                result.errors.append(
                    ValidationErrorDetail(
                        row_number=line_num,
                        field="row",
                        value=",".join(row),
                        message=f"Row has insufficient columns ({len(row)} < {len(EXPECTED_COLUMNS)})",
                    )
                )
                continue

            # 1. Patient ID validation
            raw_patient = row[col_indices["patient_id"]].strip()
            if not raw_patient:
                result.errors.append(
                    ValidationErrorDetail(
                        row_number=line_num,
                        field="patient_id",
                        value=raw_patient,
                        message="Patient ID is missing or empty",
                    )
                )
                continue

            # 2. Heart rate validation (e.g. 20 - 300 bpm bounds)
            raw_hr = row[col_indices["heart_rate"]].strip()
            try:
                hr_val = Decimal(raw_hr)
                if hr_val <= 0 or hr_val > 300:
                    result.errors.append(
                        ValidationErrorDetail(
                            row_number=line_num,
                            field="heart_rate",
                            value=raw_hr,
                            message=f"Heart rate value {hr_val} out of physiological bounds (0 - 300 bpm)",
                        )
                    )
                    continue
            except (InvalidOperation, ValueError):
                result.errors.append(
                    ValidationErrorDetail(
                        row_number=line_num,
                        field="heart_rate",
                        value=raw_hr,
                        message=f"Invalid numeric format for heart_rate: '{raw_hr}'",
                    )
                )
                continue

            # 3. SpO2 validation (0 - 100 %)
            raw_spo2 = row[col_indices["spo2"]].strip()
            try:
                spo2_val = Decimal(raw_spo2)
                if spo2_val < 0 or spo2_val > 100:
                    result.errors.append(
                        ValidationErrorDetail(
                            row_number=line_num,
                            field="spo2",
                            value=raw_spo2,
                            message=f"SpO2 percentage {spo2_val} out of bounds (0 - 100 %)",
                        )
                    )
                    continue
            except (InvalidOperation, ValueError):
                result.errors.append(
                    ValidationErrorDetail(
                        row_number=line_num,
                        field="spo2",
                        value=raw_spo2,
                        message=f"Invalid numeric format for spo2: '{raw_spo2}'",
                    )
                )
                continue

            # 4. Temperature Fahrenheit validation (70 - 120 °F)
            raw_temp = row[col_indices["temperature_f"]].strip()
            try:
                temp_f_val = Decimal(raw_temp)
                if temp_f_val < 70 or temp_f_val > 120:
                    result.errors.append(
                        ValidationErrorDetail(
                            row_number=line_num,
                            field="temperature_f",
                            value=raw_temp,
                            message=f"Temperature {temp_f_val} out of bounds (70 - 120 °F)",
                        )
                    )
                    continue
            except (InvalidOperation, ValueError):
                result.errors.append(
                    ValidationErrorDetail(
                        row_number=line_num,
                        field="temperature_f",
                        value=raw_temp,
                        message=f"Invalid numeric format for temperature_f: '{raw_temp}'",
                    )
                )
                continue

            # 5. Timestamp validation
            raw_ts = row[col_indices["timestamp"]].strip()
            dt, err = parse_timestamp_with_timezone(
                raw_ts,
                tz_name=source_timezone,
                row_num=line_num,
            )
            if err or dt is None:
                result.errors.append(
                    ValidationErrorDetail(
                        row_number=line_num,
                        field="timestamp",
                        value=raw_ts,
                        message=err or "Invalid timestamp",
                    )
                )
                continue

            # Compute canonical Celsius
            temp_c_val = fahrenheit_to_celsius(temp_f_val)

            # Record success
            result.distinct_patient_ids.add(raw_patient)
            result.valid_records.append(
                ParsedKaggleRow(
                    row_ordinal=row_idx,
                    patient_id=raw_patient,
                    heart_rate=round(hr_val, 2),
                    spo2=round(spo2_val, 2),
                    temperature_f=round(temp_f_val, 2),
                    temperature_c=temp_c_val,
                    raw_timestamp=raw_ts,
                    measured_at=dt,
                )
            )

    return result
