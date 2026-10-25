"""Timestamp alignment and leak-free forecasting feature tests."""

import numpy as np
import pandas as pd

from modules.forecasting.grid_forecaster import GridForecaster


def test_timestamp_harmonization_and_feature_order(tmp_path) -> None:
    timestamps = pd.date_range("2024-01-01", periods=30, freq="h")
    load = pd.DataFrame({"datetime": timestamps, "Northen Region Hourly Demand": np.arange(100.0, 130.0)})
    weather = pd.DataFrame({"Datetime": timestamps, "Northern_Region_Avg_T2M": np.linspace(1.0, 5.0, 30)})
    load.to_csv(tmp_path / "hourlyLoadDataIndia.csv", index=False)
    weather.to_csv(tmp_path / "Northern_Region_Hourly_Weather_2019_2024.csv", index=False)

    forecaster = GridForecaster(tmp_path)
    joined = forecaster.load_and_harmonize()
    assert joined.index.name == "Datetime"
    assert joined.index[0] == timestamps[0]
    assert "Northen Region Hourly Demand" in joined.columns
    assert "Northern_Region_Avg_T2M" in joined.columns

    featured = forecaster.engineer_features(joined, "Northen Region Hourly Demand")
    assert len(featured) == 6
    assert featured.index[0] == timestamps[24]
    assert tuple(forecaster.FEATURE_COLUMNS) == (
        "hour_sin", "hour_cos", "dayofweek", "month", "load_lag_1", "load_lag_2", "load_lag_24", "Northern_Region_Avg_T2M"
    )
    assert featured.iloc[0]["load_lag_24"] == featured.iloc[0]["normalized_target"]
    assert featured.iloc[0]["normalized_target"] == 1.0
