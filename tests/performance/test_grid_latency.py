"""Opt-in performance measurements; configure measured budgets before enforcing them."""

import os
import asyncio
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from modules.config import runtime_settings
from modules.physics_engine import api as twin_api
from modules.physics_engine.twin_model import TwinModel


pytestmark = pytest.mark.skipif(os.environ.get("SWING_RUN_PERF") != "1", reason="set SWING_RUN_PERF=1 for the non-CI performance lane")
ROOT = Path(__file__).resolve().parents[2]


def _record(name: str, elapsed: float) -> None:
    print(f"PERF {name}: {elapsed:.6f}s")
    budget = os.environ.get(f"SWING_PERF_MAX_{name.upper()}_SECONDS")
    if budget:
        assert elapsed <= float(budget), f"{name} exceeded the measured baseline budget of {budget}s"


def _measure(callable_):
    started = time.perf_counter()
    result = callable_()
    return result, time.perf_counter() - started


def test_cold_api_import_startup_baseline():
    command = [sys.executable, "-c", "import modules.physics_engine.api"]
    _, elapsed = _measure(lambda: subprocess.run(command, cwd=ROOT, check=True, timeout=90, capture_output=True))
    _record("cold_startup", elapsed)


@pytest.mark.parametrize("grid", ("39", "118"))
def test_power_flow_solve_baseline(grid):
    model = TwinModel(grid)
    result, elapsed = _measure(model.run_baseline_simulation)
    assert result["simulation_status"] == "COMPLETED"
    _record(f"solve_{grid}", elapsed)


def test_ieee_118_n_minus_one_scan_baseline():
    twin_api.initialize_grids(runtime_settings())
    result, elapsed = _measure(lambda: twin_api._scan_contingencies_sync("118"))
    assert result["status"] in {"fresh", "partial"}
    _record("n1_scan_118", elapsed)


def test_telemetry_snapshot_processing_baseline():
    twin_api.initialize_grids(runtime_settings())
    twin = twin_api.grids["118"]
    first, elapsed = _measure(lambda: twin_api._telemetry_snapshot(twin))
    second_started = time.perf_counter()
    second = twin_api._telemetry_snapshot(twin)
    interval = time.perf_counter() - second_started
    assert first["time_step"] == second["time_step"]
    _record("telemetry_snapshot", max(elapsed, interval))


def test_websocket_telemetry_stream_remains_at_one_hertz(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    twin_api.initialize_grids(runtime_settings())
    monkeypatch.setattr(twin_api, "validate_websocket_origin", lambda _socket: True)
    class SampleSocket:
        client = SimpleNamespace(host="127.0.0.1")
        headers = {"origin": "http://127.0.0.1:5500"}
        def __init__(self):
            self.times = []
        async def accept(self):
            pass
        async def send_json(self, _payload):
            self.times.append(time.perf_counter())
            if len(self.times) == 2:
                raise WebSocketDisconnect()
        async def close(self, code):
            raise AssertionError(f"unexpected WebSocket close: {code}")

    socket = SampleSocket()
    asyncio.run(twin_api.stream_telemetry(socket, "118"))
    interval = socket.times[1] - socket.times[0]
    _record("telemetry_interval", interval)
    assert 0.95 <= interval <= 1.2
