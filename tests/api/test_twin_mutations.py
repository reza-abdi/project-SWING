"""Regression tests for Twin mutation validation, rollback, and event audit."""

import copy

import pandapower as pp
import pytest
from fastapi.testclient import TestClient

import modules.physics_engine.api as twin_api


@pytest.fixture
def client():
    with TestClient(twin_api.app) as test_client:
        yield test_client


def test_write_routes_mutate_only_requested_grid_and_emit_events(client, monkeypatch) -> None:
    audits = []
    monkeypatch.setattr(twin_api, "log_event", lambda *args: audits.append(args))
    twin39 = twin_api.grids["39"]
    load_id = twin39.net.load.index[0]
    load_bus = int(twin39.net.load.at[load_id, "bus"])
    current_load = float(twin39.net.load.at[load_id, "p_mw"])

    assert client.post(
        f"/change_load/{load_bus}", params={"new_mw": current_load + 1.0, "grid": "39"}
    ).status_code == 200
    line_id = int(twin39.net.line.index[0])
    assert client.post(f"/inject_fault/{line_id}", params={"grid": "39"}).status_code == 200
    assert client.post(f"/restore_line/39/{line_id}").status_code == 200

    gen = twin39.net.gen.iloc[0]
    assert client.post(
        f"/redispatch_gen/{int(gen.bus)}", params={"delta_mw": 1.0, "grid": "39"}
    ).status_code == 200
    load_buses = list(dict.fromkeys(int(bus) for bus in twin39.net.load["bus"]))
    assert client.post(
        "/redistribute_load/39",
        params={"source_bus": load_buses[0], "destination_bus": load_buses[1], "mw_amount": 1.0},
    ).status_code == 200
    assert client.post(
        "/stress_test/118", json={"load_multiplier": 1.0, "derate_multiplier": 0.9}
    ).status_code == 200

    assert {event[2] for event in audits} == {
        "LOAD_CHANGE",
        "FAULT_INJECTED",
        "LINE_RESTORED",
        "GENERATOR_REDISPATCH",
        "LOAD_REDISTRIBUTION",
        "STRESS_TEST_APPLIED",
    }
    assert twin_api.grids["118"].time_step == 2


def test_mutation_routes_reject_invalid_grids_and_parameters(client) -> None:
    assert client.post("/change_load/0", params={"new_mw": 1, "grid": "bad"}).status_code == 404
    assert client.post("/change_load/0", params={"new_mw": -1, "grid": "39"}).status_code == 422
    assert client.post("/inject_fault/-1", params={"grid": "39"}).status_code == 404
    assert client.post("/restore_line/bad/0").status_code == 404
    assert client.post("/redispatch_gen/999", params={"delta_mw": 1, "grid": "39"}).status_code == 404
    assert client.post("/redistribute_load/39", params={"source_bus": 0, "destination_bus": 0, "mw_amount": 1}).status_code == 422
    assert client.post("/stress_test/39", json={"load_multiplier": 0, "derate_multiplier": 1}).status_code == 422


def test_failed_mutation_solves_roll_back_each_live_grid(client, monkeypatch) -> None:
    twin = twin_api.grids["39"]
    original_net = copy.deepcopy(twin.net)
    source, destination = list(dict.fromkeys(int(bus) for bus in twin.net.load["bus"]))[:2]
    generator_bus = int(twin.net.gen.iloc[0]["bus"])
    line_id = int(twin.net.line.index[0])

    def fail_solve(*args, **kwargs):
        raise pp.LoadflowNotConverged("forced test failure")

    monkeypatch.setattr(twin_api.pp, "runpp", fail_solve)
    requests = [
        (f"/change_load/{source}", {"new_mw": 10, "grid": "39"}, None),
        (f"/inject_fault/{line_id}", {"grid": "39"}, None),
        (f"/redispatch_gen/{generator_bus}", {"delta_mw": 1, "grid": "39"}, None),
        ("/redistribute_load/39", {"source_bus": source, "destination_bus": destination, "mw_amount": 1}, None),
        ("/stress_test/39", None, {"load_multiplier": 1.05, "derate_multiplier": 0.95}),
    ]
    for path, params, body in requests:
        response = client.post(path, params=params, json=body)
        assert response.status_code == 422, response.text
        assert twin.net.load.equals(original_net.load)
        assert twin.net.gen.equals(original_net.gen)
        assert twin.net.line.equals(original_net.line)
        assert twin.net.res_bus.equals(original_net.res_bus)


def test_validation_and_optimization_never_implicitly_actuate(client, monkeypatch) -> None:
    twin = twin_api.grids["39"]
    original_net = copy.deepcopy(twin.net)
    monkeypatch.setattr(
        twin_api,
        "_smart_order_router",
        lambda net, request: {
            "feasible": False,
            "mw_amount": None,
            "action_type": request.action_type,
            "target_bus": request.target_bus,
            "secondary_bus": request.secondary_bus,
        },
    )
    bus = int(twin.net.load.iloc[0]["bus"])
    assert client.post(
        "/validate_action/39",
        json={"action_type": "SHED_LOAD", "target_bus": bus, "mw_amount": 1.0},
    ).status_code == 200
    assert client.post(
        "/optimize_action/39",
        json={"action_type": "SHED_LOAD", "target_bus": bus},
    ).status_code == 200
    assert twin.net.load.equals(original_net.load)
    assert twin.net.gen.equals(original_net.gen)
    assert twin.net.line.equals(original_net.line)
