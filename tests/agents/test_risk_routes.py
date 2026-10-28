"""Capacity and horizon based risk routing for the AI agent."""

import pytest

from modules.ai_agents.agent_core import GridState, risk_assessment_node


def state(*, situation=None, bounds=None, capacity=100.0):
    return GridState(
        capacity_max=capacity,
        current_situation=situation or {"available": True, "resilience": {}, "security": {}},
        forecast_bounds=bounds or {"p90_1h": 50.0},
    )


@pytest.mark.parametrize(
    "situation,expected",
    [
        ({"available": False}, "UNKNOWN"),
        ({"available": True, "resilience": {"collapsed": True}}, "CRITICAL"),
        ({"available": True, "security": {"collapsed": True}}, "CRITICAL"),
        ({"available": True, "security": {"overloaded_line_count": 1}}, "HIGH"),
    ],
)
def test_live_conditions_override_forecast(situation, expected):
    assert risk_assessment_node(state(situation=situation))["risk_level"] == expected


@pytest.mark.parametrize(
    "bounds,expected",
    [
        ({"p90_1h": 98.0}, "HIGH"),
        ({"p90_1h": 88.2}, "MEDIUM"),
        ({"p90_1h": 50.0, "p90_6h": 98.0}, "MEDIUM"),
        ({"p90_1h": 50.0, "p90_24h": 98.0}, "WATCH"),
        ({"p90_1h": 50.0}, "LOW"),
        ({"p90_1h": 98.0, "p90_6h": None, "p90_24h": None}, "HIGH"),
        ({"p90_1h": None, "p90_6h": 98.0}, "UNKNOWN"),
    ],
)
def test_forecast_horizon_routing(bounds, expected):
    assert risk_assessment_node(state(bounds=bounds))["risk_level"] == expected


def test_capacity_threshold_scales_with_live_grid_capacity():
    assert risk_assessment_node(state(capacity=200.0, bounds={"p90_1h": 196.0}))["risk_level"] == "HIGH"
