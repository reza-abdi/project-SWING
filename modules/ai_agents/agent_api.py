"""Independent HTTP service for AI-assisted, human-approved grid proposals."""

import asyncio
from ipaddress import ip_address
import math
import math

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.ai_agents.agent_core import GridState, build_agent_graph
from modules.ai_agents.twin_client import TwinClient
from modules.ai_agents.llm_client import generate_with_fallback
from modules.ai_agents.twin_client import validate_operator_forecast_features
from modules.ai_agents import proposal_store
from modules.event_store import get_events, log_event
from modules.config import runtime_settings


class ProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telemetry: dict[str, object] = Field(default_factory=dict)
    capacity_max_mw: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @field_validator("telemetry")
    @classmethod
    def validate_telemetry(cls, value: dict[str, object]) -> dict[str, object]:
        if value:
            validate_operator_forecast_features(value)
        return dict(value)

    @model_validator(mode="after")
    def validate_capacity(self) -> "ProposeRequest":
        if self.capacity_max_mw is not None and (not math.isfinite(self.capacity_max_mw) or self.capacity_max_mw <= 0):
            raise ValueError("capacity_max_mw must be finite and positive")
        return self


app = FastAPI(title="Project SWING Decision Support", version="1.0.0")


__all__ = ["app", "GridState", "TwinClient", "build_agent_graph"]


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "Project SWING Decision Support", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Return only service and read-only Twin availability, never configuration."""
    try:
        await asyncio.wait_for(asyncio.to_thread(TwinClient().grid_status, "118"), timeout=2.0)
        twin_status = "available"
    except asyncio.TimeoutError:
        twin_status = "timeout"
    except Exception:
        twin_status = "unavailable"
    return {"status": "ok", "twin": twin_status}


def _default_graph_runner(grid: str, payload: dict) -> dict:
    """Run the isolated proposal graph with lazy, fail-closed model integrations."""
    from modules.ai_agents.agent_core import (
        ProposedAction, agent_unavailable_node, build_decision_prompt,
        lightgbm_fallback_node, operator_approval_brief, parse_decision_response,
        tft_forecasting_node,
    )

    def sensor(state):
        prediction = tft_forecasting_node(state)
        interim = state.model_copy(update=prediction)
        fallback = lightgbm_fallback_node(interim)
        return {**prediction, **fallback}

    def decide(state):
        try:
            text = generate_with_fallback(build_decision_prompt(state))
            bus_ids = {int(bus) for bus in state.current_situation.get("bus_loads", {}) if str(bus).isdigit()}
            action = parse_decision_response(text, valid_bus_ids=bus_ids)
            return {"proposed_action": action}
        except Exception as exc:
            return agent_unavailable_node(exc)

    graph = build_agent_graph(
        sensor_node=sensor,
        decision_node=decide,
        twin_client=TwinClient(),
    )
    result = graph.invoke(GridState(
        grid_id=grid,
        telemetry=dict(payload.get("telemetry", {})),
        telemetry_source="operator" if payload.get("telemetry") else "unavailable",
        capacity_max=float(payload["capacity_max_mw"]) if payload.get("capacity_max_mw") is not None else 0.0,
    ))
    state = result if isinstance(result, GridState) else GridState.model_validate(result)
    if state.validation_result.valid:
        brief = operator_approval_brief(state)
        state = state.model_copy(update=brief)
    else:
        from modules.ai_agents.agent_core import agent_failure_brief
        state = state.model_copy(update=agent_failure_brief(state))
    return {
        "decision": state.decision,
        "operator_brief": state.operator_brief,
        "proposed_action": state.proposed_action.model_dump(mode="json"),
        "validation": state.validation_result.as_response(),
        "feature_importance": state.feature_importance,
        "forecast": {
            "source": state.forecast_source,
            "input_source": state.forecast_input_source,
            "bounds": state.forecast_bounds,
            "risk_level": state.risk_level,
        },
        "snapshot": {
            "capacity_max_mw": state.capacity_max,
            "situation": state.current_situation,
            "forecast_bounds": state.forecast_bounds,
            "topology": TwinClient().topology(grid),
        },
    }


_graph_runner = _default_graph_runner


def configure_graph_runner(runner) -> None:
    """Inject a deterministic graph runner for tests and controlled deployments."""
    global _graph_runner
    _graph_runner = runner


def _proposal_is_fresh(proposal: dict, twin: TwinClient) -> dict | None:
    """Recheck physical state and run read-only validation before an approval can execute."""
    try:
        status = twin.grid_status(proposal["grid_id"])
        topology = twin.topology(proposal["grid_id"])
        snapshot = proposal["snapshot"]
        original = snapshot.get("situation", {})
        observed = {
            "available": True,
            "capacity_max_mw": float(status["capacity_max_mw"]),
            "resilience": status["resilience"],
            "security": status["security"],
            "bus_loads": status["bus_loads"],
        }
        if snapshot.get("capacity_max_mw") != float(status["capacity_max_mw"]):
            return False
        if original != observed or snapshot.get("topology") != topology:
            return False
        action = proposal["action"]
        validated = twin.validate(proposal["grid_id"], {
            key: action[key] for key in ("action_type", "target_bus", "secondary_bus", "mw_amount")
            if key in action
        })
        return status if validated.get("valid") is True else None
    except Exception:
        return None


@app.post("/propose/{grid}")
async def propose(grid: str, payload: ProposeRequest) -> dict:
    if grid not in {"39", "118"}:
        raise HTTPException(status_code=404, detail="Grid not found")
    try:
        result = await asyncio.to_thread(_graph_runner, grid, payload.model_dump())
        if result.get("decision") == "PENDING_OPERATOR_APPROVAL" and result.get("validation", {}).get("valid"):
            metadata = proposal_store.create_pending(
                grid,
                result.get("snapshot", {}),
                result["proposed_action"],
                creator="local",
                ttl_seconds=runtime_settings().proposal_ttl_seconds,
            )
            result["proposal_id"] = metadata["proposal_id"]
            result["expires_at"] = metadata["expires_at"]
        result.pop("snapshot", None)
        return result
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid proposal input") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Decision support is unavailable") from exc


@app.post("/reject/{grid}/{proposal_id}")
async def reject_proposal(grid: str, proposal_id: str) -> dict[str, str]:
    if grid not in {"39", "118"}:
        raise HTTPException(status_code=404, detail="Grid not found")
    proposal = proposal_store.get_proposal(proposal_id)
    if proposal is None or proposal["grid_id"] != grid:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if not proposal_store.transition(proposal_id, "pending", "rejected"):
        raise HTTPException(status_code=409, detail="Proposal is no longer pending")
    log_event("ai", grid, "PROPOSAL_REJECTED", {"proposal_id": proposal_id})
    return {"proposal_id": proposal_id, "status": "rejected"}


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=36, max_length=36)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"user", "assistant"}:
            raise ValueError("history roles must be user or assistant")
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value

    @field_validator("history")
    @classmethod
    def trim_history(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        return value[-10:]


def _require_local_operator() -> None:
    """Permit writes only on loopback until verified remote identity is implemented."""
    host = runtime_settings().agent_bind_host
    try:
        loopback = host.lower() == "localhost" or ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise HTTPException(status_code=503, detail="Verified operator identity is required for remote execution")


def _execute_action(twin: TwinClient, grid: str, action: dict, fresh_status: dict) -> dict:
    """Map each approved action to its one exact Twin actuation route."""
    amount = action.get("mw_amount")
    bus = action.get("target_bus")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(float(amount)) or amount <= 0:
        raise ValueError("approved action must have positive finite MW")
    if isinstance(bus, bool) or not isinstance(bus, int):
        raise ValueError("approved action must have an integer target bus")
    action_type = action.get("action_type")
    if action_type == "SHED_LOAD":
        current_load = fresh_status.get("bus_loads", {}).get(str(bus))
        if isinstance(current_load, bool) or not isinstance(current_load, (int, float)) or not math.isfinite(float(current_load)):
            raise ValueError("fresh load at target bus is unavailable")
        return twin.change_load(grid, bus, max(0.0, float(current_load) - float(amount)))
    if action_type == "REDISPATCH_GEN":
        return twin.redispatch_gen(grid, bus, float(amount))
    if action_type == "LOAD_REDISTRIBUTION":
        secondary = action.get("secondary_bus")
        if isinstance(secondary, bool) or not isinstance(secondary, int) or secondary == bus:
            raise ValueError("redistribution requires a distinct integer destination bus")
        return twin.redistribute_load(grid, bus, secondary, float(amount))
    raise ValueError("Only validated active actions can be executed")


@app.post("/execute/{grid}")
async def execute_proposal(grid: str, request: ExecuteRequest, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128)) -> dict:
    if grid not in {"39", "118"}:
        raise HTTPException(status_code=404, detail="Grid not found")
    _require_local_operator()
    proposal = proposal_store.get_proposal(request.proposal_id)
    if proposal is None or proposal["grid_id"] != grid:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal["status"] == "executed" and proposal.get("idempotency_key") == idempotency_key:
        return {
            "proposal_id": request.proposal_id,
            "status": "executed",
            "result": proposal.get("execution_result"),
            "replayed": True,
        }
    if proposal["status"] != "pending":
        raise HTTPException(status_code=409, detail="Proposal is no longer pending")
    twin = TwinClient()
    fresh_status = await asyncio.to_thread(_proposal_is_fresh, proposal, twin)
    if fresh_status is None:
        proposal_store.transition(request.proposal_id, "pending", "stale")
        log_event("ai", grid, "PROPOSAL_STALE", {"proposal_id": request.proposal_id})
        raise HTTPException(status_code=409, detail="Grid state changed or validation failed; generate a new proposal")
    if not proposal_store.transition(request.proposal_id, "pending", "executing", idempotency_key=idempotency_key):
        raise HTTPException(status_code=409, detail="Proposal has already been handled")
    action = proposal["action"]
    try:
        result = await asyncio.to_thread(_execute_action, twin, grid, action, fresh_status)
    except Exception as exc:
        proposal_store.transition(request.proposal_id, "executing", "stale")
        log_event("ai", grid, "PROPOSAL_EXECUTION_FAILED", {"proposal_id": request.proposal_id, "error": type(exc).__name__})
        raise HTTPException(status_code=502, detail="Twin action failed; proposal is consumed") from exc
    if not proposal_store.complete_execution(request.proposal_id, result):
        raise HTTPException(status_code=409, detail="Action was sent but proposal state could not be finalized")
    log_event("ai", grid, "PROPOSAL_EXECUTED", {"proposal_id": request.proposal_id, "action": action})
    return {"proposal_id": request.proposal_id, "status": "executed", "result": result, "replayed": False}


@app.get("/events/{grid}")
async def events(grid: str, source: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    if grid not in {"39", "118"}:
        raise HTTPException(status_code=404, detail="Grid not found")
    if source is not None and (not source.strip() or len(source) > 64):
        raise HTTPException(status_code=422, detail="Invalid event source filter")
    return {"grid_id": grid, "events": await asyncio.to_thread(get_events, grid, source, limit)}
