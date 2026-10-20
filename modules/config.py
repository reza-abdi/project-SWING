"""Central paths for co-located Project SWING services."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


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


@dataclass(frozen=True)
class RuntimeSettings:
    twin_api_url: str
    twin_bind_host: str
    agent_bind_host: str
    startup_derate: float
    startup_load_mult: float
    twin_port: int
    agent_port: int
    contingency_interval_seconds: int
    proposal_ttl_seconds: int


def _positive_float(name: str, default: str, environment: Mapping[str, str]) -> float:
    try:
        result = float(environment.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite positive number") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


def _positive_int(name: str, default: str, environment: Mapping[str, str], *, maximum: int | None = None) -> int:
    raw = environment.get(name, default)
    if not raw.isascii() or not raw.isdecimal():
        raise ValueError(f"{name} must be a positive integer")
    result = int(raw)
    if result < 1 or (maximum is not None and result > maximum):
        raise ValueError(f"{name} must be a positive integer in range")
    return result


def _http_url(name: str, default: str, environment: Mapping[str, str]) -> str:
    value = environment.get(name, default)
    try:
        url = urlsplit(value)
        valid = (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and not any(character.isspace() for character in value)
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and (url.port is None or 1 <= url.port <= 65535)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be an HTTP(S) URL without credentials or query parameters")
    return value.rstrip("/")


def _bind_host(name: str, default: str, environment: Mapping[str, str]) -> str:
    value = environment.get(name, default)
    try:
        loopback = value.lower() == "localhost" or ip_address(value).is_loopback
    except ValueError:
        raise ValueError(f"{name} must be localhost or an IP address") from None
    if not loopback:
        mode = environment.get("SWING_AUTH_MODE", "disabled_local_only")
        origins = [origin.strip() for origin in environment.get("SWING_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
        if mode not in {"oidc", "reverse_proxy"}:
            raise ValueError(f"{name} requires configured authentication and exact allowed origins")
        if not origins or "*" in origins:
            raise ValueError("SWING_ALLOWED_ORIGINS must contain exact HTTPS origins")
        for origin in origins:
            try:
                parsed = urlsplit(origin)
                valid_origin = (
                    parsed.scheme == "https"
                    and bool(parsed.hostname)
                    and parsed.username is None
                    and parsed.password is None
                    and parsed.path in {"", "/"}
                    and not parsed.query
                    and not parsed.fragment
                    and not any(character.isspace() for character in origin)
                    and (parsed.port is None or 1 <= parsed.port <= 65535)
                )
            except ValueError:
                valid_origin = False
            if not valid_origin:
                raise ValueError("SWING_ALLOWED_ORIGINS must contain exact HTTPS origins")
    return value


def runtime_settings(environment: Mapping[str, str] | None = None) -> RuntimeSettings:
    """Parse source-compatible local settings without echoing untrusted values."""
    env = os.environ if environment is None else environment
    operation_mode(env)
    return RuntimeSettings(
        twin_api_url=_http_url("DIGITAL_TWIN_API_URL", "http://127.0.0.1:8001", env),
        twin_bind_host=_bind_host("SWING_TWIN_BIND_HOST", "127.0.0.1", env),
        agent_bind_host=_bind_host("SWING_AGENT_BIND_HOST", "127.0.0.1", env),
        startup_derate=_positive_float("SWING_STARTUP_DERATE", "0.15", env),
        startup_load_mult=_positive_float("SWING_STARTUP_LOAD_MULT", "1.4", env),
        twin_port=_positive_int("SWING_TWIN_PORT", "8001", env, maximum=65535),
        agent_port=_positive_int("SWING_AGENT_PORT", "8002", env, maximum=65535),
        contingency_interval_seconds=_positive_int("SWING_CONTINGENCY_INTERVAL_SECONDS", "30", env),
        proposal_ttl_seconds=_positive_int("SWING_PROPOSAL_TTL_SECONDS", "300", env),
    )


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
