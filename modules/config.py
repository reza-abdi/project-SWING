"""Central paths for co-located Project SWING services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPERATION_MODE = "simulation"


def operation_mode(environment: Mapping[str, str] | None = None) -> str:
    """Allow only the supplied software simulator, including on hosted deployments."""
    env = os.environ if environment is None else environment
    mode = env.get("SWING_OPERATION_MODE", DEFAULT_OPERATION_MODE)
    if mode != DEFAULT_OPERATION_MODE:
        raise ValueError("SWING_OPERATION_MODE must be 'simulation'")
    return mode


def resolve_project_path(value: str | Path, *, root: Path = PROJECT_ROOT) -> Path:
    """Resolve a configured relative path against the repository, never the CWD."""
    path = Path(value).expanduser()
    if not str(value).strip():
        raise ValueError("configured path must not be empty")
    return (path if path.is_absolute() else root / path).resolve()


def _path_setting(name: str, default: Path, environment: Mapping[str, str]) -> Path:
    value = environment.get(name)
    if value is None:
        return default.resolve()
    if not value.strip():
        raise ValueError(f"{name} must be a nonempty path")
    return resolve_project_path(value)


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    data: Path
    models: Path
    faiss: Path
    event_db: Path
    twin_ui: Path
    agent_ui: Path


def runtime_paths(environment: Mapping[str, str] | None = None) -> RuntimePaths:
    """Return input and runtime paths without creating files or loading artifacts."""
    env = os.environ if environment is None else environment
    operation_mode(env)
    data = _path_setting("SWING_DATA_DIR", PROJECT_ROOT / "data", env)
    return RuntimePaths(
        root=PROJECT_ROOT,
        data=data,
        models=_path_setting("SWING_MODEL_DIR", PROJECT_ROOT / "models", env),
        faiss=_path_setting("SWING_FAISS_DIR", data / "knowledge_base" / "faiss_index", env),
        event_db=_path_setting("SWING_EVENT_DB_PATH", data / "event_log.db", env),
        twin_ui=PROJECT_ROOT / "Digital_Twin_UI",
        agent_ui=PROJECT_ROOT / "Agent_Dashboard_UI",
    )
