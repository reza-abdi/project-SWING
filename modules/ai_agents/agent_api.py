"""Independent HTTP service for AI-assisted, human-approved grid proposals."""

import asyncio
import math

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.ai_agents.agent_core import GridState, build_agent_graph
from modules.ai_agents.twin_client import TwinClient
from modules.ai_agents.llm_client import generate_with_fallback
from modules.ai_agents.twin_client import validate_operator_forecast_features


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
    }


_graph_runner = _default_graph_runner


def configure_graph_runner(runner) -> None:
    """Inject a deterministic graph runner for tests and controlled deployments."""
    global _graph_runner
    _graph_runner = runner


@app.post("/propose/{grid}")
async def propose(grid: str, payload: ProposeRequest) -> dict:
    if grid not in {"39", "118"}:
        raise HTTPException(status_code=404, detail="Grid not found")
    try:
        return await asyncio.to_thread(_graph_runner, grid, payload.model_dump())
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid proposal input") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Decision support is unavailable") from exc
