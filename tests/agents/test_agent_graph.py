"""End-to-end graph routes use injected stubs and never require Gemini/network access."""

import pytest

from modules.ai_agents.agent_core import (
    GridState,
    ProposedAction,
    TwinClientError,
    agent_unavailable_node,
    build_agent_graph,
)


class TwinStub:
    def __init__(self, *, available=True, feasible=True):
        self.available = available
        self.feasible = feasible
        self.calls = []

    def grid_status(self, grid):
        self.calls.append("status")
        if not self.available:
            raise TwinClientError("offline")
        return {
            "capacity_max_mw": 100.0,
            "resilience": {"collapsed": False},
            "security": {"overloaded_line_count": 0},
            "bus_loads": {"1": 20.0},
        }

    def optimize(self, grid, payload):
        self.calls.append("optimize")
        return {"feasible": self.feasible, "mw_amount": 2.0, "method": "stub"}

    def validate(self, grid, payload):
        self.calls.append("validate")
        return {"valid": True, "gri_before": 1.0, "gri_after": 2.0, "gri_improvement": 1.0}


def graph_for(twin, *, risk_bounds=None, decision=None):
    def sensor(state):
        return {"forecast_bounds": risk_bounds or {"p90_1h": 50.0}}

    def decide(state):
        if decision:
            return decision(state)
        return {"proposed_action": ProposedAction(action_type="SHED_LOAD", target_bus=1, mw_amount=2, justification="test")}

    return build_agent_graph(sensor_node=sensor, decision_node=decide, twin_client=twin)


def test_low_and_watch_routes_skip_optimizer_and_validator():
    low_twin = TwinStub()
    low = graph_for(low_twin).invoke(GridState())
    assert low["decision"] == "MAINTAIN_BASELINE"
    assert low_twin.calls == ["status"]

    watch_twin = TwinStub()
    watch = graph_for(watch_twin, risk_bounds={"p90_1h": 50.0, "p90_24h": 98.0}).invoke(GridState())
    assert watch["decision"] == "MONITOR"
    assert watch_twin.calls == ["status"]


def test_high_risk_feasible_action_is_physics_validated():
    twin = TwinStub()
    result = graph_for(twin, risk_bounds={"p90_1h": 98.0}).invoke(GridState())
    assert result["validation_result"].valid is True
    assert twin.calls == ["status", "optimize", "validate"]


def test_optimizer_exhaustion_cannot_create_executable_action():
    twin = TwinStub(feasible=False)
    result = graph_for(twin, risk_bounds={"p90_1h": 98.0}).invoke(GridState())
    assert result["decision"] == "OPTIMIZATION_INFEASIBLE"
    assert result["proposed_action"].action_type == "NO_ACTION"
    assert twin.calls == ["status", "optimize"]


def test_model_quota_failure_has_no_action_and_twin_outage_is_detected():
    class QuotaError(Exception):
        response = type("Response", (), {"status_code": 429})()

    twin = TwinStub()
    result = graph_for(twin, risk_bounds={"p90_1h": 98.0}, decision=lambda state: agent_unavailable_node(QuotaError())).invoke(GridState())
    assert result["decision"] == "AGENT_UNAVAILABLE"
    assert result["proposed_action"].action_type == "NO_ACTION"
    assert twin.calls == ["status"]

    offline = TwinStub(available=False)
    result = graph_for(offline, risk_bounds={"p90_1h": 98.0}, decision=lambda state: {"proposed_action": ProposedAction()}).invoke(GridState())
    assert result["current_situation"]["available"] is False
    assert "optimize" not in offline.calls and "validate" not in offline.calls
