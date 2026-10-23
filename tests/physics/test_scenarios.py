"""Deterministic tests for scenario transformations and asset degradation."""

from __future__ import annotations

import copy
from unittest.mock import patch

import pandapower as pp
import pandapower.networks as networks
import pytest

from modules.physics_engine.scenario_engine import (
    apply_load_multiplier,
    derate_lines,
    ramp_down_renewables,
    simulate_breaker_degradation,
    simulate_generator_trip,
    simulate_generator_wear,
    simulate_relay_degradation,
    simulate_transformer_aging,
    simulate_weather_event,
)
from modules.physics_engine.twin_model import TwinModel


def tiny_net():
    net = pp.create_empty_network()
    bus = pp.create_bus(net, vn_kv=110.0)
    pp.create_load(net, bus, p_mw=10.0, q_mvar=4.0)
    return net


def test_load_scaling_mutates_only_the_selected_copy() -> None:
    base = tiny_net()
    doubled = copy.deepcopy(base)
    halved = copy.deepcopy(base)

    assert apply_load_multiplier(doubled, 2.0) is doubled
    assert apply_load_multiplier(halved, 0.5) is halved
    assert list(doubled.load["p_mw"]) == [20.0]
    assert list(doubled.load["q_mvar"]) == [8.0]
    assert list(halved.load["p_mw"]) == [5.0]
    assert list(halved.load["q_mvar"]) == [2.0]
    assert list(base.load["p_mw"]) == [10.0]
    assert list(base.load["q_mvar"]) == [4.0]


def test_line_derating_preserves_baseline_and_rejects_nonpositive_factor() -> None:
    net = networks.case39()
    baseline = net.line["max_i_ka"].copy()
    assert derate_lines(net, 0.5) is net
    assert net.line["max_i_ka"].equals(baseline * 0.5)

    current = net.line["max_i_ka"].copy()
    with pytest.raises(ValueError):
        derate_lines(net, 0.0)
    assert net.line["max_i_ka"].equals(current)


def test_transformer_aging_thresholds_and_rul_floor() -> None:
    registry = {"transformers": {1: {"dga_score": 49.0, "rul_days": 1.0, "fault_class": "NORMAL"}}}
    with patch("modules.physics_engine.scenario_engine.random.uniform", side_effect=[2.0, 3.0]):
        simulate_transformer_aging(registry, 1)
    assert registry["transformers"][1] == {
        "dga_score": 51.0,
        "rul_days": 0.0,
        "fault_class": "THERMAL_FAULT",
    }


def test_generator_wear_threshold_and_rul_floor() -> None:
    registry = {"generators": {2: {"vibration_amp": 7.2, "rul_days": 1.0, "fault_class": "NORMAL"}}}
    with patch("modules.physics_engine.scenario_engine.random.uniform", side_effect=[0.5, 2.5]):
        simulate_generator_wear(registry, 2)
    assert registry["generators"][2] == {
        "vibration_amp": 7.7,
        "rul_days": 0.0,
        "fault_class": "CRITICAL_UNBALANCE",
    }


def test_breaker_and_relay_fault_thresholds() -> None:
    registry = {
        "circuit_breakers": {3: {"tccs_delay_ms": 49.5, "rul_days": 1.0, "fault_class": "NORMAL"}},
        "relays": {4: {"logic_integrity": 50.25, "fault_class": "NORMAL"}},
    }
    with patch("modules.physics_engine.scenario_engine.random.uniform", side_effect=[1.0, 2.0]):
        simulate_breaker_degradation(registry, 3)
    with patch("modules.physics_engine.scenario_engine.random.uniform", return_value=0.5):
        simulate_relay_degradation(registry, 4)
    assert registry["circuit_breakers"][3]["fault_class"] == "MECHANICAL_JAM"
    assert registry["circuit_breakers"][3]["rul_days"] == 0.0
    assert registry["relays"][4] == {
        "logic_integrity": 49.75,
        "fault_class": "CRITICAL_LOGIC_FAILURE",
    }


def test_generator_trip_updates_asset_and_rejects_unknown_index() -> None:
    net = pp.create_empty_network()
    bus = pp.create_bus(net, vn_kv=110.0)
    generator_id = pp.create_gen(net, bus, p_mw=10.0, vm_pu=1.0)
    registry = {"generators": {generator_id: {"fault_class": "NORMAL", "rul_days": 100.0}}}

    returned_net, returned_registry = simulate_generator_trip(net, registry, generator_id, "TEST_TRIP")
    assert returned_net is net and returned_registry is registry
    assert not bool(net.gen.at[generator_id, "in_service"])
    assert registry["generators"][generator_id] == {"fault_class": "TEST_TRIP", "rul_days": 0.0}
    with pytest.raises(ValueError):
        simulate_generator_trip(net, registry, 9999)


def test_weather_event_branches_and_unknown_event() -> None:
    heat = TwinModel("39")
    heat_baseline = heat.net.line["max_i_ka"].copy()
    with patch("modules.physics_engine.scenario_engine.random.uniform", return_value=1.0):
        simulate_weather_event(heat.net, heat.asset_registry, "HEATWAVE", 1.0)
    assert heat.net.line["max_i_ka"].equals(heat_baseline * 0.9)
    assert all(asset["dga_score"] > 0 for asset in heat.asset_registry["transformers"].values())

    storm = TwinModel("39")
    storm_baseline = storm.net.line["max_i_ka"].copy()
    with patch("modules.physics_engine.scenario_engine.random.uniform", return_value=1.0):
        simulate_weather_event(storm.net, storm.asset_registry, "STORM", 1.0)
    assert storm.net.line["max_i_ka"].equals(storm_baseline * 0.75)
    assert all(asset["tccs_delay_ms"] > 0 for asset in storm.asset_registry["circuit_breakers"].values())

    cold = TwinModel("39")
    load_p = cold.net.load["p_mw"].copy()
    load_q = cold.net.load["q_mvar"].copy()
    simulate_weather_event(cold.net, cold.asset_registry, "COLD_SNAP", 1.0)
    assert cold.net.load["p_mw"].equals(load_p * 1.2)
    assert cold.net.load["q_mvar"].equals(load_q * 1.2)
    with pytest.raises(ValueError):
        simulate_weather_event(cold.net, cold.asset_registry, "UNKNOWN", 1.0)


@pytest.mark.parametrize(("percent", "factor"), [(0, 1.0), (50, 0.5), (100, 0.0)])
def test_renewable_ramp_percent(percent: int, factor: float) -> None:
    net = networks.case39()
    ids = list(net.gen.index)
    selected = ids[:2]
    untouched = ids[2]
    baseline = net.gen["p_mw"].copy()

    ramp_down_renewables(net, percent, selected)

    assert net.gen.loc[selected, "p_mw"].equals(baseline.loc[selected] * factor)
    assert net.gen.at[untouched, "p_mw"] == baseline.at[untouched]


def test_renewable_ramp_rejects_invalid_percentage_and_selection_without_mutation() -> None:
    net = networks.case39()
    baseline = net.gen["p_mw"].copy()
    for percent in (-1, 101, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ramp_down_renewables(net, percent)
        assert net.gen["p_mw"].equals(baseline)
    with pytest.raises(ValueError):
        ramp_down_renewables(net, 50, [999999])
    assert net.gen["p_mw"].equals(baseline)
