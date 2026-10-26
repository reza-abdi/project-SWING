"""Guarded CPU inference support for the supplied TFT checkpoint."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

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
