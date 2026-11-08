"""Credential-free checks for deployment wiring and fail-closed defaults."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.validate_deployment import validate


def test_static_deployment_contract_passes() -> None:
    assert validate() == []


def test_no_certificates_or_real_tokens_are_checked_in() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("SWING_OPERATOR_TOKEN", "SWING_ADMIN_TOKEN", "SWING_INTERNAL_TWIN_TOKEN"):
        line = next(item for item in example.splitlines() if item.startswith(f"{name}="))
        assert line.partition("=")[2] == ""
    assert not (ROOT / "deploy/certs/privkey.pem").exists()


def test_proxy_routes_and_same_origin_fallbacks_exist() -> None:
    twin = (ROOT / "deploy/nginx/twin.conf").read_text(encoding="utf-8")
    agent = (ROOT / "deploy/nginx/agent.conf").read_text(encoding="utf-8")
    assert "location /api/twin/" in twin and "location ~ ^/ws/twin/" in twin
    assert "location /api/agent/" in agent
    for filename in ("ai_app.js", "ai_chat.js", "ai_forecast.js", "ai_rl_status.js"):
        source = (ROOT / "Agent_Dashboard_UI" / filename).read_text(encoding="utf-8")
        assert "/api/agent" in source or "/api/twin" in source


def test_services_share_only_private_persistent_network_paths() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert compose.count("swing-state:/var/lib/swing") == 2
    assert "networks: [backend, egress]" in compose
    assert "ports:\n      - \"127.0.0.1:${SWING_HTTPS_PORT:-8443}:443\"" in compose
    assert "SWING_ADMIN_TOKEN: ${SWING_ADMIN_TOKEN:?" in compose
    assert "SWING_INTERNAL_TWIN_TOKEN: ${SWING_INTERNAL_TWIN_TOKEN:?" in compose


def test_containers_drop_capabilities_and_tls_proxy_keeps_only_bind_capability() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert compose.count('security_opt: ["no-new-privileges:true"]') == 3
    assert compose.count("cap_drop: [ALL]") == 3
    assert "cap_add: [NET_BIND_SERVICE]" in compose
