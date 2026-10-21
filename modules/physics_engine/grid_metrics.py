"""Electrical and topology measurements for pandapower networks."""


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
