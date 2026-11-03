"""Small role checks shared by the Twin and AI HTTP services."""

from __future__ import annotations

import hmac
import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket


def allowed_origins() -> list[str]:
    """Return exact configured origins; local development uses known loopback ports."""
    configured = [item.strip().rstrip("/") for item in os.environ.get("SWING_ALLOWED_ORIGINS", "").split(",") if item.strip()]
    local_mode = os.environ.get("SWING_AUTH_MODE", "disabled_local_only") == "disabled_local_only"
    if not configured and local_mode:
        configured = [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5500, 8000, 8080)]
    if "*" in configured or len(set(configured)) != len(configured):
        raise ValueError("SWING_ALLOWED_ORIGINS must contain unique exact origins")
    for origin in configured:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("SWING_ALLOWED_ORIGINS must contain exact HTTP(S) origins")
        if not local_mode and parsed.scheme != "https":
            raise ValueError("remote allowed origins must use HTTPS")
    return configured


def validate_websocket_origin(websocket: WebSocket) -> bool:
    """Accept configured browser origins; allow originless local diagnostic clients."""
    origin = websocket.headers.get("origin")
    if origin:
        return origin.rstrip("/") in allowed_origins()
    peer = websocket.client.host if websocket.client else ""
    try:
        return (os.environ.get("SWING_AUTH_MODE", "disabled_local_only") == "disabled_local_only"
                and ipaddress.ip_address(peer).is_loopback)
    except ValueError:
        return False


def _authorized(request: Request, role: str) -> bool:
    mode = os.environ.get("SWING_AUTH_MODE", "disabled_local_only")
    if mode == "disabled_local_only":
        host = request.client.host if request.client else ""
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host.lower() == "localhost"
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        return False
    roles = ("admin",) if role == "admin" else ("operator", "admin")
    for candidate_role in roles:
        expected = os.environ.get(f"SWING_{candidate_role.upper()}_TOKEN", "")
        if expected and hmac.compare_digest(supplied, expected):
            return True
    return False


async def require_operator(request: Request) -> None:
    """Allow local development or an explicitly authenticated operator/admin."""
    if not _authorized(request, "operator"):
        raise HTTPException(status_code=401, detail="Operator authentication required")


async def require_admin(request: Request) -> None:
    """Protect direct simulation actuation behind an administrator role."""
    if not _authorized(request, "admin"):
        raise HTTPException(status_code=403, detail="Administrator authentication required")
