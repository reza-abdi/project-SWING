"""Regression coverage for pandapower topology and physics metrics."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pandapower as pp
import pandapower.networks as networks
import pandas as pd

from modules.physics_engine.grid_metrics import (
    get_electrical_metrics,
    get_observation_vector,
    get_resilience_index,
    get_security_metrics,
    get_topology_metrics,
)
from modules.physics_engine.twin_model import TwinModel


def metric_fixture(voltages: list[float], loadings: list[float], *, converged: bool = True):
    return SimpleNamespace(
        bus=pd.DataFrame(index=range(len(voltages))),
        line=pd.DataFrame(index=range(len(loadings))),
        res_bus=pd.DataFrame({"vm_pu": voltages}),
        res_line=pd.DataFrame({"loading_percent": loadings}),
        converged=converged,
    )


def test_topology_counts_match_ieee_case_fixtures() -> None:
    for case, factory in (("39", networks.case39), ("118", networks.case118)):
        assert get_topology_metrics(TwinModel(case).net) == get_topology_metrics(factory())


def test_electrical_metrics_after_newton_raphson() -> None:
    net = networks.case39()
    pp.runpp(net, algorithm="nr")

    metrics = get_electrical_metrics(net)

    assert set(metrics) == {
        "current_demand_mw",
        "total_generation_mw",
        "max_line_loading_percent",
        "min_voltage_pu",
        "max_volateg_pu",
    }
    assert all(math.isfinite(value) for value in metrics.values())
    assert metrics["current_demand_mw"] > 0
    assert metrics["total_generation_mw"] > 0


def test_security_metrics_clean_overloaded_and_collapsed_cases() -> None:
    clean = metric_fixture([1.0], [85.0, 100.0])
    assert get_security_metrics(clean) == {
        "overloaded_line_count": 0,
        "overloaded_line_ids": [],
        "collapsed": False,
    }

    overloaded = metric_fixture([1.0], [101.0, 130.0])
    assert get_security_metrics(overloaded) == {
        "overloaded_line_count": 2,
        "overloaded_line_ids": [0, 1],
        "collapsed": False,
    }

    collapsed = metric_fixture([float("nan")], [float("nan"), float("nan")], converged=False)
    assert get_security_metrics(collapsed) == {
        "overloaded_line_count": 2,
        "overloaded_line_ids": [0, 1],
        "collapsed": True,
    }


def test_observation_vector_order_normalization_and_nan_handling() -> None:
    net = metric_fixture([1.0, float("nan"), 0.98], [25.0, 150.0])

    vector = get_observation_vector(net)

    assert vector == [1.0, 0.0, 0.98, 0.25, 1.5]
    assert len(vector) == len(net.bus) + len(net.line)
    assert all(math.isfinite(value) for value in vector)


def test_resilience_nominal_and_boundary_scores() -> None:
    nominal = get_resilience_index(metric_fixture([1.0, 1.0], [75.0, 80.0]))
    assert nominal == {
        "grid_resilience_index": 100.0,
        "collapsed": False,
        "voltage_score": 100.0,
        "loading_score": 100.0,
        "security_score": 100.0,
    }

    boundary = get_resilience_index(metric_fixture([0.95, 1.05], [110.0, 130.0]))
    assert boundary == {
        "grid_resilience_index": 35.0,
        "collapsed": False,
        "voltage_score": 50.0,
        "loading_score": 0.0,
        "security_score": 70.0,
    }


def test_resilience_fails_closed_on_collapse_or_missing_measurements() -> None:
    expected = {
        "grid_resilience_index": 0.0,
        "collapsed": True,
        "voltage_score": 0.0,
        "loading_score": 0.0,
        "security_score": 0.0,
    }
    collapsed = metric_fixture([1.0, 1.0], [float("nan"), float("nan")], converged=False)
    partial = metric_fixture([1.0, 0.99], [75.0, float("nan")])

    assert get_resilience_index(collapsed) == expected
    assert get_resilience_index(partial) == expected
