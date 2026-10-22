"""Scenario transformations for the pandapower digital twin."""

import math


def apply_load_multiplier(net, multiplier: float):
    """Scale active and reactive load on every bus in place."""
    net.load["p_mw"] = net.load["p_mw"] * multiplier
    net.load["q_mvar"] = net.load["q_mvar"] * multiplier
    return net


def derate_lines(net, derate_multiplier: float):
    """Reduce line current capacity with a finite positive multiplier."""
    if not math.isfinite(derate_multiplier) or derate_multiplier <= 0:
        raise ValueError("derate_multiplier must be a finite positive number")
    net.line["max_i_ka"] = net.line["max_i_ka"] * derate_multiplier
    return net
