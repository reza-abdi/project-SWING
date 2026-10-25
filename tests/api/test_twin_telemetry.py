"""WebSocket telemetry serialization and connection lifecycle regressions."""

import math

from fastapi.testclient import TestClient
import pytest

import modules.physics_engine.api as twin_api


def test_telemetry_stream_emits_consistent_snapshot_and_disconnects(client, monkeypatch) -> None:
    snapshots = []

    def snapshot(twin):
        value = {
            "grid": twin.grid_type,
            "lines": [{"id": 0, "loading_percent": float("nan")}],
            "buses": [{"id": 0, "vm_pu": 1.0}],
            "loads": [],
            "resilience": {"grid_resilience_index": float("inf")},
        }
        snapshots.append(value)
        return twin_api._json_safe(value)

    monkeypatch.setattr(twin_api, "_telemetry_snapshot", snapshot)
    with client.websocket_connect("/ws/telemetry/39") as websocket:
        frame = websocket.receive_json()
        assert frame["grid"] == "39"
        assert frame["lines"][0]["loading_percent"] is None
        assert frame["resilience"]["grid_resilience_index"] is None
        assert frame["buses"][0]["vm_pu"] == 1.0
    assert len(snapshots) == 1
    assert math.isnan(snapshots[0]["lines"][0]["loading_percent"])


def test_telemetry_rejects_invalid_grid_and_snapshot_is_a_copy(client) -> None:
    try:
        with client.websocket_connect("/ws/telemetry/invalid"):
            raise AssertionError("invalid grid must close before accepting")
    except Exception as exc:
        assert "close" in str(exc).lower() or exc.__class__.__name__ == "WebSocketDisconnect"

    twin = twin_api.grids["39"]
    first = twin_api._telemetry_snapshot(twin)
    original = float(twin.net.res_bus.iloc[0]["vm_pu"])
    first["buses"][0]["vm_pu"] = -100.0
    second = twin_api._telemetry_snapshot(twin)
    assert second["buses"][0]["vm_pu"] == original


@pytest.fixture
def client():
    with TestClient(twin_api.app) as test_client:
        yield test_client
