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
