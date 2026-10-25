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


def calculate_reward(grid_id: str, mw_amount: float, search_ceiling_mw: float, converged: bool, max_loading: float) -> float:
    """Score MW use, overload severity, and a secure-convergence bonus."""
    if grid_id not in {"39", "118"} or search_ceiling_mw <= 0:
        raise ValueError("invalid grid or search ceiling")
    mw_coefficient, overload_coefficient = (0.1, 0.005) if grid_id == "39" else (1.0, 0.05)
    mw_penalty = mw_amount / search_ceiling_mw
    overload_penalty = max(0.0, max_loading - 100.0) ** 2
    secure_bonus = 10.0 if converged and max_loading <= 100.0 else 0.0
    return -(mw_coefficient * mw_penalty) - (overload_coefficient * overload_penalty) + secure_bonus


class GridOptimizeEnv(gym.Env):
    """Single-action environment over an isolated pandapower network."""

    metadata = {"render_modes": []}
    ACTION_TYPES = ("SHED_LOAD", "REDISPATCH_GEN")

    def __init__(
        self,
        grid_id: str = "39",
        *,
        net=None,
        action_type: str = "SHED_LOAD",
        search_ceiling_mw: float = 300.0,
        load_multiplier_range: tuple[float, float] = (1.0, 2.0),
        derate_range: tuple[float, float] = (0.05, 0.5),
    ):
        super().__init__()
        if grid_id not in {"39", "118"}:
            raise ValueError("grid_id must be '39' or '118'")
        if action_type not in self.ACTION_TYPES:
            raise ValueError("action_type must be SHED_LOAD or REDISPATCH_GEN")
        if not math.isfinite(search_ceiling_mw) or search_ceiling_mw <= 0:
            raise ValueError("search_ceiling_mw must be finite and positive")
        if net is None:
            from pandapower import networks

            net = networks.case39() if grid_id == "39" else networks.case118()
        self.grid_id = grid_id
        self.action_type = action_type
        self.base_net = copy.deepcopy(net)
        pp.runpp(self.base_net)
        self.net = copy.deepcopy(self.base_net)
        self.search_ceiling_mw = 100.0 if grid_id == "39" else float(search_ceiling_mw)
        self.load_multiplier_range = load_multiplier_range
        self.derate_range = derate_range
        facilities = self.base_net.load if action_type == "SHED_LOAD" else self.base_net.gen
        self.valid_target_buses = sorted(int(bus) for bus in facilities["bus"].unique())
        if not self.valid_target_buses:
            raise ValueError(f"No buses with a facility for {action_type}")
        self.action_space = spaces.Box(low=0.0, high=self.search_ceiling_mw, shape=(1,), dtype=np.float32)
        observation_size = len(net.line) + len(net.bus) + 1
        self.observation_space = spaces.Box(low=0.0, high=np.inf, shape=(observation_size,), dtype=np.float32)
        self.target_bus = int(net.bus.index[0])
        self.reset_attempts = 10

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        load_range = (1.0, 1.4) if self.grid_id == "39" else self.load_multiplier_range
        derate_range = (0.3, 0.7) if self.grid_id == "39" else self.derate_range
        for attempt in range(1, self.reset_attempts + 1):
            candidate = copy.deepcopy(self.base_net)
            load_multiplier = float(self.np_random.uniform(*load_range))
            derate_multiplier = float(self.np_random.uniform(*derate_range))
            candidate.load.loc[:, "p_mw"] = self.base_net.load["p_mw"] * load_multiplier
            candidate.load.loc[:, "q_mvar"] = self.base_net.load["q_mvar"] * load_multiplier
            candidate.line.loc[:, "max_i_ka"] = self.base_net.line["max_i_ka"] * derate_multiplier
            try:
                pp.runpp(candidate)
            except (pp.LoadflowNotConverged, ValueError, FloatingPointError):
                continue
            if not bool(candidate.converged):
                continue
            self.net = candidate
            self.target_bus = int(self.np_random.choice(self.valid_target_buses))
            return build_observation_vector(self.net, self.target_bus), {
                "grid": self.grid_id,
                "attempt": attempt,
                "load_multiplier": load_multiplier,
                "derate_multiplier": derate_multiplier,
            }
        raise RuntimeError(f"could not find a convergent {self.grid_id}-bus reset in {self.reset_attempts} attempts")

    def step(self, action):
        """Apply one sampled bounded action to a candidate network."""
        action_value = np.asarray(action, dtype=np.float64)
        if action_value.shape != (1,) or not np.all(np.isfinite(action_value)):
            raise ValueError("action must be a finite one-element MW array")
        mw_amount = float(np.clip(action_value[0], 0.0, self.search_ceiling_mw))
        action_type = self.action_type
        candidate = copy.deepcopy(self.net)
        facilities = candidate.load if action_type == "SHED_LOAD" else candidate.gen
        matching = facilities.index[facilities["bus"] == self.target_bus]
        if matching.empty:
            raise RuntimeError(f"{action_type} has no available facility")
        facility_index = int(matching[0])
        target_bus = self.target_bus
        amount = mw_amount
        if action_type == "SHED_LOAD":
            amount = min(amount, float(facilities.at[facility_index, "p_mw"]))
        if amount <= 0:
            raise RuntimeError(f"{action_type} has no positive available MW")
        if action_type == "SHED_LOAD":
            candidate.load.at[facility_index, "p_mw"] -= amount
        else:
            candidate.gen.at[facility_index, "p_mw"] += amount
        converged = True
        try:
            pp.runpp(candidate)
        except (pp.LoadflowNotConverged, ValueError, FloatingPointError):
            converged = False
        if not converged or not bool(candidate.converged):
            max_loading = 999.0
        else:
            self.net = candidate
            max_loading = float(candidate.res_line["loading_percent"].max()) if len(candidate.res_line) else 0.0
        reward = calculate_reward(self.grid_id, amount, self.search_ceiling_mw, converged, max_loading)
        observation = build_observation_vector(self.net, target_bus)
        info = {
            "action_type": action_type,
            "target_bus": target_bus,
            "mw_amount": amount,
            "converged": converged,
            "max_loading_percent": max_loading,
        }
        return observation, reward, True, False, info
