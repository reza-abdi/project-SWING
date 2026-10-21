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
    failed_result = {
        "grid_resilience_index": 0.0,
        "collapsed": True,
        "voltage_score": 0.0,
        "loading_score": 0.0,
        "security_score": 0.0,
    }
    try:
        bus_values = [float(value) for value in net.res_bus["vm_pu"]]
        line_values = [float(value) for value in net.res_line["loading_percent"]]
    except (AttributeError, KeyError, TypeError, ValueError):
        return failed_result.copy()

    try:
        converged = net.get("converged")
    except AttributeError:
        converged = getattr(net, "converged", None)
    line_count = len(net.line)
    invalid_measurements = (
        not bus_values
        or any(not math.isfinite(value) for value in bus_values)
        or (line_count > 0 and (len(line_values) != line_count or any(not math.isfinite(value) for value in line_values)))
    )
    if converged is not None and not bool(converged):
        return failed_result.copy()
    if invalid_measurements:
        return failed_result.copy()

    voltage_score = _clamp(100.0 - (max(abs(value - 1.0) for value in bus_values) / 0.10) * 100.0)
    if line_values:
        max_loading = max(line_values)
        loading_score = _clamp(100.0 - max(0.0, max_loading - 80.0) * 2.0)
    else:
        loading_score = 100.0

    overloaded_count = sum(value > 100.0 for value in line_values)
    security_score = _clamp(100.0 - overloaded_count * 15.0)
    index = 0.35 * voltage_score + 0.40 * loading_score + 0.25 * security_score
    return {
        "grid_resilience_index": round(index, 2),
        "collapsed": False,
        "voltage_score": round(voltage_score, 2),
        "loading_score": round(loading_score, 2),
        "security_score": round(security_score, 2),
    }
