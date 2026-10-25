"""Physics-only FastAPI service for the Project SWING digital twin."""

from contextlib import asynccontextmanager
import asyncio
import copy
from datetime import datetime, timezone
from importlib import import_module
import math
import time
from typing import AsyncIterator, Literal

import pandapower as pp
from fastapi import FastAPI
from fastapi import HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.config import runtime_paths, runtime_settings
from modules.event_store import log_event
from modules.physics_engine.twin_model import TwinModel
from modules.physics_engine.grid_metrics import get_resilience_index, get_security_metrics


grids: dict[str, TwinModel] = {}
contingency_cache: dict[str, dict[str, object]] = {
    grid_id: {"status": "unavailable", "lines": {}, "generators": {}}
    for grid_id in ("39", "118")
}
GridId = Literal["39", "118"]
ActionType = Literal["SHED_LOAD", "REDISPATCH_GEN", "LOAD_REDISTRIBUTION"]
app = FastAPI(
    title="Digital Twin API",
    description="Physics-only simulation API for IEEE transmission grid models.",
    version="1.0.0",
)


class ActionRequest(BaseModel):
    """Validated payload for a non-mutating action feasibility check."""

    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    target_bus: int = Field(ge=0, strict=True)
    mw_amount: float = Field(ge=0.0, allow_inf_nan=False)
    secondary_bus: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_bus_pair(self) -> "ActionRequest":
        if self.action_type == "LOAD_REDISTRIBUTION":
            if self.secondary_bus is None:
                raise ValueError("secondary_bus is required for LOAD_REDISTRIBUTION")
            if self.secondary_bus == self.target_bus:
                raise ValueError("redistribution buses must be distinct")
        elif self.secondary_bus is not None:
            raise ValueError("secondary_bus is only valid for LOAD_REDISTRIBUTION")
        return self


