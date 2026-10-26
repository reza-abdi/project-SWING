"""Guarded CPU inference support for the supplied TFT checkpoint."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import numpy as np

from modules.config import runtime_paths


TFT_CHECKPOINT_SHA256 = "3b0fde570ad83ff4ab70a4b668652c41389d0630def4354520048f941d32d491"
TFT_DATASET_SHA256 = "81441e1cbf792a9a89fbe370e2af2dedef6edece12c3dafc29a7c0441efe3449"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TFTForecaster:
    """Load a reviewed TFT checkpoint explicitly for CPU-only inference."""

    def __init__(self, checkpoint_path: str | Path | None = None) -> None:
        paths = runtime_paths()
        self.project_root = paths.root
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else paths.models / "tft_best_model.ckpt"
        self.model = None
        self.training_dataset_params = None

    def load_model(self, *, trust_checkpoint: bool = False) -> None:
        if not self.checkpoint_path.is_file():
            raise FileNotFoundError(
                f"No TFT checkpoint found at {self.checkpoint_path}. Train the TFT and provide a reviewed checkpoint."
            )
        if not trust_checkpoint:
            raise PermissionError("TFT checkpoint deserialization is disabled until its provenance is trusted")
        if _sha256(self.checkpoint_path) != TFT_CHECKPOINT_SHA256:
            raise ValueError("TFT checkpoint hash does not match the reviewed artifact")
        import torch
        from pytorch_forecasting import TemporalFusionTransformer

        model = TemporalFusionTransformer.load_from_checkpoint(
            str(self.checkpoint_path), map_location=torch.device("cpu")
        )
        model.to(torch.device("cpu"))
        model.eval()
        self.model = model

    def load_training_dataset_config(
        self,
        dataset_path: str | Path | None = None,
        *,
        trust_dataset: bool = False,
    ):
        """Load the serialized TimeSeriesDataSet only after explicit hash trust."""
        path = Path(dataset_path) if dataset_path is not None else runtime_paths().models / "training_dataset.pkl"
        if not path.is_file():
            raise FileNotFoundError(f"TFT training dataset configuration is missing: {path}")
        if not trust_dataset:
            raise PermissionError("TFT dataset pickle loading is disabled until its provenance is trusted")
        if _sha256(path) != TFT_DATASET_SHA256:
            raise ValueError("TFT dataset hash does not match the reviewed artifact")
        import pickle
        from pytorch_forecasting import TimeSeriesDataSet

        with path.open("rb") as handle:
            dataset = pickle.load(handle)
        if not isinstance(dataset, TimeSeriesDataSet):
            raise TypeError("serialized TFT dataset has an unexpected type")
        self.training_dataset_params = dataset
        return dataset

    def build_recent_history_window(
        self,
        window: int = 168,
        csv_path: str | Path | None = None,
        *,
        prediction_length: int = 24,
    ) -> pd.DataFrame:
        """Return 168 encoder plus 24 known-covariate rows from historical CSV."""
        if window < 1 or prediction_length < 1:
            raise ValueError("window and prediction_length must be positive")
        path = Path(csv_path) if csv_path is not None else runtime_paths().data / "processed_data" / "tft_ready_data.csv"
        if not path.is_file():
            raise FileNotFoundError(f"historical TFT feature data is missing: {path}")
        frame = pd.read_csv(path)
        if "Datetime" not in frame.columns:
            raise ValueError("historical TFT data must include Datetime")
        frame["Datetime"] = pd.to_datetime(frame["Datetime"], errors="raise")
        frame = frame.sort_values("Datetime").tail(window + prediction_length).reset_index(drop=True)
        expected_length = window + prediction_length
        if len(frame) != expected_length:
            raise ValueError(f"historical TFT data needs at least {expected_length} hourly rows")
        gaps = frame["Datetime"].diff().dropna()
        if not bool((gaps == pd.Timedelta(hours=1)).all()):
            raise ValueError("historical TFT inference window must contain contiguous hourly rows")
        for column in ("month", "dayofweek", "hour", "region"):
            if column in frame.columns:
                frame[column] = frame[column].astype(str)
        frame.attrs["source_type"] = "historical_proxy"
        frame.attrs["source_description"] = "tail of processed historical data; not live telemetry"
        frame.attrs["encoder_length"] = window
        frame.attrs["prediction_length"] = prediction_length
        return frame

    def forecast_multi_horizon(self, recent_history_df: pd.DataFrame, training_dataset=None) -> dict[str, list[float]]:
        """Return p10/p50/p90 vectors over the model's full 24-hour horizon."""
        if self.model is None:
            raise RuntimeError("Call load_model(trust_checkpoint=True) before forecasting")
        dataset = training_dataset if training_dataset is not None else self.training_dataset_params
        if dataset is None:
            raise RuntimeError("Call load_training_dataset_config(trust_dataset=True) before forecasting")
        import torch
        from pytorch_forecasting import TimeSeriesDataSet

        inference_dataset = TimeSeriesDataSet.from_dataset(
            dataset, recent_history_df, predict=True, stop_randomization=True
        )
        dataloader = inference_dataset.to_dataloader(train=False, batch_size=1, num_workers=0)
        with torch.no_grad():
            raw = self.model.predict(dataloader, mode="quantiles")
        if hasattr(raw, "detach"):
            raw = raw.detach().cpu().numpy()
        values = np.asarray(raw)
        if values.ndim != 3 or values.shape[0] != 1 or values.shape[1] != 24 or values.shape[2] != 3:
            raise ValueError("TFT prediction must have shape (1, 24, 3) for p10/p50/p90")
        if not np.isfinite(values).all():
            raise ValueError("TFT prediction contains non-finite values")
        return {key: [float(item) for item in values[0, :, index]] for index, key in enumerate(("p10", "p50", "p90"))}
