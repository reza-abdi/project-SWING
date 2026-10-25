"""Regression coverage for failed candidate power-flow solves."""

import copy

import pandapower as pp

from modules.physics_engine.twin_model import TwinModel


def test_failed_line_trip_preserves_live_grid_and_reports_collapse(monkeypatch) -> None:
    model = TwinModel("39")
    assert model.run_baseline_simulation()["simulation_status"] == "COMPLETED"
    live_net = copy.deepcopy(model.net)
    live_assets = copy.deepcopy(model.asset_registry)
    line_id = int(model.net.line.index[0])

    def fail_solve(*args, **kwargs):
        raise pp.LoadflowNotConverged("forced test failure")

    monkeypatch.setattr(pp, "runpp", fail_solve)

    assert model.trip_line(line_id) == "FAILED"
    assert model.net.line.equals(live_net.line)
    assert model.net.res_bus.equals(live_net.res_bus)
    assert model.asset_registry == live_assets
    assert model.current_state["collapsed"] is True
    assert model.current_state["grid_resilience_index"] == 0.0
    assert "max_line_loading_percent" not in model.current_state
    assert model.current_state["last_event"] == f"Line {line_id} Tripped"


def test_failed_weather_event_preserves_asset_health(monkeypatch) -> None:
    model = TwinModel("39")
    model.run_baseline_simulation()
    live_net = copy.deepcopy(model.net)
    live_assets = copy.deepcopy(model.asset_registry)

    def fail_solve(*args, **kwargs):
        raise pp.LoadflowNotConverged("forced test failure")

    monkeypatch.setattr(pp, "runpp", fail_solve)

    assert model.apply_weather_event("HEATWAVE") == "FAILED"
    assert model.net.line.equals(live_net.line)
    assert model.net.res_line.equals(live_net.res_line)
    assert model.asset_registry == live_assets
    assert model.current_state["collapsed"] is True
