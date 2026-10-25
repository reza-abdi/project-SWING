"""Regression tests for the digital-twin network and timeline behavior."""

import copy

import pytest

from modules.physics_engine.twin_model import TwinModel


@pytest.mark.parametrize("grid_type", ["39", "118"])
def test_baseline_simulation_converges_for_supported_grids(grid_type: str) -> None:
    model = TwinModel(grid_type)

    summary = model.run_baseline_simulation()

    assert summary["grid_type"] == grid_type
    assert summary["simulation_status"] == "COMPLETED"
    assert summary["time_step"] == 1
    assert summary["collapsed"] is False
    assert summary["grid_resilience_index"] > 0.0
    assert model.net.converged


def test_update_state_keeps_independent_timeline_snapshots() -> None:
    model = TwinModel("39")
    first_state = model.run_baseline_simulation()
    first_snapshot = copy.deepcopy(model.state_history[1])

    updated = model.update_state(
        {"grid_type": "39", "measurements": {"load_mw": 10.0}},
        "COMPLETED",
        "Manual Timeline Update",
    )
    updated["measurements"]["load_mw"] = 99.0

    assert model.time_step == 2
    assert model.previous_state == first_snapshot
    assert model.state_history[1] == first_snapshot
    assert model.state_history[2]["measurements"]["load_mw"] == 10.0
    assert first_state["last_event"] == "Baseline Simulation Completed"


def test_line_fault_can_be_restored_and_unknown_lines_are_rejected() -> None:
    model = TwinModel("39")
    model.run_baseline_simulation()
    line_id = int(model.net.line.index[0])

    assert model.trip_line(line_id) == "COMPLETED"
    assert not bool(model.net.line.at[line_id, "in_service"])
    assert model.restore_line(line_id) == "COMPLETED"
    assert bool(model.net.line.at[line_id, "in_service"])

    with pytest.raises(ValueError, match="not found"):
        model.trip_line(-1)
    with pytest.raises(ValueError, match="not found"):
        model.restore_line(-1)


def test_per_bus_load_change_targets_load_and_rejects_invalid_inputs() -> None:
    model = TwinModel("39")
    model.run_baseline_simulation()
    load_id = model.net.load.index[0]
    bus_id = int(model.net.load.at[load_id, "bus"])
    other_loads = model.net.load.drop(index=load_id)["p_mw"].copy()

    assert model.change_load(bus_id, 123.0) == "COMPLETED"
    assert model.net.load.at[load_id, "p_mw"] == 123.0
    assert model.net.load.drop(index=load_id)["p_mw"].equals(other_loads)

    junction_bus = next(
        index for index in model.net.bus.index if index not in model.net.load["bus"].values
    )
    with pytest.raises(ValueError, match="does not have a load"):
        model.change_load(int(junction_bus), 10.0)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        model.change_load(bus_id, float("nan"))
    with pytest.raises(ValueError, match="finite and nonnegative"):
        model.change_load(bus_id, -1.0)


def test_stress_settings_are_absolute_and_idempotent() -> None:
    model = TwinModel("39")
    baseline_p = model.baseline_load_p_mw.copy()
    baseline_q = model.baseline_load_q_mvar.copy()
    baseline_current = model.baseline_max_i_ka.copy()

    for _ in range(2):
        assert model.apply_stress_test(1.05, 0.8) == "COMPLETED"
        assert model.net.load["p_mw"].equals(baseline_p * 1.05)
        assert model.net.load["q_mvar"].equals(baseline_q * 1.05)
        assert model.net.line["max_i_ka"].equals(baseline_current * 0.8)


def test_grid_instances_keep_independent_networks_and_timelines() -> None:
    case39 = TwinModel("39")
    case118 = TwinModel("118")
    case39.run_baseline_simulation()
    case118.run_baseline_simulation()
    untouched_case118_load = case118.net.load["p_mw"].copy()

    assert case39.apply_stress_test(1.05, 0.9) == "COMPLETED"

    assert case39.net is not case118.net
    assert case39.time_step == 2
    assert case118.time_step == 1
    assert case118.net.load["p_mw"].equals(untouched_case118_load)