class OptimizeRequest(BaseModel):
    """Bounded optimizer search request; it never authorizes an actuation."""

    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    target_bus: int = Field(ge=0, strict=True)
    secondary_bus: int | None = Field(default=None, ge=0, strict=True)
    search_ceiling_mw: float = Field(default=300.0, gt=0.0, le=10000.0, allow_inf_nan=False)
    tolerance_mw: float = Field(default=0.5, gt=0.0, le=1000.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bus_pair(self) -> "OptimizeRequest":
        if self.action_type == "LOAD_REDISTRIBUTION":
            if self.secondary_bus is None:
                raise ValueError("secondary_bus is required for LOAD_REDISTRIBUTION")
            if self.secondary_bus == self.target_bus:
                raise ValueError("redistribution buses must be distinct")
        elif self.secondary_bus is not None:
            raise ValueError("secondary_bus is only valid for LOAD_REDISTRIBUTION")
        return self


class StressTestRequest(BaseModel):
    """Positive absolute stress multipliers for the baseline grid case."""

    model_config = ConfigDict(extra="forbid")

    load_multiplier: float = Field(default=1.0, gt=0.0, le=10.0, allow_inf_nan=False)
    derate_multiplier: float = Field(default=1.0, gt=0.0, le=10.0, allow_inf_nan=False)


def validate_grid_id(grid_id: str) -> GridId:
    """Restrict API grid selection to the two supported IEEE network IDs."""
    if grid_id not in {"39", "118"}:
        raise ValueError("grid must be '39' or '118'")
    return grid_id  # type: ignore[return-value]


def _apply_action(
    test_net,
    action_type: str,
    target_bus: int,
    mw_amount: float,
    secondary_bus: int | None = None,
) -> bool:
    """Apply one bounded corrective action to an isolated candidate network."""
    try:
        amount = float(mw_amount)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(amount) or amount < 0.0:
        return False

    if action_type == "SHED_LOAD":
        matching = test_net.load.index[test_net.load["bus"] == target_bus]
        if matching.empty:
            return False
        load_id = matching[0]
        current_mw = float(test_net.load.at[load_id, "p_mw"])
        test_net.load.at[load_id, "p_mw"] = max(0.0, current_mw - amount)
        return True

    if action_type == "REDISPATCH_GEN":
        matching = test_net.gen.index[
            (test_net.gen["bus"] == target_bus) & test_net.gen["in_service"]
        ]
        if matching.empty:
            return False
        gen_id = matching[0]
        current_mw = float(test_net.gen.at[gen_id, "p_mw"])
        maximum_mw = float(test_net.gen.at[gen_id, "max_p_mw"])
        if not math.isfinite(maximum_mw) or current_mw + amount > maximum_mw:
            return False
        test_net.gen.at[gen_id, "p_mw"] = current_mw + amount
        return True

    if action_type == "LOAD_REDISTRIBUTION":
        if secondary_bus is None or secondary_bus == target_bus:
            return False
        source_matches = test_net.load.index[test_net.load["bus"] == target_bus]
        destination_matches = test_net.load.index[test_net.load["bus"] == secondary_bus]
        if source_matches.empty or destination_matches.empty:
            return False
        source_id, destination_id = source_matches[0], destination_matches[0]
        source_mw = float(test_net.load.at[source_id, "p_mw"])
        shifted_mw = min(amount, source_mw)
        test_net.load.at[source_id, "p_mw"] = source_mw - shifted_mw
        test_net.load.at[destination_id, "p_mw"] += shifted_mw
        return True

    return False


def _evaluate_action(
    base_net,
    action_type: str,
    target_bus: int,
    mw_amount: float,
    secondary_bus: int | None = None,
) -> tuple[bool | None, float | None, object | None]:
    """Return outcome, loading and candidate network from isolated physics."""
    test_net = copy.deepcopy(base_net)
    if not _apply_action(test_net, action_type, target_bus, mw_amount, secondary_bus):
        return None, None, None
    try:
        pp.runpp(test_net, algorithm="nr")
    except pp.LoadflowNotConverged:
        return False, None, None
    if test_net.res_line.empty:
        return True, 0.0, test_net
    max_loading = float(test_net.res_line["loading_percent"].max())
    if not math.isfinite(max_loading):
        return False, None, None
    return True, max_loading, test_net


def _test_action(
    base_net,
    action_type: str,
    target_bus: int,
    mw_amount: float,
    secondary_bus: int | None = None,
) -> tuple[bool | None, float | None]:
    """Solve a corrective action on a deep copy without changing live state."""
    converged, max_loading, _ = _evaluate_action(
        base_net, action_type, target_bus, mw_amount, secondary_bus
    )
    return converged, max_loading


def _emergency_grid_rescue(base_net) -> tuple[bool, float, float | None]:
    """Estimate global load shedding needed for solvability on a private copy."""
    rescue_net = copy.deepcopy(base_net)
    total_original_load = float(rescue_net.load["p_mw"].sum())
    for _ in range(9):
        rescue_net.load["p_mw"] *= 0.9
        try:
            pp.runpp(rescue_net, algorithm="nr")
        except pp.LoadflowNotConverged:
            continue

        max_loading = (
            float(rescue_net.res_line["loading_percent"].max())
            if not rescue_net.res_line.empty
            else 0.0
        )
        if not math.isfinite(max_loading):
            continue
        total_mw_shed = total_original_load - float(rescue_net.load["p_mw"].sum())
        return True, total_mw_shed, max_loading
    return False, 0.0, None


def _bisect_action(
    base_net,
    request: OptimizeRequest,
    *,
    max_loading_limit: float = 100.0,
    max_iterations: int = 48,
) -> dict[str, object]:
    """Find minimum feasible MW by bounded bisection over copied grid solves."""
    arguments = (
        base_net,
        request.action_type,
        request.target_bus,
    )
    secondary_bus = request.secondary_bus
    low = 0.0
    low_converged, low_loading = _test_action(
        *arguments, low, secondary_bus
    )
    if low_converged is None:
        return {"feasible": False, "mw_amount": None, "error": "Invalid action target."}
    if low_converged and low_loading is not None and low_loading <= max_loading_limit:
        return {
            "feasible": True,
            "mw_amount": 0.0,
            "resulting_max_loading_percent": round(low_loading, 2),
            "method": "BISECTION",
            "iterations": 0,
        }

    high = float(request.search_ceiling_mw)
    high_converged, high_loading = _test_action(
        *arguments, high, secondary_bus
    )
    if high_converged is None:
        return {"feasible": False, "mw_amount": None, "error": "Invalid action target."}
    if not high_converged or high_loading is None or high_loading > max_loading_limit:
        return {
            "feasible": False,
            "mw_amount": None,
            "resulting_max_loading_percent": high_loading,
            "error": "Search ceiling cannot satisfy the loading limit.",
        }

    iterations = 0
    while high - low > request.tolerance_mw and iterations < max_iterations:
        midpoint = (low + high) / 2.0
        converged, loading = _test_action(*arguments, midpoint, secondary_bus)
        iterations += 1
        if converged and loading is not None and loading <= max_loading_limit:
            high, high_loading = midpoint, loading
        else:
            low = midpoint

    return {
        "feasible": True,
        "mw_amount": round(high, 4),
        "resulting_max_loading_percent": round(high_loading, 2),
        "method": "BISECTION",
        "iterations": iterations,
    }


def _physical_action_ceiling(
    net,
    action_type: str,
    target_bus: int,
) -> float:
    """Calculate an action's real available MW at the selected facility."""
    if action_type in {"SHED_LOAD", "LOAD_REDISTRIBUTION"}:
        total = net.load.loc[net.load["bus"] == target_bus, "p_mw"].sum()
        return max(0.0, float(total))
    generators = net.gen.loc[
        (net.gen["bus"] == target_bus) & net.gen["in_service"]
    ]
    if generators.empty:
        return 0.0
    headroom = (generators["max_p_mw"] - generators["p_mw"]).clip(lower=0.0)
    total_headroom = float(headroom.sum())
    return total_headroom if math.isfinite(total_headroom) else 0.0


def _smart_order_router(base_net, request: OptimizeRequest) -> dict[str, object]:
    """Try the requested action, then route it across bounded physical candidates."""
    initial = _bisect_action(base_net, request)
    if initial.get("feasible"):
        return {
            **initial,
            "action_type": request.action_type,
            "target_bus": request.target_bus,
            "secondary_bus": request.secondary_bus,
        }

    loads_by_bus = base_net.load.groupby("bus")["p_mw"].sum().sort_values(ascending=False)
    heavy_buses = [int(bus) for bus in loads_by_bus.index[:10]]
    light_buses = [int(bus) for bus in loads_by_bus.sort_values().index]
    action_types = [request.action_type]
    if request.action_type == "LOAD_REDISTRIBUTION":
        action_types.append("SHED_LOAD")

    last_failure: dict[str, object] = initial
    for action_type in action_types:
        if action_type == "REDISPATCH_GEN":
            candidates = [
                int(bus)
                for bus in base_net.gen.loc[base_net.gen["in_service"], "bus"].unique()
            ]
        else:
            candidates = heavy_buses
        for target_bus in candidates:
            if action_type == request.action_type and target_bus == request.target_bus:
                if action_type != "LOAD_REDISTRIBUTION" or (
                    request.secondary_bus in set(int(bus) for bus in loads_by_bus.index)
                    and request.secondary_bus != target_bus
                ):
                    continue
            secondary_bus = None
            if action_type == "LOAD_REDISTRIBUTION":
                valid_destinations = set(int(bus) for bus in loads_by_bus.index)
                if request.secondary_bus in valid_destinations and request.secondary_bus != target_bus:
                    secondary_bus = request.secondary_bus
                else:
                    secondary_bus = next(
                        (bus for bus in light_buses if bus != target_bus), None
                    )
                if secondary_bus is None:
                    continue

            physical_ceiling = _physical_action_ceiling(base_net, action_type, target_bus)
            ceiling = min(request.search_ceiling_mw, physical_ceiling)
            if ceiling <= 0.0:
                continue
            candidate_request = OptimizeRequest(
                action_type=action_type,
                target_bus=target_bus,
                secondary_bus=secondary_bus,
                search_ceiling_mw=ceiling,
                tolerance_mw=request.tolerance_mw,
            )
            result = _bisect_action(base_net, candidate_request)
            if result.get("feasible"):
                return {
                    **result,
                    "action_type": action_type,
                    "target_bus": target_bus,
                    "secondary_bus": secondary_bus,
                }
            last_failure = result

    return {
        **last_failure,
        "feasible": False,
        "action_type": request.action_type,
        "target_bus": request.target_bus,
        "secondary_bus": request.secondary_bus,
    }


@app.post("/optimize_action/{grid}", tags=["optimization"])
def optimize_action(grid: str, request: OptimizeRequest) -> dict[str, object]:
    """Suggest a bounded action using a validated SAC result or physics search."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")

    base_net = grids[grid_id].net
    physical_ceiling = _physical_action_ceiling(
        base_net, request.action_type, request.target_bus
    )
    bounded_request = request.model_copy(
        update={
            "search_ceiling_mw": min(request.search_ceiling_mw, physical_ceiling)
            if physical_ceiling > 0.0
            else request.search_ceiling_mw
        }
    )
    rl_error: str | None = None
    if request.action_type in {"SHED_LOAD", "REDISPATCH_GEN"} and physical_ceiling > 0.0:
        try:
            rl_env_module = import_module("modules.optimization_engine.rl_env")
            optimizer_module = import_module("modules.optimization_engine.rl_optimizer")

            optimizer = optimizer_module.RLOptimizer(grid_type=grid_id)
            optimizer.load_model(request.action_type)
            observation = rl_env_module.build_observation_vector(base_net, request.target_bus)
            predicted_mw = float(optimizer.predict_mw(observation))
            if math.isfinite(predicted_mw) and 0.0 <= predicted_mw <= physical_ceiling:
                converged, max_loading = _test_action(
                    base_net,
                    request.action_type,
                    request.target_bus,
                    predicted_mw,
                    request.secondary_bus,
                )
                if converged and max_loading is not None and max_loading <= 100.2:
                    return {
                        "feasible": True,
                        "mw_amount": round(predicted_mw, 4),
                        "resulting_max_loading_percent": round(max_loading, 2),
                        "method": "RL",
                        "action_type": request.action_type,
                        "target_bus": request.target_bus,
                        "secondary_bus": request.secondary_bus,
                    }
            rl_error = "policy suggestion failed bounds or physics recheck"
        except Exception as exc:
            # Model loading and inference are optional; always fall through to physics search.
            rl_error = type(exc).__name__

    result = _smart_order_router(base_net, bounded_request)
    result.setdefault("method", "SMART_ORDER_ROUTER")
    if (
        result.get("feasible")
        and result.get("action_type") == request.action_type
        and result.get("target_bus") == request.target_bus
        and result.get("secondary_bus") == request.secondary_bus
    ):
        result["method"] = "BISECTION"
    else:
        result["method"] = "SMART_ORDER_ROUTER"
    result["rl_fallback_reason"] = rl_error
    return result


@app.post("/validate_action/{grid}", tags=["optimization"])
def validate_action(grid: str, action: ActionRequest) -> dict[str, object]:
    """Assess an action on a copy and report security and resilience changes."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")

    base_net = grids[grid_id].net
    gri_before = float(get_resilience_index(base_net)["grid_resilience_index"])
    converged, max_loading, candidate = _evaluate_action(
        base_net,
        action.action_type,
        action.target_bus,
        action.mw_amount,
        action.secondary_bus,
    )
    if converged is None:
        return {
            "valid": False,
            "resulting_max_loading_percent": None,
            "gri_before": gri_before,
            "gri_after": None,
            "gri_improvement": None,
            "error": "Action target does not have a compatible load or generator facility.",
        }
    if not converged or candidate is None or max_loading is None:
        return {
            "valid": False,
            "resulting_max_loading_percent": None,
            "gri_before": gri_before,
            "gri_after": None,
            "gri_improvement": None,
            "error": "Power flow did not converge for this action.",
        }

    gri_after = float(get_resilience_index(candidate)["grid_resilience_index"])
    secure = max_loading <= 100.2
    return {
        "valid": secure,
        "resulting_max_loading_percent": round(max_loading, 2),
        "gri_before": gri_before,
        "gri_after": gri_after,
        "gri_improvement": round(gri_after - gri_before, 2),
        "error": None if secure else f"Max line loading {max_loading:.1f}% -- still overloaded.",
    }


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
    for grid_id in contingency_cache:
        contingency_cache[grid_id] = {
            "status": "unavailable",
            "lines": {},
            "generators": {},
        }
    return grids


