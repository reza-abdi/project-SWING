"""Regression tests for dataset schema checks and archived dataset bytes."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import replace
from pathlib import Path

from scripts.verify_datasets import SPECS, validate_dataset

ROOT = Path(__file__).resolve().parents[2]
SOURCE_HASHES = {
    "data/raw_data/hourlyLoadDataIndia.csv": "072db545cba1b682c45867b7c101a3e179ef6025b9e4c19b96b2b1f8df34f44c",
    "data/raw_data/Northern_Region_Hourly_Weather_2019_2024.csv": "8bf0cf172db39435eeec1021b61d0086e79ed16ac5c252a4ea4532cbb8be7227",
    "data/processed_data/tft_ready_data.csv": "e8baee3e109327ee7faa53b9b054f15c1eb270b1de88ca52670361f3464bb6bb",
}


def write_csv(path: Path, spec, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=spec.columns)
        writer.writeheader()
        writer.writerows(rows)


def raw_row(spec, timestamp: str) -> dict[str, str]:
    row = {column: "1.0" for column in spec.columns}
    row[spec.timestamp] = timestamp
    return row


def test_synthetic_dataset_passes_schema_and_strict_row_count(tmp_path: Path) -> None:
    original = SPECS[0]
    spec = replace(original, path="synthetic.csv", rows=2)
    path = tmp_path / spec.path
    write_csv(path, spec, [
        raw_row(spec, "2024-01-01 00:00:00"),
        raw_row(spec, "2024-01-01 01:00:00"),
    ])

    assert validate_dataset(path, spec, strict=True) == []


def test_synthetic_dataset_rejects_duplicate_timestamps_and_missing_values(tmp_path: Path) -> None:
    original = SPECS[0]
    spec = replace(original, path="synthetic.csv", rows=2)
    path = tmp_path / spec.path
    duplicate = raw_row(spec, "2024-01-01 00:00:00")
    missing = raw_row(spec, "2024-01-01 01:00:00")
    missing[spec.numeric[0]] = ""
    write_csv(path, spec, [duplicate, missing])

    errors = validate_dataset(path, spec, strict=True)
    assert any("missing values" in error for error in errors)

    missing[spec.numeric[0]] = "2.0"
    missing[spec.timestamp] = duplicate[spec.timestamp]
    write_csv(path, spec, [duplicate, missing])
    errors = validate_dataset(path, spec, strict=True)
    assert any("strictly increasing" in error for error in errors)


def test_distributed_datasets_match_recorded_source_hashes() -> None:
    for relative, expected in SOURCE_HASHES.items():
        path = ROOT / relative
        assert path.is_file(), f"distributed dataset is missing: {relative}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
