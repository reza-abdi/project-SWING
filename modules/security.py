"""Small role checks shared by the Twin and AI HTTP services."""

from __future__ import annotations

import hmac
import ipaddress
import os
import asyncio
import json
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket


class RequestLimitMiddleware:
    """Bound JSON request bodies, expensive route rates, and concurrent workers."""

    def __init__(self, app, *, max_body_bytes: int = 65536) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self._hits: dict[tuple[str, str], list[float]] = {}
        self._semaphores = {"propose": asyncio.Semaphore(2), "chat": asyncio.Semaphore(3),
                            "optimize": asyncio.Semaphore(2), "contingency": asyncio.Semaphore(2),
                            "forecast": asyncio.Semaphore(2)}

    @staticmethod
    def _category(path: str) -> tuple[str, int] | None:
        routes = (("/propose/", "propose", 5), ("/chat/", "chat", 12),
                  ("/forecast/", "forecast", 30), ("/optimize_action/", "optimize", 10),
                  ("/contingency/", "contingency", 6))
        return next(((name, rate) for prefix, name, rate in routes if path.startswith(prefix)), None)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        category = self._category(path)
        client = scope.get("client")
        identity = client[0] if client else "unknown"
        now = time.monotonic()
        if category:
            name, limit = category
            key = (identity, name)
            hits = [stamp for stamp in self._hits.get(key, ()) if now - stamp < 60.0]
            if len(hits) >= limit:
                self._hits[key] = hits
                await self._respond(send, 429, "Request rate limit exceeded")
                return
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 10000:
                self._hits = {item: stamps for item, stamps in self._hits.items() if stamps and now - stamps[-1] < 60.0}

        body = bytearray()
        events = []
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            body.extend(chunk)
            if len(body) > self.max_body_bytes:
                await self._respond(send, 413, "Request body is too large")
                return
            events.append(event)
            if not event.get("more_body", False):
                break
        replay = iter(events)

        async def replay_receive():
            try:
                return next(replay)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        semaphore = self._semaphores.get(category[0]) if category else None
        if semaphore is not None:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=0.001)
            except asyncio.TimeoutError:
                await self._respond(send, 429, "Expensive request concurrency limit reached")
                return
        try:
            await self.app(scope, replay_receive, send)
        finally:
            if semaphore is not None:
                semaphore.release()

    @staticmethod
    async def _respond(send, status: int, message: str) -> None:
        payload = json.dumps({"detail": message}).encode("utf-8")
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
                   (b"retry-after", b"60")]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload})


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
    roles = ("admin", "internal") if role == "admin" else ("operator", "admin")
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
