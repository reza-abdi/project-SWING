"""Small role checks shared by the Twin and AI HTTP services."""

from __future__ import annotations

import hmac
import ipaddress
import os

from fastapi import HTTPException, Request


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
