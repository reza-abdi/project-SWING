"""Forecast model tests using native-text metadata and predictor stubs."""

import sys
import types

import numpy as np
import pandas as pd
import pytest

from modules.forecasting.grid_forecaster import GridForecaster


class _Model:
    def __init__(self, value: float):
        self.value = value
        self.seen_columns = None

    def predict(self, frame):
        self.seen_columns = list(frame.columns)
        return np.array([self.value])


def test_load_models_checks_ordered_native_feature_metadata(monkeypatch, tmp_path) -> None:
    class Booster:
        def __init__(self, model_file):
            self.path = model_file

        def feature_name(self):
            return list(GridForecaster.FEATURE_COLUMNS)

    monkeypatch.setitem(sys.modules, "lightgbm", types.SimpleNamespace(Booster=Booster))
    forecaster = GridForecaster()
    for q in (10, 50, 90):
        (tmp_path / f"lightgbm_q_{q}.txt").write_text("test fixture")
    forecaster.load_models(tmp_path)
    assert set(forecaster.models) == {0.1, 0.5, 0.9}


def test_forecast_orders_features_clamps_baseline_and_quantile_crossing() -> None:
    forecaster = GridForecaster()
    models = {0.1: _Model(0.4), 0.5: _Model(0.2), 0.9: _Model(0.8)}
    forecaster.models = models
    features = {name: float(index) for index, name in enumerate(forecaster.FEATURE_COLUMNS)}
    bounds = forecaster.forecast_next_hour(features, 1000.0)
    assert bounds == {"p10": 400.0, "p50": 400.0, "p90": 800.0}
    assert all(model.seen_columns == list(forecaster.FEATURE_COLUMNS) for model in models.values())
    with pytest.raises(ValueError, match="finite and positive"):
        forecaster.forecast_next_hour(features, float("inf"))


def test_shap_explanation_has_eight_ranked_features(monkeypatch) -> None:
    forecaster = GridForecaster()
    forecaster.models = {0.5: object()}

    class TreeExplainer:
        expected_value = np.array([0.3])

        def __init__(self, model):
            pass

        def shap_values(self, frame):
            return np.arange(8, dtype=float).reshape(1, 8)

    monkeypatch.setitem(sys.modules, "shap", types.SimpleNamespace(TreeExplainer=TreeExplainer))
    result = forecaster.explain_prediction({name: 0.0 for name in forecaster.FEATURE_COLUMNS})
    assert result["base_value"] == 0.3
    assert len(result["contributions"]) == 8
    assert len(result["ranked_features"]) == 8
    assert result["ranked_features"][0][0] == forecaster.FEATURE_COLUMNS[-1]
