"""Grid-specific SAC policy loading and bounded MW inference."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from modules.config import runtime_paths


class RLOptimizer:
    """Load a pre-trained policy for one grid and corrective action type."""

    ACTION_TYPES = ("SHED_LOAD", "REDISPATCH_GEN")

    def __init__(self, grid_type: str, models_dir: str | Path | None = None) -> None:
        if grid_type not in {"39", "118"}:
            raise ValueError("grid_type must be '39' or '118'")
        self.grid_type = grid_type
        self.models_dir = Path(models_dir) if models_dir is not None else runtime_paths().models
        self.model = None
        self.action_type: str | None = None
        from pandapower import networks

        net = networks.case39() if grid_type == "39" else networks.case118()
        self.expected_observation_size = len(net.line) + len(net.bus) + 1

    def model_path(self, action_type: str) -> Path:
        if action_type not in self.ACTION_TYPES:
            raise ValueError("RL policies support SHED_LOAD and REDISPATCH_GEN only")
        return self.models_dir / f"rl_optimizer_{action_type.lower()}_{self.grid_type}.zip"

    def load_model(self, action_type: str) -> bool:
        """Load a selected policy; report unavailable weights without failing startup."""
        path = self.model_path(action_type)
        self.model = None
        self.action_type = None
        if not path.is_file():
            return False
        from stable_baselines3 import SAC

        self.model = SAC.load(str(path), device="cpu")
        self.action_type = action_type
        return True

    def predict_mw(self, observation: np.ndarray, *, search_ceiling_mw: float | None = None) -> float:
        """Return one finite, nonnegative MW action within the policy ceiling."""
        if self.model is None:
            raise RuntimeError("No trained RL policy is loaded")
        vector = np.asarray(observation, dtype=np.float32)
        if vector.ndim != 1 or vector.size != self.expected_observation_size or not np.all(np.isfinite(vector)):
            raise ValueError(f"observation must be a finite vector of length {self.expected_observation_size}")
        action, _ = self.model.predict(vector, deterministic=True)
        values = np.asarray(action, dtype=np.float64).reshape(-1)
        if values.size != 1 or np.isnan(values[0]):
            raise ValueError("policy returned an invalid MW action")
        ceiling = search_ceiling_mw if search_ceiling_mw is not None else (100.0 if self.grid_type == "39" else 300.0)
        if not np.isfinite(ceiling) or ceiling <= 0:
            raise ValueError("search ceiling must be finite and positive")
        amount = float(np.clip(values[0], 0.0, ceiling))
        return amount
