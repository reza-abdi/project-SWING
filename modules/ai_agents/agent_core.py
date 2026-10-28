"""Grounded compliance retrieval primitives for the separate AI service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.ai_agents.twin_client import (
    TwinClient,
    TwinClientError,
    validate_operator_forecast_features,
)


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
    telemetry_source: Literal["operator", "historical_proxy", "demo", "unavailable"] = "unavailable"
    capacity_max: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    current_situation: dict[str, object] = Field(default_factory=dict)
    forecast_bounds: dict[str, object] = Field(default_factory=dict)
    feature_importance: dict[str, object] = Field(default_factory=dict)
    forecast_source: Literal["NONE", "TFT", "LIGHTGBM"] = "NONE"
    forecast_input_source: Literal["operator", "historical_proxy", "demo", "mixed", "unavailable"] = "unavailable"
    forecast_error: str | None = None
    risk_level: Literal["UNKNOWN", "CRITICAL", "HIGH", "MEDIUM", "WATCH", "LOW"] = "UNKNOWN"
    compliance_context: str = ""
    proposed_action: ProposedAction = Field(default_factory=ProposedAction)
    validation_result: ValidationResult = Field(default_factory=ValidationResult)
    retry_count: int = Field(default=0, ge=0)
    decision: str = "PENDING"
    operator_brief: str = ""


def parse_decision_response(response: str, *, valid_bus_ids: set[int] | None = None) -> ProposedAction:
    """Parse one strict action object; model text is untrusted input."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("model response is empty")
    text = response.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("model response must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    allowed = {"action_type", "target_bus", "secondary_bus", "mw_amount", "justification"}
    if set(payload) - allowed or not {"action_type", "justification"}.issubset(payload):
        raise ValueError("model response has missing or unsupported fields")
    for key in ("target_bus", "secondary_bus"):
        bus = payload.get(key)
        if bus is not None and (isinstance(bus, bool) or not isinstance(bus, int)):
            raise ValueError(f"{key} must be an integer bus identifier")
        if bus is not None and valid_bus_ids is not None and bus not in valid_bus_ids:
            raise ValueError(f"{key} is not present in the live grid")
    return ProposedAction.model_validate(payload)


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


def tft_forecasting_node(
    state: GridState,
    forecaster=None,
    *,
    trust_checkpoint: bool = False,
    trust_dataset: bool = False,
) -> dict[str, object]:
    """Try trusted historical-proxy TFT inference before single-hour fallback."""
    if not math.isfinite(state.capacity_max) or state.capacity_max <= 0:
        return {"forecast_bounds": {}, "forecast_source": "NONE", "forecast_error": "INVALID_BASELINE"}
    try:
        if forecaster is None:
            from modules.forecasting.tft_forecaster import TFTForecaster

            forecaster = TFTForecaster()
        if forecaster.model is None:
            forecaster.load_model(trust_checkpoint=trust_checkpoint)
        dataset = forecaster.training_dataset_params
        if dataset is None:
            dataset = forecaster.load_training_dataset_config(trust_dataset=trust_dataset)
        history = forecaster.build_recent_history_window()
        raw = forecaster.forecast_multi_horizon(history, dataset)
        indices = {"1h": 0, "2h": 1, "6h": 5, "24h": 23}
        bounds = {}
        for horizon, index in indices.items():
            for quantile in ("p10", "p50", "p90"):
                values = raw.get(quantile)
                if not isinstance(values, (list, tuple)) or len(values) != 24:
                    raise ValueError("TFT must return 24 hourly values for every quantile")
                value = float(values[index]) * state.capacity_max
                if not math.isfinite(value):
                    raise ValueError("TFT returned a non-finite prediction")
                bounds[f"{quantile}_{horizon}"] = value
        return {
            "forecast_bounds": bounds,
            "forecast_source": "TFT",
            "forecast_input_source": "historical_proxy",
            "forecast_error": None,
        }
    except Exception as exc:
        return {
            "forecast_bounds": {},
            "forecast_source": "NONE",
            "forecast_input_source": "unavailable",
            "forecast_error": type(exc).__name__,
        }


def lightgbm_fallback_node(state: GridState, forecaster=None) -> dict[str, object]:
    """Always try LightGBM for next-hour bounds and p50 feature importance."""
    bounds = dict(state.forecast_bounds)
    was_tft = state.forecast_source == "TFT"
    if state.telemetry_source != "operator":
        reason = "OPERATOR_FORECAST_FEATURES_REQUIRED"
        if not was_tft:
            for horizon in ("1h", "2h", "6h", "24h"):
                for quantile in ("p10", "p50", "p90"):
                    bounds[f"{quantile}_{horizon}"] = None
        return {
            "forecast_bounds": bounds,
            "feature_importance": {},
            "forecast_source": "TFT" if was_tft else "NONE",
            "forecast_input_source": "historical_proxy" if was_tft else "unavailable",
            "forecast_error": reason,
        }
    try:
        if forecaster is None:
            from modules.forecasting.grid_forecaster import GridForecaster

            forecaster = GridForecaster()
        features = validate_operator_forecast_features(state.telemetry)
        forecaster.load_models()
        one_hour = forecaster.forecast_next_hour(features, state.capacity_max)
        for quantile in ("p10", "p50", "p90"):
            value = float(one_hour[quantile])
            if not math.isfinite(value):
                raise ValueError("LightGBM returned a non-finite prediction")
            bounds[f"{quantile}_1h"] = value
        if not was_tft:
            for horizon in ("2h", "6h", "24h"):
                for quantile in ("p10", "p50", "p90"):
                    bounds[f"{quantile}_{horizon}"] = None
        try:
            importance = forecaster.explain_prediction(features)
        except Exception:
            importance = {}
        return {
            "forecast_bounds": bounds,
            "feature_importance": importance,
            "forecast_source": "TFT" if was_tft else "LIGHTGBM",
            "forecast_input_source": "mixed" if was_tft else "operator",
            "forecast_error": state.forecast_error if was_tft else None,
        }
    except Exception as exc:
        return {
            "forecast_bounds": bounds,
            "feature_importance": {},
            "forecast_source": "TFT" if was_tft else "NONE",
            "forecast_input_source": "historical_proxy" if was_tft else "unavailable",
            "forecast_error": f"LIGHTGBM_UNAVAILABLE:{type(exc).__name__}",
        }


def risk_assessment_node(state: GridState) -> dict[str, object]:
    """Elevate an already-collapsed live Twin state above forecasts."""
    situation = state.current_situation
    if not situation.get("available"):
        return {"risk_level": "UNKNOWN"}
    resilience = situation.get("resilience") or {}
    security = situation.get("security") or {}
    if resilience.get("collapsed") or security.get("collapsed"):
        return {"risk_level": "CRITICAL"}
    overloaded = security.get("overloaded_line_count", 0)
    if isinstance(overloaded, (int, float)) and not isinstance(overloaded, bool) and overloaded > 0:
        return {"risk_level": "HIGH"}
    threshold = state.capacity_max * 0.98
    if not math.isfinite(threshold) or threshold <= 0:
        return {"risk_level": "UNKNOWN"}

    def bound(key: str):
        value = state.forecast_bounds.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None
        return float(value)

    p90_1h = bound("p90_1h")
    p90_6h = bound("p90_6h")
    p90_24h = bound("p90_24h")
    if p90_1h is None:
        return {"risk_level": "UNKNOWN"}
    if p90_1h >= threshold:
        return {"risk_level": "HIGH"}
    if p90_1h >= threshold * 0.90 or (p90_6h is not None and p90_6h >= threshold):
        return {"risk_level": "MEDIUM"}
    if p90_24h is not None and p90_24h >= threshold:
        return {"risk_level": "WATCH"}
    return {"risk_level": "LOW"}


def watch_operator_node(state: GridState) -> dict[str, object]:
    """Return an observation-only brief for a 24-hour WATCH forecast."""
    if state.risk_level != "WATCH":
        return {"decision": "ROUTE_MISMATCH", "operator_brief": "WATCH route requires WATCH risk."}
    horizon = state.forecast_bounds.get("p90_24h")
    return {
        "decision": "MONITOR",
        "operator_brief": (
            f"Monitor grid {state.grid_id}: the 24-hour upper forecast is "
            f"{horizon:g} MW. No optimization or grid action was requested."
            if isinstance(horizon, (int, float)) and not isinstance(horizon, bool)
            else f"Monitor grid {state.grid_id}: elevated 24-hour risk; forecast bound unavailable."
        ),
        "proposed_action": ProposedAction(action_type="NO_ACTION"),
    }


def no_action_operator_node(state: GridState) -> dict[str, object]:
    """Recommend the baseline only when live observations and forecasts are safe."""
    if state.risk_level == "UNKNOWN" or not state.current_situation.get("available"):
        return {
            "decision": "DATA_UNAVAILABLE",
            "operator_brief": "Current grid status is unavailable; safety cannot be assessed.",
            "proposed_action": ProposedAction(action_type="NO_ACTION"),
        }
    if state.risk_level != "LOW":
        return {
            "decision": "ROUTE_MISMATCH",
            "operator_brief": "Baseline recommendation requires a LOW risk assessment.",
            "proposed_action": ProposedAction(action_type="NO_ACTION"),
        }
    return {
        "decision": "MAINTAIN_BASELINE",
        "operator_brief": "Available live status and forecasts indicate low risk; maintain the current baseline.",
        "proposed_action": ProposedAction(action_type="NO_ACTION"),
    }


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
