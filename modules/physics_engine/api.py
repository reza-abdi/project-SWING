"""Physics-only FastAPI service for the Project SWING digital twin."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from modules.config import runtime_paths, runtime_settings
from modules.physics_engine.twin_model import TwinModel
from modules.physics_engine.grid_metrics import get_resilience_index, get_security_metrics


grids: dict[str, TwinModel] = {}


def initialize_grids(settings=None) -> dict[str, TwinModel]:
    """Build independent IEEE networks and apply the configured startup states."""
    resolved_settings = settings or runtime_settings()
    candidate_grids = {
        "39": TwinModel("39"),
        "118": TwinModel("118"),
    }
    if candidate_grids["39"].run_baseline_simulation()["simulation_status"] != "COMPLETED":
        raise RuntimeError("IEEE-39 baseline simulation did not converge")
    if candidate_grids["118"].apply_stress_test(
        resolved_settings.startup_load_mult,
        resolved_settings.startup_derate,
    ) != "COMPLETED":
        raise RuntimeError("IEEE-118 startup stress simulation did not converge")

    grids.clear()
    grids.update(candidate_grids)
    return grids


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate service settings at startup and retain them for dependencies."""
    settings = runtime_settings()
    app.state.settings = settings
    initialize_grids(settings)
    try:
        yield
    finally:
        grids.clear()


app = FastAPI(
    title="Digital Twin API",
    description="Physics-only simulation API for IEEE transmission grid models.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", tags=["service"])
def read_root() -> dict[str, str]:
    """Report that the digital-twin service is online."""
    return {"message": "Digital Twin Engine is Online"}


@app.get("/health", tags=["service"])
def read_health() -> JSONResponse:
    """Report service readiness and simulator dependency status without internals."""
    grid_status = {
        grid_id: bool(model.simulation_status == "COMPLETED" and model.net.converged)
        for grid_id, model in grids.items()
    }
    ready = set(grid_status) == {"39", "118"} and all(grid_status.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "unavailable",
            "service": "digital-twin",
            "dependencies": {
                "grid_simulators": "ok" if ready else "unavailable",
                "grids": grid_status,
            },
        },
    )


@app.get("/grid_status", tags=["grid"])
def get_grid_status(grid: str = "39") -> dict[str, object]:
    """Return live demand, generation, resilience, and bus load measurements."""
    if grid not in grids:
        raise HTTPException(status_code=404, detail="Grid not found")

    net = grids[grid].net
    total_demand_mw = float(net.load["p_mw"].sum())
    total_generation_mw = float(net.gen.loc[net.gen["in_service"], "p_mw"].sum())
    bus_loads = {str(int(bus_id)): 0.0 for bus_id in net.bus.index}
    for _, load in net.load.iterrows():
        bus_id = str(int(load["bus"]))
        bus_loads[bus_id] += float(load["p_mw"])

    return {
        "active_grid": f"IEEE {grid}-Bus",
        "buses": len(net.bus),
        "lines": len(net.line),
        "total_demand_mw": round(total_demand_mw, 2),
        "total_generation_capacity_mw": round(total_generation_mw, 2),
        "capacity_max_mw": round(total_demand_mw, 2),
        "resilience": get_resilience_index(net),
        "security": get_security_metrics(net),
        "bus_loads": bus_loads,
    }


@app.get("/topology", tags=["grid"])
def get_topology(grid: str = "118") -> dict[str, list[dict[str, object]]]:
    """Return Cytoscape-compatible bus nodes and transmission-line edges."""
    if grid not in grids:
        raise HTTPException(status_code=404, detail="Grid not found")

    net = grids[grid].net
    generator_buses = set(net.gen["bus"].tolist())
    transformer_buses = set(net.trafo["hv_bus"].tolist()) | set(
        net.trafo["lv_bus"].tolist()
    )
    nodes = []
    for bus_id in net.bus.index:
        attached_loads = net.load.loc[net.load["bus"] == bus_id, "p_mw"]
        current_load = float(attached_loads.sum())
        if bus_id in generator_buses:
            node_type = "GENERATOR"
        elif bus_id in transformer_buses:
            node_type = "TRANSFORMER"
        elif current_load > 0.0:
            node_type = "LOAD"
        else:
            node_type = "JUNCTION"
        nodes.append(
            {
                "data": {
                    "id": str(int(bus_id)),
                    "label": f"Bus {int(bus_id)}",
                    "load": current_load,
                    "node_type": node_type,
                }
            }
        )

    edges = [
        {
            "data": {
                "id": f"line{int(line_id)}",
                "source": str(int(line["from_bus"])),
                "target": str(int(line["to_bus"])),
            }
        }
        for line_id, line in net.line.iterrows()
    ]
    return {"nodes": nodes, "edges": edges}


@app.get("/rl_status", tags=["optimization"])
def get_rl_status() -> dict[str, dict[str, dict[str, object]]]:
    """Report local policy archive presence and metadata without exposing paths."""
    models_dir = runtime_paths().models
    policy_stems = {
        "SHED_LOAD": "shed_load",
        "REDISPATCH_GEN": "redispatch_gen",
    }
    status: dict[str, dict[str, dict[str, object]]] = {}
    for grid_id in ("39", "118"):
        status[grid_id] = {}
        for stem in policy_stems.values():
            policy_path = models_dir / f"rl_optimizer_{stem}_{grid_id}.zip"
            if policy_path.is_file():
                stat = policy_path.stat()
                status[grid_id][stem] = {
                    "trained": True,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "mtime": stat.st_mtime,
                    "last_trained": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            else:
                status[grid_id][stem] = {"trained": False}
    return status
