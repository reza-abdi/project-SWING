"""Load and harmonize regional demand and weather measurements."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np

from modules.config import runtime_paths


class GridForecaster:
    """Forecast regional demand using aligned weather and load history."""

    WEATHER_FEATURE = "Northern_Region_Avg_T2M"
    FEATURE_COLUMNS = (
        "hour_sin",
        "hour_cos",
        "dayofweek",
        "month",
        "load_lag_1",
        "load_lag_2",
        "load_lag_24",
        WEATHER_FEATURE,
    )

    def __init__(self, raw_data_dir: str | Path | None = None) -> None:
        self.project_root = runtime_paths().root
        self.raw_data_dir = Path(raw_data_dir) if raw_data_dir is not None else runtime_paths().data / "raw_data"

    def load_and_harmonize(
        self,
        load_file: str = "hourlyLoadDataIndia.csv",
        weather_file: str = "Northern_Region_Hourly_Weather_2019_2024.csv",
    ) -> pd.DataFrame:
        """Inner-join unique hourly records using the source timestamp columns."""
        load_path = (self.raw_data_dir / load_file).resolve()
        weather_path = (self.raw_data_dir / weather_file).resolve()
        root = self.raw_data_dir.resolve()
        if root not in load_path.parents or root not in weather_path.parents:
            raise ValueError("input files must remain under the configured raw data directory")
        load = pd.read_csv(load_path, parse_dates=["datetime"], index_col="datetime")
        weather = pd.read_csv(weather_path, parse_dates=["Datetime"], index_col="Datetime")
        if load.index.has_duplicates or weather.index.has_duplicates:
            raise ValueError("load and weather timestamps must be unique")
        if self.WEATHER_FEATURE not in weather.columns:
            raise ValueError(f"weather data must include {self.WEATHER_FEATURE}")
        load.index.name = "Datetime"
        load = load.sort_index()
        weather = weather[[self.WEATHER_FEATURE]].sort_index()
        joined = load.join(weather, how="inner", validate="one_to_one")
        return joined

    def engineer_features(self, frame: pd.DataFrame, load_column: str) -> pd.DataFrame:
        """Add source-compatible rolling normalization and hourly lag features."""
        if load_column not in frame.columns:
            raise ValueError(f"load column not found: {load_column}")
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError("feature engineering requires a DatetimeIndex")
        result = frame.copy().sort_index()
        demand = pd.to_numeric(result[load_column], errors="coerce")
        rolling_max = demand.rolling(window=24 * 30, min_periods=1).max()
        result["normalized_target"] = demand.div(rolling_max.where(rolling_max != 0))
        result["hour"] = result.index.hour
        result["hour_sin"] = np.sin(2 * np.pi * result["hour"] / 24.0)
        result["hour_cos"] = np.cos(2 * np.pi * result["hour"] / 24.0)
        result["dayofweek"] = result.index.dayofweek
        result["month"] = result.index.month
        result["load_lag_1"] = result["normalized_target"].shift(1)
        result["load_lag_2"] = result["normalized_target"].shift(2)
        result["load_lag_24"] = result["normalized_target"].shift(24)
        return result.dropna(subset=["normalized_target", "load_lag_1", "load_lag_2", "load_lag_24"])
