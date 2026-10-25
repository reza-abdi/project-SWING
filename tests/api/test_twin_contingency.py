"""Contingency endpoint freshness and scanner lifetime regressions."""

import asyncio
import time

from fastapi.testclient import TestClient
import pytest

import modules.physics_engine.api as twin_api
from modules.config import runtime_settings


@pytest.fixture
def client():
    with TestClient(twin_api.app) as test_client:
        yield test_client


def test_contingency_endpoint_reports_cache_state(client, monkeypatch) -> None:
    monkeypatch.setattr(twin_api, "runtime_settings", lambda: runtime_settings({}))
    twin_api.contingency_cache["39"] = {"status": "unavailable", "lines": {}, "generators": {}}
    assert client.get("/contingency/39").json()["status"] == "unavailable"

    twin_api.contingency_cache["39"] = {
        "status": "fresh",
        "lines": {"0": {"secure": True}},
        "generators": {},
        "last_scan_timestamp": time.time(),
    }
    fresh = client.get("/contingency/39").json()
    assert fresh["status"] == "fresh"
    assert fresh["lines"]["0"]["secure"] is True
    assert fresh["age_seconds"] is not None

    twin_api.contingency_cache["39"]["last_scan_timestamp"] = time.time() - 1000
    assert client.get("/contingency/39").json()["status"] == "stale"
    assert client.get("/contingency/invalid").status_code == 404


def test_lifespan_starts_one_scanner_per_grid_and_cancels_on_shutdown(monkeypatch) -> None:
    started = []
    stopped = []
    never = asyncio.Event()

    async def scanner(grid_id: str, interval_seconds: int) -> None:
        started.append((grid_id, interval_seconds))
        try:
            await never.wait()
        finally:
            stopped.append(grid_id)

    configured = runtime_settings({"SWING_CONTINGENCY_INTERVAL_SECONDS": "7"})
    monkeypatch.setattr(twin_api, "runtime_settings", lambda: configured)
    monkeypatch.setattr(twin_api, "initialize_grids", lambda settings: twin_api.grids.update({"39": None, "118": None}))
    monkeypatch.setattr(twin_api, "contingency_scanner_loop", scanner)

    for _ in range(2):
        with TestClient(twin_api.app):
            assert set(twin_api.app.state.contingency_scanner_tasks) == {"39", "118"}
            assert len(twin_api.app.state.contingency_scanner_tasks) == 2
        assert twin_api.app.state.contingency_scanner_tasks == {}

    assert sorted(started) == [("118", 7), ("118", 7), ("39", 7), ("39", 7)]
    assert sorted(stopped) == ["118", "118", "39", "39"]
