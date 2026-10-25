"""Physics-only FastAPI service for the Project SWING digital twin."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from modules.config import runtime_settings
from modules.physics_engine.twin_model import TwinModel


grids: dict[str, TwinModel] = {}


def initialize_grids(settings=None) -> dict[str, TwinModel]:
    """Build independent IEEE networks and apply the configured startup states."""
    resolved_settings = settings or runtime_settings()
    candidate_grids = {
        "39": TwinModel("39"),
        "118": TwinModel("118"),
    }
    if candidate_grids["39"].run_baseline_simulation()["simulation_status"] != "COMPLETED":
        raise RuntimeError("IEEE-39 baseline simulation did not converge")
    if candidate_grids["118"].apply_stress_test(
        resolved_settings.startup_load_mult,
        resolved_settings.startup_derate,
    ) != "COMPLETED":
        raise RuntimeError("IEEE-118 startup stress simulation did not converge")

    grids.clear()
    grids.update(candidate_grids)
    return grids


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate service settings at startup and retain them for dependencies."""
    settings = runtime_settings()
    app.state.settings = settings
    initialize_grids(settings)
    try:
        yield
    finally:
        grids.clear()


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
