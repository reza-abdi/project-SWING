"""Offline training CLI for the grid-specific SAC optimization policies."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.config import runtime_paths
from modules.optimization_engine.rl_env import GridOptimizeEnv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train one Project SWING SAC corrective-action policy.")
    parser.add_argument("--grid", choices=("39", "118"), required=True)
    parser.add_argument("--action", choices=GridOptimizeEnv.ACTION_TYPES, required=True)
    parser.add_argument("--timesteps", type=int, default=50_000)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true", help="replace both existing policy and reward CSV")
    return parser


def train(
    grid: str,
    action: str,
    timesteps: int,
    output_dir: Path | None = None,
    seed: int = 0,
    overwrite: bool = False,
) -> Path:
    if timesteps < 1:
        raise ValueError("timesteps must be positive")
    from pandapower import networks
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import BaseCallback

    class RewardCSVLogger(BaseCallback):
        def __init__(self, csv_path: Path):
            super().__init__(verbose=0)
            self.csv_path = csv_path
            self.file = None
            self.writer = None

        def _on_training_start(self) -> None:
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            self.file = self.csv_path.open("w", newline="", encoding="utf-8")
            self.writer = csv.writer(self.file)
            self.writer.writerow(["timestep", "reward", "resulting_max_loading", "mw_amount", "converged"])

        def _on_step(self) -> bool:
            for info, reward in zip(self.locals.get("infos", [{}]), self.locals.get("rewards", [0.0])):
                self.writer.writerow([
                    self.num_timesteps,
                    float(reward),
                    info.get("max_loading_percent"),
                    info.get("mw_amount"),
                    info.get("converged"),
                ])
            return True

        def _on_training_end(self) -> None:
            if self.file is not None:
                self.file.close()
                self.file = None

    base_net = networks.case39() if grid == "39" else networks.case118()
    env = GridOptimizeEnv(grid, net=base_net, action_type=action)
    model = SAC("MlpPolicy", env, verbose=0, seed=seed)
    models_dir = output_dir or runtime_paths().models
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact = models_dir / f"rl_optimizer_{action.lower()}_{grid}.zip"
    log_path = models_dir / f"rl_optimizer_{action.lower()}_{grid}_rewards.csv"
    existing = [path for path in (artifact, log_path) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError("training output exists; choose another --output-dir or pass --overwrite")
    model.learn(total_timesteps=timesteps, callback=RewardCSVLogger(log_path))
    model.save(str(artifact))
    return artifact


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact = train(args.grid, args.action, args.timesteps, args.output_dir, args.seed, args.overwrite)
    print(f"Saved trained policy to {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