def _scan_contingencies_sync(grid_id: str) -> dict[str, object]:
    """Evaluate every line and generator outage using an isolated network copy."""
    if grid_id not in grids:
        return {"status": "unavailable", "lines": {}, "generators": {}}
    base_net = grids[grid_id].net

    def evaluate(candidate_net) -> dict[str, object]:
        try:
            pp.runpp(candidate_net, algorithm="nr")
        except pp.LoadflowNotConverged:
            return {"converged": False, "max_loading_percent": None, "secure": False}
        if candidate_net.res_line.empty:
            maximum_loading = 0.0
        else:
            maximum_loading = float(candidate_net.res_line["loading_percent"].max())
        if not math.isfinite(maximum_loading):
            return {"converged": False, "max_loading_percent": None, "secure": False}
        return {
            "converged": True,
            "max_loading_percent": round(maximum_loading, 2),
            "secure": maximum_loading <= 100.0,
        }

    line_results: dict[str, dict[str, object]] = {}
    for line_id in base_net.line.index:
        candidate = copy.deepcopy(base_net)
        candidate.line.at[line_id, "in_service"] = False
        line_results[str(int(line_id))] = evaluate(candidate)

    generator_results: dict[str, dict[str, object]] = {}
    for generator_id in base_net.gen.index:
        candidate = copy.deepcopy(base_net)
        candidate.gen.at[generator_id, "in_service"] = False
        generator_results[str(int(generator_id))] = evaluate(candidate)

    results = list(line_results.values()) + list(generator_results.values())
    insecure_count = sum(not bool(result["secure"]) for result in results)
    return {
        "status": "fresh",
        "lines": line_results,
        "generators": generator_results,
        "n_minus_1_secure": insecure_count == 0,
        "insecure_contingency_count": insecure_count,
        "last_scan_timestamp": time.time(),
    }


