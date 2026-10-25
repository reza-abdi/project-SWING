"""Optional RL failures must continue into deterministic physics search."""

from types import SimpleNamespace

import pytest

import modules.physics_engine.api as twin_api
from modules.physics_engine.twin_model import TwinModel


@pytest.mark.parametrize("failure", ["missing", "corrupt", "physics"])
def test_optional_policy_failures_fall_back_to_physics_search(monkeypatch, failure) -> None:
    twin = TwinModel("39")
    monkeypatch.setitem(twin_api.grids, "39", twin)
    calls = []

    class StubOptimizer:
        def __init__(self, **kwargs):
            pass

        def load_model(self, action_type):
            if failure == "missing":
                return False
            if failure == "corrupt":
                raise ValueError("invalid artifact")

        def predict_mw(self, observation):
            return 1.0

    def fake_import(name):
        if name.endswith("rl_env"):
            return SimpleNamespace(build_observation_vector=lambda net, bus: [1.0])
        return SimpleNamespace(RLOptimizer=StubOptimizer)

    def physics_search(net, request):
        calls.append(request)
        return {"feasible": True, "action_type": request.action_type, "target_bus": request.target_bus, "mw_amount": 2.0}

    monkeypatch.setattr(twin_api, "import_module", fake_import)
    monkeypatch.setattr(twin_api, "_smart_order_router", physics_search)
    monkeypatch.setattr(twin_api, "_test_action", lambda *args: (False, 130.0))
    request = twin_api.OptimizeRequest(action_type="SHED_LOAD", target_bus=int(twin.net.load.iloc[0]["bus"]))

    result = twin_api.optimize_action("39", request)
    assert len(calls) == 1
    assert result["feasible"] is True
    assert result["mw_amount"] == 2.0
    assert result["method"] == "BISECTION"
    assert result["rl_fallback_reason"] is not None
