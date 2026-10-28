"""Independent HTTP service for AI-assisted, human-approved grid proposals."""

import asyncio
from fastapi import FastAPI

from modules.ai_agents.agent_core import GridState, build_agent_graph
from modules.ai_agents.twin_client import TwinClient


app = FastAPI(title="Project SWING Decision Support", version="1.0.0")


__all__ = ["app", "GridState", "TwinClient", "build_agent_graph"]


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "Project SWING Decision Support", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Return only service and read-only Twin availability, never configuration."""
    try:
        await asyncio.wait_for(asyncio.to_thread(TwinClient().grid_status, "118"), timeout=2.0)
        twin_status = "available"
    except asyncio.TimeoutError:
        twin_status = "timeout"
    except Exception:
        twin_status = "unavailable"
    return {"status": "ok", "twin": twin_status}