async def contingency_scanner_loop(grid_id: str, interval_seconds: int) -> None:
    """Refresh one grid's contingency cache without blocking HTTP handling."""
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be positive")
    while True:
        try:
            result = await asyncio.to_thread(_scan_contingencies_sync, grid_id)
            contingency_cache[grid_id] = result
        except asyncio.CancelledError:
            raise
        except Exception:
            contingency_cache[grid_id] = {
                "status": "error",
                "lines": {},
                "generators": {},
            }
        await asyncio.sleep(interval_seconds)


@app.get("/contingency/{grid}", tags=["grid"])
def get_contingency_status(grid: str) -> dict[str, object]:
    """Return cached N-1 results with explicit freshness and availability."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    cached = dict(contingency_cache.get(grid_id, {}))
    timestamp = cached.get("last_scan_timestamp")
    if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
        cached["status"] = "unavailable"
        cached["age_seconds"] = None
        return cached

    age = max(0.0, time.time() - float(timestamp))
    interval = runtime_settings().contingency_interval_seconds
    cache_status = str(cached.get("status", "unavailable"))
    if cache_status == "fresh" and age > interval * 2:
        cache_status = "stale"
    cached["status"] = cache_status
    cached["age_seconds"] = round(age, 2)
    return cached


def _json_safe(value):
    """Replace non-finite measurements recursively before WebSocket encoding."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _telemetry_snapshot(twin: TwinModel) -> dict[str, object]:
    """Build one self-consistent JSON-safe telemetry snapshot."""
    net = copy.deepcopy(twin.net)

    def records(frame, columns: tuple[str, ...]) -> list[dict[str, object]]:
        if frame is None:
            return []
        return [
            {"id": int(index), **{column: row.get(column) for column in columns if column in row}}
            for index, row in frame.iterrows()
        ]

    return _json_safe({
        "grid": twin.grid_type,
        "timestamp": time.time(),
        "lines": records(net.res_line, ("p_from_mw", "p_to_mw", "i_from_ka", "i_to_ka", "loading_percent")),
        "buses": records(net.res_bus, ("vm_pu", "va_degree")),
        "loads": records(net.res_load, ("p_mw", "q_mvar")),
        "resilience": get_resilience_index(net),
    })


