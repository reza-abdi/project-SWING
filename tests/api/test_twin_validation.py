"""API coverage for non-mutating corrective-action validation."""

import copy

from fastapi.testclient import TestClient

import modules.physics_engine.api as twin_api


def test_all_supported_action_types_validate_without_mutating_live_grid() -> None:
    with TestClient(twin_api.app) as client:
        net = twin_api.grids["39"].net
        original_loads = net.load.copy(deep=True)
        original_generators = net.gen.copy(deep=True)
        load_buses = list(dict.fromkeys(int(bus) for bus in net.load["bus"]))
        gen_bus = int(net.gen.iloc[0]["bus"])
        actions = [
            {"action_type": "SHED_LOAD", "target_bus": load_buses[0], "mw_amount": 2.0},
            {"action_type": "REDISPATCH_GEN", "target_bus": gen_bus, "mw_amount": 2.0},
            {
                "action_type": "LOAD_REDISTRIBUTION",
                "target_bus": load_buses[0],
                "secondary_bus": load_buses[1],
                "mw_amount": 2.0,
            },
        ]

        for action in actions:
            response = client.post("/validate_action/39", json=action)
            assert response.status_code == 200, response.text
            assert "valid" in response.json()
            assert "gri_improvement" in response.json()

        assert net.load.equals(original_loads)
        assert net.gen.equals(original_generators)


def test_invalid_grid_schema_and_action_target_are_rejected() -> None:
    with TestClient(twin_api.app) as client:
        valid_payload = {"action_type": "SHED_LOAD", "target_bus": 0, "mw_amount": 1.0}
        assert client.post("/validate_action/invalid", json=valid_payload).status_code == 404
        assert client.post(
            "/validate_action/39",
            json={"action_type": "UNKNOWN", "target_bus": 0, "mw_amount": 1.0},
        ).status_code == 422
        assert client.post(
            "/validate_action/39",
            json={
                "action_type": "LOAD_REDISTRIBUTION",
                "target_bus": 2,
                "secondary_bus": 2,
                "mw_amount": 1.0,
            },
        ).status_code == 422

        junction = next(
            int(bus)
            for bus in twin_api.grids["39"].net.bus.index
            if bus not in set(twin_api.grids["39"].net.load["bus"])
        )
        result = client.post(
            "/validate_action/39",
            json={"action_type": "SHED_LOAD", "target_bus": junction, "mw_amount": 1.0},
        ).json()
        assert result["valid"] is False
        assert result["gri_after"] is None


def test_secure_insecure_and_nonconvergent_results(monkeypatch) -> None:
    with TestClient(twin_api.app) as client:
        base_net = twin_api.grids["39"].net
        action = {"action_type": "SHED_LOAD", "target_bus": int(base_net.load.iloc[0]["bus"]), "mw_amount": 1.0}

        monkeypatch.setattr(
            twin_api,
            "_evaluate_action",
            lambda *args: (True, 99.0, copy.deepcopy(base_net)),
        )
        secure = client.post("/validate_action/39", json=action).json()
        assert secure["valid"] is True
        assert secure["resulting_max_loading_percent"] == 99.0

        monkeypatch.setattr(
            twin_api,
            "_evaluate_action",
            lambda *args: (True, 120.0, copy.deepcopy(base_net)),
        )
        insecure = client.post("/validate_action/39", json=action).json()
        assert insecure["valid"] is False
        assert insecure["error"] is not None

        monkeypatch.setattr(twin_api, "_evaluate_action", lambda *args: (False, None, None))
        failed = client.post("/validate_action/39", json=action).json()
        assert failed["valid"] is False
        assert failed["resulting_max_loading_percent"] is None
        assert "did not converge" in failed["error"]
