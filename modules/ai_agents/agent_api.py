"""Independent HTTP service for AI-assisted, human-approved grid proposals."""

from fastapi import FastAPI

from modules.ai_agents.agent_core import GridState, build_agent_graph
from modules.ai_agents.twin_client import TwinClient


app = FastAPI(title="Project SWING Decision Support", version="1.0.0")


__all__ = ["app", "GridState", "TwinClient", "build_agent_graph"]
