"""Read-only, loopback-only smoke checks for the four local Project SWING services."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import socket
import struct
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.config import runtime_settings


def request_json(url: str, timeout: float = 4.0) -> dict:
    with urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {url} returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {url} did not return a JSON object")
    return payload


def _finite_tree(value) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_tree(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite_tree(item) for item in value)
    return True


def sample_websocket(url: str) -> dict:
    """Read one local RFC 6455 text frame using only the standard library."""
    parsed = urlsplit(url)
    if parsed.scheme != "ws" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("WebSocket smoke target must be local plain ws://")
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=4) as connection:
        connection.settimeout(4)
        request = (f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        connection.sendall(request.encode("ascii"))
        received = bytearray()
        while b"\r\n\r\n" not in received:
            chunk = connection.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket closed during handshake")
            received.extend(chunk)
        header, remainder = bytes(received).split(b"\r\n\r\n", 1)
        lines = header.decode("latin1").split("\r\n")
        headers = {line.partition(":")[0].strip().lower(): line.partition(":")[2].strip()
                   for line in lines[1:] if ":" in line}
        if not lines[0].endswith(" 101 Switching Protocols") or headers.get("sec-websocket-accept") != expected:
            raise RuntimeError("WebSocket handshake was rejected")

        def exact(size: int) -> bytes:
            while len(remainder) < size:
                chunk = connection.recv(4096)
                if not chunk:
                    raise RuntimeError("WebSocket closed before telemetry frame")
                remainder.extend(chunk)
            result = bytes(remainder[:size])
            del remainder[:size]
            return result

        first, second = exact(2)
        opcode, length = first & 0x0F, second & 0x7F
        if length == 126:
            length = struct.unpack("!H", exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", exact(8))[0]
        if length > 1_000_000 or opcode != 1:
            raise RuntimeError("WebSocket telemetry frame has an unsupported type or size")
        masked = bool(second & 0x80)
        mask = exact(4) if masked else b""
        frame = exact(length)
        if masked:
            frame = bytes(byte ^ mask[index % 4] for index, byte in enumerate(frame))
        payload = json.loads(frame.decode("utf-8"))
        if not isinstance(payload, dict) or not _finite_tree(payload):
            raise RuntimeError("WebSocket telemetry frame is not a finite JSON object")
        if not {"grid", "time_step", "buses", "lines"} <= set(payload):
            raise RuntimeError("WebSocket telemetry frame is missing required fields")
        return payload


def run() -> None:
    settings = runtime_settings()
    twin = settings.twin_api_url.rstrip("/")
    if not twin.startswith("http://127.0.0.1") and not twin.startswith("http://localhost"):
        raise RuntimeError("--local smoke checks require a loopback Digital Twin URL")
    agent = f"http://127.0.0.1:{settings.agent_port}"
    for grid in ("39", "118"):
        status = request_json(f"{twin}/grid_status?{urlencode({'grid': grid})}")
        topology = request_json(f"{twin}/topology?{urlencode({'grid': grid})}")
        contingency = request_json(f"{twin}/contingency/{grid}")
        if status.get("buses") != int(grid) or not isinstance(status.get("bus_loads"), dict):
            raise RuntimeError(f"Grid {grid} status contract failed")
        if not topology.get("nodes") or not isinstance(topology.get("edges"), list):
            raise RuntimeError(f"Grid {grid} topology contract failed")
        if not {"status", "lines", "generators", "age_seconds"} <= set(contingency):
            raise RuntimeError(f"Grid {grid} contingency contract failed")
        print(f"OK Twin grid {grid}: status, topology, contingency")

    health = request_json(f"{agent}/health")
    if health.get("status") != "ok":
        raise RuntimeError("AI service health check failed")
    for base, page in (("http://127.0.0.1:3000", "/home.html"),
                       ("http://127.0.0.1:3001", "/ai_home.html")):
        with urlopen(base + page, timeout=4) as response:
            if response.status != 200 or not response.read(256).strip():
                raise RuntimeError(f"Static page is unavailable: {base + page}")
    frame = sample_websocket(f"ws://127.0.0.1:{settings.twin_port}/ws/telemetry/39")
    print(f"OK AI health, UI pages, telemetry frame for {frame['grid']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", required=True, help="target only loopback services")
    parser.add_argument("--no-mutation", action="store_true", required=True, help="run read-only checks only")
    parser.parse_args(argv)
    try:
        run()
    except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Smoke check failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
