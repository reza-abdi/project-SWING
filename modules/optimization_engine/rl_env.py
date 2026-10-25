"""Shared observation and single-step Gymnasium environment for grid actions."""

from __future__ import annotations

import math

import numpy as np


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
