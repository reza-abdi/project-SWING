"""Scenario transformations for the pandapower digital twin."""


def apply_load_multiplier(net, multiplier: float):
    """Scale active and reactive load on every bus in place."""
    net.load["p_mw"] = net.load["p_mw"] * multiplier
    net.load["q_mvar"] = net.load["q_mvar"] * multiplier
    return net
