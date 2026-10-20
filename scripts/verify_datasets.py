"""Validate the schemas and integrity of the distributed SWING datasets."""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DatasetSpec:
    path: str
    columns: tuple[str, ...]
    rows: int
    timestamp: str
    numeric: tuple[str, ...]


SPECS = (
    DatasetSpec(
        "data/raw_data/hourlyLoadDataIndia.csv",
        (
            "datetime",
            "National Hourly Demand",
            "Northen Region Hourly Demand",
            "Western Region Hourly Demand",
            "Eastern Region Hourly Demand",
            "Southern Region Hourly Demand",
            "North-Eastern Region Hourly Demand",
        ),
        46728,
        "datetime",
        (
            "National Hourly Demand",
            "Northen Region Hourly Demand",
            "Western Region Hourly Demand",
            "Eastern Region Hourly Demand",
            "Southern Region Hourly Demand",
            "North-Eastern Region Hourly Demand",
        ),
    ),
    DatasetSpec(
        "data/raw_data/Northern_Region_Hourly_Weather_2019_2024.csv",
        ("Datetime", "Delhi_T2M", "Lucknow_T2M", "Jaipur_T2M", "Northern_Region_Avg_T2M"),
        46728,
        "Datetime",
        ("Delhi_T2M", "Lucknow_T2M", "Jaipur_T2M", "Northern_Region_Avg_T2M"),
    ),
    DatasetSpec(
        "data/processed_data/tft_ready_data.csv",
        (
            "Datetime",
            "National Hourly Demand",
            "Northen Region Hourly Demand",
            "Western Region Hourly Demand",
            "Eastern Region Hourly Demand",
            "Southern Region Hourly Demand",
            "North-Eastern Region Hourly Demand",
            "Northern_Region_Avg_T2M",
            "normalized_target",
            "hour",
            "hour_sin",
            "hour_cos",
            "dayofweek",
            "month",
            "load_lag_1",
            "load_lag_2",
            "load_lag_24",
            "time_idx",
            "region",
        ),
        46704,
        "Datetime",
        (
            "National Hourly Demand",
            "Northen Region Hourly Demand",
            "Western Region Hourly Demand",
            "Eastern Region Hourly Demand",
            "Southern Region Hourly Demand",
            "North-Eastern Region Hourly Demand",
            "Northern_Region_Avg_T2M",
            "normalized_target",
            "hour",
            "hour_sin",
            "hour_cos",
            "dayofweek",
            "month",
            "load_lag_1",
            "load_lag_2",
            "load_lag_24",
            "time_idx",
        ),
    ),
)
def validate_dataset(path: Path, spec: DatasetSpec, *, strict: bool) -> list[str]:
    errors: list[str] = []
    try:
        handle = path.open(newline="", encoding="utf-8-sig")
    except OSError as exc:
        return [f"{spec.path}: cannot read file: {exc}"]

    with handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != spec.columns:
            return [f"{spec.path}: unexpected header {reader.fieldnames!r}; expected {list(spec.columns)!r}"]
        timestamps: list[datetime] = []
        time_indices: list[int] = []
        row_count = 0
        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            if None in row:
                errors.append(f"{spec.path}:{line_number}: row has more fields than the header")
                continue
            missing = [column for column, value in row.items() if value is None or not value.strip()]
            if missing:
                errors.append(f"{spec.path}:{line_number}: missing values in {missing}")
                continue
            try:
                timestamps.append(datetime.strptime(row[spec.timestamp], "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                errors.append(f"{spec.path}:{line_number}: invalid timestamp {row[spec.timestamp]!r}")
            for column in spec.numeric:
                try:
                    value = float(row[column])
                    if not math.isfinite(value):
                        raise ValueError("not finite")
                except ValueError:
                    errors.append(f"{spec.path}:{line_number}: {column} must be a finite number")
            if "time_idx" in row:
                try:
                    time_indices.append(int(row["time_idx"]))
                except ValueError:
                    errors.append(f"{spec.path}:{line_number}: time_idx must be an integer")
            if "region" in row and row["region"] != "Northern":
                errors.append(f"{spec.path}:{line_number}: unexpected region {row['region']!r}")

    if strict and row_count != spec.rows:
        errors.append(f"{spec.path}: expected {spec.rows} data rows, found {row_count}")
    if len(timestamps) == row_count and timestamps:
        if any(later <= earlier for earlier, later in zip(timestamps, timestamps[1:])):
            errors.append(f"{spec.path}: timestamps must be strictly increasing with no duplicates")
    if time_indices and time_indices != list(range(len(time_indices))):
        errors.append(f"{spec.path}: time_idx must increase from zero without gaps")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="also require the recorded source row counts")
    args = parser.parse_args()
    errors = [error for spec in SPECS for error in validate_dataset(ROOT / spec.path, spec, strict=args.strict)]
    if errors:
        print("\n".join(f"ERROR {error}" for error in errors))
        return 1
    mode = "strict" if args.strict else "schema"
    print(f"Dataset {mode} checks passed for {len(SPECS)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
