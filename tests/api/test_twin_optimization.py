"""Regression tests for optimizer routing and numerical safety margins."""

import modules.physics_engine.api as twin_api
from modules.physics_engine.twin_model import TwinModel


def test_router_recalculates_ceiling_after_correcting_target(monkeypatch) -> None:
    net = TwinModel("39").net
    seen = []

    def fake_bisect(base_net, request, **kwargs):
        seen.append(request)
        if request.target_bus == 999:
            return {"feasible": False, "error": "invalid target"}
        return {"feasible": True, "mw_amount": 1.0, "resulting_max_loading_percent": 99.0}

    monkeypatch.setattr(twin_api, "_bisect_action", fake_bisect)
    request = twin_api.OptimizeRequest(
        action_type="SHED_LOAD",
        target_bus=999,
        search_ceiling_mw=500.0,
    )

    result = twin_api._smart_order_router(net, request)

    selected_bus = result["target_bus"]
    expected_ceiling = min(
        500.0,
        twin_api._physical_action_ceiling(net, "SHED_LOAD", selected_bus),
    )
    assert result["feasible"] is True
    assert selected_bus != 999
    assert seen[1].target_bus == selected_bus
    assert seen[1].search_ceiling_mw == expected_ceiling


def test_redistribution_router_can_downgrade_to_load_shedding(monkeypatch) -> None:
    net = TwinModel("39").net
    seen_actions = []

    def fake_bisect(base_net, request, **kwargs):
        seen_actions.append(request.action_type)
        if request.target_bus == 999:
            return {"feasible": False, "error": "invalid target"}
        if request.action_type == "SHED_LOAD":
            return {"feasible": True, "mw_amount": 2.0, "resulting_max_loading_percent": 98.0}
        return {"feasible": False, "error": "route not feasible"}

    monkeypatch.setattr(twin_api, "_bisect_action", fake_bisect)
    request = twin_api.OptimizeRequest(
        action_type="LOAD_REDISTRIBUTION",
        target_bus=999,
        secondary_bus=998,
        search_ceiling_mw=100.0,
    )

    result = twin_api._smart_order_router(net, request)

    assert result["feasible"] is True
    assert result["action_type"] == "SHED_LOAD"
    assert result["secondary_bus"] is None
    assert "LOAD_REDISTRIBUTION" in seen_actions
    assert "SHED_LOAD" in seen_actions


def test_bisection_enforces_full_security_boundary(monkeypatch) -> None:
    def threshold(net, action, bus, amount, secondary=None):
        return True, 100.01 - float(amount)

    monkeypatch.setattr(twin_api, "_test_action", threshold)
    request = twin_api.OptimizeRequest(
        action_type="SHED_LOAD",
        target_bus=1,
        search_ceiling_mw=1.0,
        tolerance_mw=0.0001,
    )

    result = twin_api._bisect_action(object(), request)

    assert result["feasible"] is True
    assert result["resulting_max_loading_percent"] <= 100.0
    assert 0.01 <= result["mw_amount"] <= 0.011
