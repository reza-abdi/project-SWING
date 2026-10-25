"""Physics-only FastAPI service for the Project SWING digital twin."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from modules.config import runtime_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate service settings at startup and retain them for dependencies."""
    app.state.settings = runtime_settings()
    yield


app = FastAPI(
    title="Digital Twin API",
    description="Physics-only simulation API for IEEE transmission grid models.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", tags=["service"])
def read_root() -> dict[str, str]:
    """Report that the digital-twin service is online."""
    return {"message": "Digital Twin Engine is Online"}
