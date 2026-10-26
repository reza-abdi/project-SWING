"""TFT trust gates, horizon validation and single-hour fallback tests."""

import sys
import types

import numpy as np
import pandas as pd
import pytest

from modules.forecasting.tft_forecaster import TFTForecaster


class LightGBMFallback:
    def __init__(self):
        self.called = False

    def forecast_next_hour(self, features, baseline):
        self.called = True
        assert baseline == 1000.0
        return {"p10": 10.0, "p50": 20.0, "p90": 30.0}


def test_missing_and_untrusted_checkpoints_are_gated_and_fallback(tmp_path) -> None:
    fallback = LightGBMFallback()
    model = TFTForecaster(tmp_path / "missing.ckpt")
    result = model.forecast_or_fallback(pd.DataFrame(), {}, 1000.0, fallback)
    assert result["source"] == "LightGBM"
    assert result["fallback_reason"] == "FileNotFoundError"
    assert result["predictions"] == {"p10": [10.0], "p50": [20.0], "p90": [30.0]}
    assert fallback.called

    with pytest.raises(PermissionError):
        TFTForecaster().load_model()


def test_bad_checkpoint_hash_uses_single_horizon_fallback(tmp_path) -> None:
    checkpoint = tmp_path / "bad.ckpt"
    checkpoint.write_bytes(b"not the reviewed checkpoint")
    fallback = LightGBMFallback()
    result = TFTForecaster(checkpoint).forecast_or_fallback(
        pd.DataFrame(), {}, 1000.0, fallback, trust_checkpoint=True
    )
    assert result["source"] == "LightGBM"
    assert result["fallback_reason"] == "ValueError"


@pytest.mark.parametrize("failure", ["category", "shape"])
def test_category_or_prediction_shape_failure_uses_lightgbm_fallback(monkeypatch, failure) -> None:
    class NoGrad:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Loader:
        def to_dataloader(self, **_kwargs):
            return object()

    class TimeSeriesDataSet:
        @classmethod
        def from_dataset(cls, *_args, **_kwargs):
            if failure == "category":
                raise ValueError("incompatible categories")
            return Loader()

    class Model:
        def predict(self, *_args, **_kwargs):
            return np.zeros((1, 23, 3))

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(no_grad=NoGrad))
    monkeypatch.setitem(sys.modules, "pytorch_forecasting", types.SimpleNamespace(TimeSeriesDataSet=TimeSeriesDataSet))
    forecaster = TFTForecaster()
    forecaster.model = Model()
    fallback = LightGBMFallback()
    result = forecaster.forecast_or_fallback(
        pd.DataFrame({"region": ["Northern"]}), {}, 1000.0, fallback, training_dataset=object()
    )
    assert result["source"] == "LightGBM"
    assert result["fallback_reason"] in {"ValueError"}
    assert fallback.called


def test_history_window_has_192_categorical_historical_rows() -> None:
    frame = TFTForecaster().build_recent_history_window()
    assert len(frame) == 192
    assert frame.attrs["source_type"] == "historical_proxy"
    assert frame["region"].dtype == object
    assert frame["hour"].dtype == object
    assert frame["Datetime"].diff().dropna().eq(pd.Timedelta(hours=1)).all()


def test_valid_tft_output_keeps_all_24_hour_quantiles(monkeypatch) -> None:
    class NoGrad:
        def __enter__(self): return self
        def __exit__(self, *_args): return None

    class Loader:
        def to_dataloader(self, **_kwargs): return object()

    class TimeSeriesDataSet:
        @classmethod
        def from_dataset(cls, *_args, **_kwargs): return Loader()

    class Model:
        def predict(self, *_args, **_kwargs): return np.ones((1, 24, 3))

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(no_grad=NoGrad))
    monkeypatch.setitem(sys.modules, "pytorch_forecasting", types.SimpleNamespace(TimeSeriesDataSet=TimeSeriesDataSet))
    forecaster = TFTForecaster(); forecaster.model = Model()
    result = forecaster.forecast_multi_horizon(pd.DataFrame(), object())
    assert set(result) == {"p10", "p50", "p90"}
    assert all(len(values) == 24 and np.isfinite(values).all() for values in result.values())
