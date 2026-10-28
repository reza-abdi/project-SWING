"""Grounded compliance retrieval primitives for the separate AI service."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.ai_agents.twin_client import TwinClient, TwinClientError


class RAGUnavailableError(RuntimeError):
    """The regulatory source cannot currently provide verified context."""


@dataclass(frozen=True)
class RetrievedCitation:
    source: str
    page: int


@dataclass(frozen=True)
class ComplianceContext:
    text: str
    citations: tuple[RetrievedCitation, ...]
    verified: bool


class ProposedAction(BaseModel):
    """Strictly validated operator proposal; it never executes by itself."""

    model_config = ConfigDict(extra="forbid")

    action_type: Literal["SHED_LOAD", "REDISPATCH_GEN", "LOAD_REDISTRIBUTION", "NO_ACTION"] = "NO_ACTION"
    target_bus: int | None = Field(default=None, ge=0, strict=True)
    secondary_bus: int | None = Field(default=None, ge=0, strict=True)
    mw_amount: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    justification: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "ProposedAction":
        if self.action_type == "NO_ACTION":
            if any(value is not None for value in (self.target_bus, self.secondary_bus, self.mw_amount)):
                raise ValueError("NO_ACTION cannot include buses or an MW amount")
        else:
            if self.target_bus is None or self.mw_amount is None:
                raise ValueError("active actions require target_bus and mw_amount")
            if self.action_type == "LOAD_REDISTRIBUTION":
                if self.secondary_bus is None or self.secondary_bus == self.target_bus:
                    raise ValueError("LOAD_REDISTRIBUTION requires a distinct secondary_bus")
            elif self.secondary_bus is not None:
                raise ValueError("secondary_bus is only valid for LOAD_REDISTRIBUTION")
        return self


class ValidationResult(BaseModel):
    """Physics validation response with nullable metrics when unavailable."""

    model_config = ConfigDict(extra="forbid")

    valid: bool = False
    resulting_max_loading_percent: float | None = Field(default=None, allow_inf_nan=False)
    gri_before: float | None = Field(default=None, allow_inf_nan=False)
    gri_after: float | None = Field(default=None, allow_inf_nan=False)
    gri_improvement: float | None = Field(default=None, allow_inf_nan=False)
    error: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_measurements(self) -> "ValidationResult":
        if self.valid and self.error:
            raise ValueError("a valid result cannot include an error")
        if (
            self.gri_improvement is not None
            and self.gri_before is not None
            and self.gri_after is not None
            and abs(self.gri_improvement - (self.gri_after - self.gri_before)) > 1e-6
        ):
            raise ValueError("gri_improvement must equal gri_after minus gri_before")
        return self

    def as_response(self) -> dict[str, object]:
        """Serialize with nullable measurements always present in the contract."""
        return self.model_dump(mode="json", exclude_none=False)


class GridState(BaseModel):
    """Typed graph state with isolated per-run mutable containers."""

    model_config = ConfigDict(extra="forbid")

    grid_id: Literal["39", "118"] = "118"
    telemetry: dict[str, object] = Field(default_factory=dict)
    capacity_max: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    current_situation: dict[str, object] = Field(default_factory=dict)
    forecast_bounds: dict[str, object] = Field(default_factory=dict)
    feature_importance: dict[str, object] = Field(default_factory=dict)
    risk_level: Literal["UNKNOWN", "CRITICAL", "HIGH", "MEDIUM", "WATCH", "LOW"] = "UNKNOWN"
    compliance_context: str = ""
    proposed_action: ProposedAction = Field(default_factory=ProposedAction)
    validation_result: ValidationResult = Field(default_factory=ValidationResult)
    retry_count: int = Field(default=0, ge=0)
    decision: str = "PENDING"
    operator_brief: str = ""


def observer_node(state: GridState, twin_client: TwinClient | None = None) -> dict[str, object]:
    """Read current status from the Twin API and fail closed on missing fields."""
    client = twin_client or TwinClient()
    try:
        status = client.grid_status(state.grid_id)
    except (TwinClientError, ValueError) as exc:
        return {"current_situation": {"available": False, "error": type(exc).__name__}, "capacity_max": 0.0}
    capacity = status.get("capacity_max_mw")
    resilience = status.get("resilience")
    security = status.get("security")
    bus_loads = status.get("bus_loads")
    if (
        not isinstance(capacity, (int, float))
        or not math.isfinite(float(capacity))
        or capacity <= 0
        or not isinstance(resilience, dict)
        or not isinstance(security, dict)
        or not isinstance(bus_loads, dict)
    ):
        return {"current_situation": {"available": False, "error": "INCOMPLETE_TWIN_STATUS"}, "capacity_max": 0.0}
    situation = {
        "available": True,
        "capacity_max_mw": float(capacity),
        "resilience": resilience,
        "security": security,
        "bus_loads": bus_loads,
    }
    return {"current_situation": situation, "capacity_max": float(capacity)}


def retrieve_compliance_context(
    question: str,
    vector_store,
    *,
    top_k: int = 3,
    max_chunk_chars: int = 1800,
    max_context_chars: int = 5000,
) -> ComplianceContext:
    """Retrieve bounded IEGC excerpts with a page citation for every chunk."""
    if not question.strip():
        raise ValueError("compliance question must not be empty")
    if top_k != 3 or max_chunk_chars < 1 or max_context_chars < 1:
        raise ValueError("retrieval limits are invalid")
    if vector_store is None:
        raise RAGUnavailableError("regulatory vector index is unavailable")
    try:
        documents = vector_store.similarity_search(question, k=top_k)
    except Exception as exc:
        raise RAGUnavailableError("regulatory retrieval failed") from exc
    if not documents:
        raise RAGUnavailableError("no regulatory excerpts were retrieved")

    parts = []
    citations = []
    remaining = max_context_chars
    for document in documents[:top_k]:
        metadata = getattr(document, "metadata", {}) or {}
        source = metadata.get("source")
        page = metadata.get("page")
        if source != "IEGC_Code.pdf" or not isinstance(page, int) or page < 0:
            raise RAGUnavailableError("retrieved excerpt lacks verifiable IEGC page metadata")
        text = str(getattr(document, "page_content", "")).strip()[:max_chunk_chars]
        if not text:
            continue
        citation = RetrievedCitation(source=source, page=page + 1)
        label = f"[{citation.source}, page {citation.page}]"
        excerpt = f"{label}\n{text}"[:remaining]
        if not excerpt:
            break
        parts.append(excerpt)
        citations.append(citation)
        remaining -= len(excerpt) + 2
        if remaining <= 0:
            break
    if not parts:
        raise RAGUnavailableError("retrieved regulatory excerpts contain no usable text")
    return ComplianceContext(text="\n\n".join(parts), citations=tuple(citations), verified=True)


def safe_compliance_lookup(question: str, vector_store=None) -> dict[str, object]:
    """Convert missing corpus/index/retrieval into an explicit fail-closed state."""
    try:
        result = retrieve_compliance_context(question, vector_store)
    except (RAGUnavailableError, ValueError):
        return {
            "status": "RAG_UNAVAILABLE",
            "context": "",
            "citations": [],
            "decision_allowed": False,
            "actuation_allowed": False,
        }
    return {
        "status": "RAG_READY",
        "context": result.text,
        "citations": [
            {"source": item.source, "page": item.page} for item in result.citations
        ],
        "decision_allowed": True,
        "actuation_allowed": False,
    }
