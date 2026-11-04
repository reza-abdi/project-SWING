"""Failure behavior keeps candidate states isolated and stale data explicit."""

import copy
import time

import pandapower as pp
import pytest
from fastapi.testclient import TestClient

from modules.physics_engine import api as twin_api
from modules.physics_engine.twin_model import TwinModel


def test_collapsed_stress_candidate_preserves_live_network(monkeypatch):
    model = TwinModel("39")
    model.run_baseline_simulation()
    original_loads = model.net.load.copy(deep=True)
    monkeypatch.setattr(pp, "runpp", lambda *args, **kwargs: (_ for _ in ()).throw(pp.LoadflowNotConverged("forced")))
    result = model.apply_stress_test(1.1, 0.9)
    assert result == "FAILED"
    assert model.net.load.equals(original_loads)
    assert model.current_state["collapsed"] is True


def test_timeout_and_rescuer_exhaustion_are_fail_closed(monkeypatch):
    model = TwinModel("39")
    model.run_baseline_simulation()
    before = copy.deepcopy(model.net)
    def timeout(*_args, **_kwargs):
        raise TimeoutError("solver timed out")
    monkeypatch.setattr(model, "_solve_candidate", timeout)
    with pytest.raises(TimeoutError):
        model.change_load(int(model.net.load.iloc[0]["bus"]), 1.0)
    assert model.net.load.equals(before.load)

    monkeypatch.setattr(twin_api.pp, "runpp", lambda *args, **kwargs: (_ for _ in ()).throw(pp.LoadflowNotConverged("forced")))
    rescued, _, amount = twin_api._emergency_grid_rescue(before)
    assert rescued is False
    assert amount is None


def test_stale_contingency_and_nonmutating_validation(monkeypatch):
    with TestClient(twin_api.app) as client:
        twin = twin_api.grids["39"]
        original = twin.net.load.copy(deep=True)
        twin_api.contingency_cache["39"] = {
            "status": "fresh", "lines": {}, "generators": {}, "last_scan_timestamp": time.time() - 3600,
        }
        assert client.get("/contingency/39").json()["status"] == "stale"
        bus = int(twin.net.load.iloc[0]["bus"])
        monkeypatch.setattr(twin_api, "_evaluate_action", lambda *args: (False, None, None))
        response = client.post("/validate_action/39", json={
            "action_type": "SHED_LOAD", "target_bus": bus, "mw_amount": 1.0,
        })
        assert response.status_code == 200
        assert response.json()["valid"] is False
        assert twin.net.load.equals(original)