@app.websocket("/ws/telemetry/{grid}")
async def stream_telemetry(websocket: WebSocket, grid: str) -> None:
    """Stream one-second snapshots for an available grid."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError:
        await websocket.close(code=1008)
        return
    twin = grids.get(grid_id)
    if twin is None:
        await websocket.close(code=1013)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_telemetry_snapshot(twin))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate service settings at startup and retain them for dependencies."""
    settings = runtime_settings()
    app.state.settings = settings
    initialize_grids(settings)
    scanner_tasks = {
        grid_id: asyncio.create_task(
            contingency_scanner_loop(grid_id, settings.contingency_interval_seconds),
            name=f"contingency-scanner-{grid_id}",
        )
        for grid_id in grids
    }
    app.state.contingency_scanner_tasks = scanner_tasks
    try:
        yield
    finally:
        for task in scanner_tasks.values():
            task.cancel()
        await asyncio.gather(*scanner_tasks.values(), return_exceptions=True)
        app.state.contingency_scanner_tasks = {}
        grids.clear()


app.router.lifespan_context = lifespan


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


@app.post("/change_load/{bus_id}", tags=["actuation"])
def update_grid_load(
    bus_id: int,
    new_mw: float = Query(ge=0.0, allow_inf_nan=False),
    grid: str = "118",
) -> dict[str, str]:
    """Atomically update one load facility and record the successful action."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")

    twin = grids[grid_id]
    try:
        status = twin.change_load(bus_id, new_mw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if status != "COMPLETED":
        raise HTTPException(status_code=422, detail="Load change did not converge; live grid was preserved")

    log_event(
        "digital_twin",
        grid_id,
        "LOAD_CHANGE",
        {"bus_id": bus_id, "new_mw": new_mw},
    )
    return {
        "status": "Command Received",
        "action": f"Updated Facility {bus_id} to {new_mw}MW",
    }


@app.post("/inject_fault/{line_id}", tags=["actuation"])
def trigger_line_fault(line_id: int, grid: str = "39") -> dict[str, str]:
    """Trip one line atomically on the selected IEEE simulation."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")

    twin = grids[grid_id]
    try:
        status = twin.trip_line(line_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Line not found") from exc
    if status != "COMPLETED":
        raise HTTPException(status_code=422, detail="Line outage did not converge; live grid was preserved")
    log_event("digital_twin", grid_id, "FAULT_INJECTED", {"line_id": line_id})
    return {
        "status": "Command Received",
        "action": f"Tripped Line {line_id} on IEEE {grid_id}",
    }


@app.post("/restore_line/{grid}/{line_id}", tags=["actuation"])
def restore_line(grid: str, line_id: int) -> dict[str, str]:
    """Restore one line atomically on the requested IEEE simulation."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")

    twin = grids[grid_id]
    try:
        status = twin.restore_line(line_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Line not found") from exc
    if status != "COMPLETED":
        raise HTTPException(status_code=422, detail="Line restoration did not converge; live grid was preserved")
    log_event("digital_twin", grid_id, "LINE_RESTORED", {"line_id": line_id})
    return {
        "status": "Command Received",
        "action": f"Restored Line {line_id} on IEEE {grid_id}",
    }


@app.post("/redispatch_gen/{bus_id}", tags=["actuation"])
def redispatch_generator(
    bus_id: int,
    delta_mw: float = Query(allow_inf_nan=False),
    grid: str = "39",
) -> dict[str, str]:
    """Apply a bounded signed generator delta and commit only on convergence."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")

    twin = grids[grid_id]
    matching = twin.net.gen.index[
        (twin.net.gen["bus"] == bus_id) & twin.net.gen["in_service"]
    ]
    if matching.empty:
        raise HTTPException(status_code=404, detail="No in-service generator at bus")
    gen_id = matching[0]
    current_mw = float(twin.net.gen.at[gen_id, "p_mw"])
    minimum_mw = float(twin.net.gen.at[gen_id, "min_p_mw"])
    maximum_mw = float(twin.net.gen.at[gen_id, "max_p_mw"])
    requested_mw = current_mw + delta_mw
    if not all(math.isfinite(value) for value in (current_mw, minimum_mw, maximum_mw, requested_mw)):
        raise HTTPException(status_code=422, detail="Generator dispatch values must be finite")
    if requested_mw < minimum_mw or requested_mw > maximum_mw:
        raise HTTPException(status_code=422, detail="Generator dispatch exceeds physical limits")

    candidate_net = copy.deepcopy(twin.net)
    candidate_net.gen.at[gen_id, "p_mw"] = requested_mw
    event = f"Generator at Bus {bus_id} Redispatched by {delta_mw:g} MW"
    twin.current_scenario = event
    status = twin._solve_candidate(candidate_net, event)
    if status != "COMPLETED":
        raise HTTPException(status_code=422, detail="Redispatch did not converge; live grid was preserved")
    log_event(
        "digital_twin",
        grid_id,
        "GENERATOR_REDISPATCH",
        {"bus_id": bus_id, "delta_mw": delta_mw},
    )
    return {"status": "Command Received", "action": event}


