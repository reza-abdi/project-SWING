"""Run the four local Project SWING simulation services together."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from modules.config import PROJECT_ROOT, runtime_settings


@dataclass(frozen=True)
class Service:
    name: str
    command: tuple[str, ...]
    directory: Path
    port: int


def services() -> tuple[Service, ...]:
    settings = runtime_settings()
    return (
        Service("Digital Twin API", (sys.executable, str(PROJECT_ROOT / "scripts" / "run_twin.py")), PROJECT_ROOT, settings.twin_port),
        Service("AI Agent API", (sys.executable, str(PROJECT_ROOT / "scripts" / "run_agent.py")), PROJECT_ROOT, settings.agent_port),
        Service("Digital Twin UI", (sys.executable, "-m", "http.server", "3000", "--bind", "127.0.0.1"), PROJECT_ROOT / "Digital_Twin_UI", 3000),
        Service("AI Dashboard UI", (sys.executable, "-m", "http.server", "3001", "--bind", "127.0.0.1"), PROJECT_ROOT / "Agent_Dashboard_UI", 3001),
    )


def wait_until_listening(process: subprocess.Popen, port: int, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited during startup with status {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"service did not listen on port {port} before timeout")


def stop_services(processes: list[tuple[Service, subprocess.Popen]]) -> None:
    for _, process in processes:
        if process.poll() is None:
            process.terminate()
    for _, process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    processes: list[tuple[Service, subprocess.Popen]] = []
    try:
        for service in services():
            if not service.directory.is_dir():
                raise RuntimeError(f"missing service directory: {service.directory}")
            print(f"Starting {service.name} on 127.0.0.1:{service.port}", flush=True)
            process = subprocess.Popen(service.command, cwd=service.directory)
            processes.append((service, process))
            wait_until_listening(process, service.port)
        print("Digital Twin UI: http://127.0.0.1:3000/home.html", flush=True)
        print("AI Dashboard UI: http://127.0.0.1:3001/ai_home.html", flush=True)
        print("Press Ctrl+C to stop all services.", flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping local services.", flush=True)
    finally:
        stop_services(processes)


if __name__ == "__main__":
    main()
