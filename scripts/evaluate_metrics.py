"""Offline evaluation reports for forecasting, RL training, retrieval, and proposals."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sqlite3
import statistics

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def regression_metrics(actual, predicted) -> dict[str, float]:
    """Return normalized RMSE, MAE and MAPE, ignoring zero targets for MAPE."""
    pairs = [(float(a), float(p)) for a, p in zip(actual, predicted)
             if math.isfinite(float(a)) and math.isfinite(float(p))]
    if not pairs:
        raise ValueError("evaluation requires at least one finite target/prediction pair")
    observed, estimates = zip(*pairs)
    scale = max(observed) - min(observed)
    if scale == 0:
        scale = max(abs(value) for value in observed) or 1.0
    errors = [estimate - value for value, estimate in pairs]
    mape_values = [abs(error / value) for (value, _), error in zip(pairs, errors) if value != 0]
    return {
        "n": len(pairs),
        "nrmse": math.sqrt(statistics.mean(error * error for error in errors)) / scale,
        "nmae": statistics.mean(abs(error) for error in errors) / scale,
        "mape": statistics.mean(mape_values) if mape_values else float("nan"),
    }


def evaluate_forecasts(data_path: Path | None = None, models_dir: Path | None = None) -> dict:
    """Evaluate supplied LightGBM quantile models on a chronological 20% holdout."""
    import lightgbm as lgb
    import pandas as pd

    from modules.forecasting.grid_forecaster import GridForecaster

    source = data_path or PROJECT_ROOT / "data/processed_data/tft_ready_data.csv"
    model_root = models_dir or PROJECT_ROOT / "models"
    frame = pd.read_csv(source, parse_dates=["Datetime"]).sort_values("Datetime")
    forecaster = GridForecaster()
    features = list(forecaster.FEATURE_COLUMNS)
    required = {"Datetime", "Northen Region Hourly Demand", *features}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"evaluation data is missing columns: {sorted(missing)}")
    split = int(len(frame) * 0.8)
    test = frame.iloc[split:]
    if split < 2 or test.empty:
        raise ValueError("chronological evaluation needs at least three rows")
    results = {}
    for quantile in (10, 50, 90):
        model = lgb.Booster(model_file=str(model_root / f"lightgbm_q_{quantile}.txt"))
        if model.feature_name() != features:
            raise ValueError(f"lightgbm_q_{quantile}.txt feature schema does not match source")
        prediction = model.predict(test.loc[:, features])
        results[f"p{quantile}"] = regression_metrics(test["normalized_target"], prediction)
    return {"dataset": str(source), "target_column": "Northen Region Hourly Demand",
            "split": "chronological 80/20", "test_rows": len(test), "quantiles": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--models", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(evaluate_forecasts(args.data, args.models), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
