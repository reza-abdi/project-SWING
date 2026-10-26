"""Fetch and atomically store hourly weather for Northern Region demand."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import pandas as pd
import requests

from modules.config import runtime_paths


ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
LOCATIONS = (
    ("Delhi", 28.6139, 77.2090),
    ("Lucknow", 26.8467, 80.9462),
    ("Jaipur", 26.9124, 75.7873),
)


def fetch_northern_region_weather(
    output_path: str | Path | None = None,
    *,
    start_date: str = "2019-01-01",
    end_date: str = "2024-04-30",
    timeout_seconds: float = 30.0,
) -> pd.DataFrame:
    """Fetch three city temperature series and save their hourly regional mean."""
    params = {
        "latitude": ",".join(str(latitude) for _, latitude, _ in LOCATIONS),
        "longitude": ",".join(str(longitude) for _, _, longitude in LOCATIONS),
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m",
        "timezone": "Asia/Kolkata",
    }
    response = requests.get(ARCHIVE_URL, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) != len(LOCATIONS):
        raise ValueError("weather response must contain one hourly record per requested location")

    city_frames = []
    expected_times = None
    for (city, _, _), record in zip(LOCATIONS, payload):
        if not isinstance(record, dict) or not isinstance(record.get("hourly"), dict):
            raise ValueError(f"weather response is missing hourly data for {city}")
        hourly = record["hourly"]
        times = hourly.get("time")
        temperatures = hourly.get("temperature_2m")
        if not isinstance(times, list) or not times or not isinstance(temperatures, list) or len(times) != len(temperatures):
            raise ValueError(f"weather response has invalid timestamps or temperatures for {city}")
        if any(value is None for value in temperatures):
            raise ValueError(f"weather response has missing hourly temperatures for {city}")
        if expected_times is None:
            expected_times = times
        elif times != expected_times:
            raise ValueError("weather locations returned different hourly timestamps")
        city_frames.append(pd.Series(temperatures, index=pd.to_datetime(times), name=f"{city}_T2M"))

    combined = pd.concat(city_frames, axis=1)
    if combined.index.has_duplicates or not combined.index.is_monotonic_increasing:
        raise ValueError("weather response timestamps must be unique and sorted")
    combined["Northern_Region_Avg_T2M"] = combined.mean(axis=1)
    combined.index.name = "Datetime"
    result = combined.reset_index()

    destination = Path(output_path) if output_path is not None else runtime_paths().data / "raw_data" / "Northern_Region_Hourly_Weather_2019_2024.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=destination.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            result.to_csv(handle, index=False)
        os.replace(temp_path, destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return result


if __name__ == "__main__":
    fetch_northern_region_weather()