@app.post("/redistribute_load/{grid}", tags=["actuation"])
def redistribute_load(
    grid: str,
    source_bus: int,
    destination_bus: int,
    mw_amount: float = Query(gt=0.0, allow_inf_nan=False),
) -> dict[str, str | float]:
    """Move active load between two facilities with conserved total demand."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")
    if source_bus == destination_bus:
        raise HTTPException(status_code=422, detail="Source and destination buses must differ")

    twin = grids[grid_id]
    source_matches = twin.net.load.index[twin.net.load["bus"] == source_bus]
    destination_matches = twin.net.load.index[twin.net.load["bus"] == destination_bus]
    if source_matches.empty or destination_matches.empty:
        raise HTTPException(status_code=422, detail="Both buses must have load facilities")

    source_id, destination_id = source_matches[0], destination_matches[0]
    source_mw = float(twin.net.load.at[source_id, "p_mw"])
    shifted_mw = min(float(mw_amount), source_mw)
    if shifted_mw <= 0.0:
        raise HTTPException(status_code=422, detail="Source bus has no load available to move")
    candidate_net = copy.deepcopy(twin.net)
    candidate_net.load.at[source_id, "p_mw"] = source_mw - shifted_mw
    candidate_net.load.at[destination_id, "p_mw"] += shifted_mw
    event = f"Redistributed {shifted_mw:.2f} MW: Bus {source_bus} to Bus {destination_bus}"
    twin.current_scenario = event
    status = twin._solve_candidate(candidate_net, event)
    if status != "COMPLETED":
        raise HTTPException(status_code=422, detail="Redistribution did not converge; live grid was preserved")
    log_event(
        "digital_twin",
        grid_id,
        "LOAD_REDISTRIBUTION",
        {
            "source_bus": source_bus,
            "destination_bus": destination_bus,
            "mw_amount": shifted_mw,
        },
    )
    return {
        "status": "Command Received",
        "action": event,
        "mw_amount": shifted_mw,
    }


@app.post("/stress_test/{grid}", tags=["actuation"])
def apply_stress_test(grid: str, request: StressTestRequest) -> dict[str, object]:
    """Set absolute load and line-rating multipliers and report modeled collapse."""
    try:
        grid_id = validate_grid_id(grid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Grid not found") from exc
    if grid_id not in grids:
        raise HTTPException(status_code=503, detail="Grid simulator is unavailable")

    twin = grids[grid_id]
    status = twin.apply_stress_test(request.load_multiplier, request.derate_multiplier)
    log_event(
        "digital_twin",
        grid_id,
        "STRESS_TEST_APPLIED",
        {
            "load_multiplier": request.load_multiplier,
            "derate_multiplier": request.derate_multiplier,
            "simulation_status": status,
        },
    )
    if status != "COMPLETED":
        raise HTTPException(
            status_code=422,
            detail="Grid collapsed (power flow did not converge) at this stress level.",
        )
    return {
        "status": "Stress Test Applied",
        "load_multiplier": request.load_multiplier,
        "derate_multiplier": request.derate_multiplier,
        "grid_resilience_index": twin.current_state.get("grid_resilience_index"),
    }
