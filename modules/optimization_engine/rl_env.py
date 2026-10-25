"""Shared observation and single-step Gymnasium environment for grid actions."""

from __future__ import annotations

import copy
import math

import numpy as np
import gymnasium as gym
from gymnasium import spaces
import pandapower as pp


def build_observation_vector(net, target_bus: int) -> np.ndarray:
    """Return line loading, bus voltage and normalized target in stable order."""
    line_values = [float(value) / 100.0 for value in net.res_line["loading_percent"]]
    bus_values = [float(value) for value in net.res_bus["vm_pu"]]
    values = [value if math.isfinite(value) else 0.0 for value in (*line_values, *bus_values)]
    bus_ids = list(net.bus.index)
    if target_bus not in bus_ids:
        raise ValueError("target_bus is not present in the network")
    target = bus_ids.index(target_bus) / max(1, len(bus_ids) - 1)
    return np.asarray([*values, target], dtype=np.float32)


class GridOptimizeEnv(gym.Env):
    """Single-action environment over an isolated pandapower network."""

    metadata = {"render_modes": []}
    ACTION_TYPES = ("SHED_LOAD", "REDISPATCH_GEN")

    def __init__(self, grid_id: str = "39", *, net=None, max_action_mw: float = 50.0):
        super().__init__()
        if grid_id not in {"39", "118"}:
            raise ValueError("grid_id must be '39' or '118'")
        if not math.isfinite(max_action_mw) or max_action_mw <= 0:
            raise ValueError("max_action_mw must be finite and positive")
        if net is None:
            from pandapower import networks

            net = networks.case39() if grid_id == "39" else networks.case118()
        self.grid_id = grid_id
        self.base_net = copy.deepcopy(net)
        pp.runpp(self.base_net)
        self.net = copy.deepcopy(self.base_net)
        self.max_action_mw = float(max_action_mw)
        self.action_space = spaces.Discrete(len(self.ACTION_TYPES))
        observation_size = len(net.line) + len(net.bus) + 1
        self.observation_space = spaces.Box(low=0.0, high=np.inf, shape=(observation_size,), dtype=np.float32)
        self.target_bus = int(net.bus.index[0])

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self.net = copy.deepcopy(self.base_net)
        self.target_bus = int(self.np_random.choice(list(self.net.bus.index)))
        return build_observation_vector(self.net, self.target_bus), {"grid": self.grid_id}
