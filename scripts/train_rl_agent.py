"""Offline training CLI for the grid-specific SAC optimization policies."""

from __future__ import annotations

import argparse
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
    return parser


def train(grid: str, action: str, timesteps: int, output_dir: Path | None = None, seed: int = 0) -> Path:
    if timesteps < 1:
        raise ValueError("timesteps must be positive")
    from pandapower import networks
    from stable_baselines3 import SAC

    base_net = networks.case39() if grid == "39" else networks.case118()
    env = GridOptimizeEnv(grid, net=base_net, action_type=action)
    model = SAC("MlpPolicy", env, verbose=0, seed=seed)
    models_dir = output_dir or runtime_paths().models
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact = models_dir / f"rl_optimizer_{action.lower()}_{grid}.zip"
    model.learn(total_timesteps=timesteps)
    model.save(str(artifact))
    return artifact


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact = train(args.grid, args.action, args.timesteps)
    print(f"Saved trained policy to {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
