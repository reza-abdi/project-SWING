"""Non-executing structural checks for the supplied SAC policy packages."""

import json
import zipfile

import pytest

from modules.optimization_engine.rl_env import GridOptimizeEnv
from modules.optimization_engine.rl_optimizer import RLOptimizer


@pytest.mark.parametrize(
    ("grid", "action_type"),
    [(grid, action) for grid in ("39", "118") for action in ("SHED_LOAD", "REDISPATCH_GEN")],
)
def test_policy_zip_has_expected_structure_without_deserialization(grid, action_type) -> None:
    optimizer = RLOptimizer(grid)
    path = optimizer.model_path(action_type)
    assert path.is_file()
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert {"data", "policy.pth", "pytorch_variables.pth", "_stable_baselines3_version"} <= names
        metadata = json.loads(archive.read("data"))
        assert "gymnasium.spaces.box.Box" in metadata["observation_space"][":type:"]
        assert "gymnasium.spaces.box.Box" in metadata["action_space"][":type:"]

    env = GridOptimizeEnv(grid, action_type=action_type)
    assert optimizer.expected_observation_size == env.observation_space.shape[0]
    assert env.action_space.shape == (1,)
