"""Electrical and topology measurements for pandapower networks."""

import math


def get_topology_metrics(net) -> dict[str, int]:
    """Return element counts, including both two- and three-winding transformers."""
    return {
        "total_buses": len(net.bus),
        "total_lines": len(net.line),
        "total_loads": len(net.load),
        "total_generators": len(net.gen),
        "total_transformers": len(net.trafo) + len(net.trafo3w),
    }


def get_electrical_metrics(net) -> dict[str, float]:
    """Summarize demand, generation, thermal loading, and bus voltage results."""
    return {
        "current_demand_mw": float(net.res_load["p_mw"].sum()),
        "total_generation_mw": float(net.res_gen["p_mw"].sum()),
        "max_line_loading_percent": float(net.res_line["loading_percent"].max()),
        "min_voltage_pu": float(net.res_bus["vm_pu"].min()),
        # Keep the original public key spelling until existing clients migrate.
        "max_volateg_pu": float(net.res_bus["vm_pu"].max()),
    }


def get_security_metrics(net) -> dict[str, object]:
    """Report overloaded lines and treat missing power-flow results as collapse."""
    line_ids = list(net.line.index)
    line_count = len(line_ids)
    try:
        converged = net.get("converged")
    except AttributeError:
        converged = getattr(net, "converged", None)

    if "loading_percent" not in net.res_line:
        loading = None
    else:
        loading = net.res_line["loading_percent"]
    collapsed = converged is False or (line_count > 0 and (loading is None or loading.isna().all()))

    if collapsed:
        overloaded_ids = line_ids
    else:
        overloaded_ids = list(net.res_line.index[net.res_line["loading_percent"] > 100])
    return {
        "overloaded_line_count": len(overloaded_ids),
        "overloaded_line_ids": overloaded_ids,
        "collapsed": bool(collapsed),
    }


def get_observation_vector(net) -> list[float]:
    """Return ordered bus voltages followed by per-unit line loadings."""

    def finite_or_zero(value) -> float:
        number = float(value)
        return number if math.isfinite(number) else 0.0

    voltages = [finite_or_zero(value) for value in net.res_bus["vm_pu"]]
    loadings = [finite_or_zero(value) / 100.0 for value in net.res_line["loading_percent"]]
    return voltages + loadings


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def get_resilience_index(net) -> dict[str, float | bool]:
    """Calculate 35/40/25 voltage, thermal loading, and security scores."""
    voltages = net.res_bus["vm_pu"].dropna()
    if voltages.empty:
        voltage_score = 0.0
    else:
        max_deviation = float((voltages - 1.0).abs().max())
        voltage_score = _clamp(100.0 - (max_deviation / 0.10) * 100.0)

    loadings = net.res_line["loading_percent"].dropna()
    if loadings.empty:
        loading_score = 100.0
    else:
        max_loading = float(loadings.max())
        loading_score = _clamp(100.0 - max(0.0, max_loading - 80.0) * 2.0)

    overloaded_count = int((net.res_line["loading_percent"] > 100.0).sum())
    security_score = _clamp(100.0 - overloaded_count * 15.0)
    index = 0.35 * voltage_score + 0.40 * loading_score + 0.25 * security_score
    return {
        "grid_resilience_index": round(index, 2),
        "collapsed": False,
        "voltage_score": round(voltage_score, 2),
        "loading_score": round(loading_score, 2),
        "security_score": round(security_score, 2),
    }
