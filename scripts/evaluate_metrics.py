"""Offline evaluation reports for forecasting, RL training, retrieval, and proposals."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def regression_metrics(actual, predicted) -> dict[str, float]:
    """Return normalized RMSE, MAE and MAPE, ignoring zero targets for MAPE."""
    pairs = [(float(a), float(p)) for a, p in zip(actual, predicted)
             if math.isfinite(float(a)) and math.isfinite(float(p))]
    if not pairs:
        raise ValueError("evaluation requires at least one finite target/prediction pair")
    observed, estimates = zip(*pairs)
    scale = max(observed) - min(observed)
    if scale == 0:
        scale = max(abs(value) for value in observed) or 1.0
    errors = [estimate - value for value, estimate in pairs]
    mape_values = [abs(error / value) for (value, _), error in zip(pairs, errors) if value != 0]
    return {
        "n": len(pairs),
        "nrmse": math.sqrt(statistics.mean(error * error for error in errors)) / scale,
        "nmae": statistics.mean(abs(error) for error in errors) / scale,
        "mape": statistics.mean(mape_values) if mape_values else float("nan"),
    }


def evaluate_forecasts(data_path: Path | None = None, models_dir: Path | None = None) -> dict:
    """Evaluate supplied LightGBM quantile models on a chronological 20% holdout."""
    import lightgbm as lgb
    import pandas as pd

    from modules.forecasting.grid_forecaster import GridForecaster

    source = data_path or PROJECT_ROOT / "data/processed_data/tft_ready_data.csv"
    model_root = models_dir or PROJECT_ROOT / "models"
    frame = pd.read_csv(source, parse_dates=["Datetime"]).sort_values("Datetime")
    forecaster = GridForecaster()
    features = list(forecaster.FEATURE_COLUMNS)
    required = {"Datetime", "Northen Region Hourly Demand", *features}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"evaluation data is missing columns: {sorted(missing)}")
    split = int(len(frame) * 0.8)
    test = frame.iloc[split:]
    if split < 2 or test.empty:
        raise ValueError("chronological evaluation needs at least three rows")
    results = {}
    for quantile in (10, 50, 90):
        model = lgb.Booster(model_file=str(model_root / f"lightgbm_q_{quantile}.txt"))
        if model.feature_name() != features:
            raise ValueError(f"lightgbm_q_{quantile}.txt feature schema does not match source")
        prediction = model.predict(test.loc[:, features])
        results[f"p{quantile}"] = regression_metrics(test["normalized_target"], prediction)
    return {"dataset": str(source), "target_column": "Northen Region Hourly Demand",
            "split": "chronological 80/20", "test_rows": len(test), "quantiles": results}


def evaluate_rl_logs(models_dir: Path | None = None) -> dict:
    """Summarize convergence and reward deciles for the four supplied SAC logs."""
    root = models_dir or PROJECT_ROOT / "models"
    report = {}
    for grid in ("39", "118"):
        for action in ("shed_load", "redispatch_gen"):
            path = root / f"rl_optimizer_{action}_{grid}_rewards.csv"
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            if not rows or not {"reward", "converged"} <= set(rows[0]):
                raise ValueError(f"reward log is empty or has an invalid schema: {path.name}")
            rewards = [float(row["reward"]) for row in rows]
            if any(not math.isfinite(reward) for reward in rewards):
                raise ValueError(f"reward log contains non-finite values: {path.name}")
            decile = max(1, math.ceil(len(rewards) / 10))
            flags = [row["converged"].strip().lower() in {"true", "1", "yes"} for row in rows]
            report[f"{grid}/{action}"] = {
                "episodes": len(rewards),
                "convergence_fraction": sum(flags) / len(flags),
                "first_decile_mean_reward": statistics.mean(rewards[:decile]),
                "last_decile_mean_reward": statistics.mean(rewards[-decile:]),
            }
    return report


def evaluate_rag(db_path: Path | None = None, *, judge: bool = False) -> dict:
    """Score up to seven active proposals against trusted IEGC retrieval excerpts."""
    from modules.config import runtime_paths

    database = db_path or runtime_paths().event_db
    if not database.is_file():
        return {"method": "heuristic retrieval overlap", "evaluated": 0, "results": []}
    with sqlite3.connect(str(database)) as connection:
        rows = connection.execute(
            "SELECT grid_id, action_json FROM agent_proposals ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    selected = []
    for grid, action_json in rows:
        action = json.loads(action_json)
        if action.get("action_type") != "NO_ACTION":
            selected.append((grid, action))
        if len(selected) == 7:
            break
    if not selected:
        return {"method": "heuristic retrieval overlap", "evaluated": 0, "results": []}
    manifest_hash = os.environ.get("SWING_TRUSTED_RAG_MANIFEST_SHA256")
    if not manifest_hash:
        raise ValueError("set SWING_TRUSTED_RAG_MANIFEST_SHA256 to the reviewed index manifest hash")
    from modules.ai_agents.agent_core import retrieve_compliance_context
    from modules.ai_agents.rag_builder import RAGBuilder

    builder = RAGBuilder()
    vector_store = builder.load_index(builder.create_embeddings(), trusted_manifest_sha256=manifest_hash)
    results = []
    for grid, action in selected:
        query = str(action.get("justification", ""))[:1000]
        context = retrieve_compliance_context(query, vector_store)
        query_terms = {word.lower() for word in query.split() if len(word) > 3}
        excerpt = context.text
        excerpt_terms = {word.lower() for word in excerpt.split() if len(word) > 3}
        item = {"grid": grid, "action_type": action.get("action_type"),
                "citations": [{"source": citation.source, "page": citation.page} for citation in context.citations],
                "heuristic_term_overlap": len(query_terms & excerpt_terms) / max(1, len(query_terms)),
                "finding_type": "heuristic retrieval relevance; not a compliance determination"}
        if judge:
            from modules.ai_agents.llm_client import generate_with_fallback
            prompt = ("Assess whether this retrieved regulatory excerpt is relevant to the operator's stated rationale. "
                      "Return a short relevance label and reason; do not advise grid operation.\n"
                      f"Rationale: {query}\nExcerpt: {excerpt[:4000]}")
            item["optional_llm_judgment"] = generate_with_fallback(prompt)[:1000]
            item["finding_type"] = "LLM-based relevance judgment; not a compliance determination"
        results.append(item)
    return {"method": "optional Gemini judge" if judge else "heuristic retrieval overlap",
            "evaluated": len(results), "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--section", choices=("forecast", "rl", "rag", "physics"), default="forecast")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--gemini-judge", action="store_true", help="opt in to paid Gemini relevance judgments")
    args = parser.parse_args(argv)
    if args.section == "forecast":
        report = evaluate_forecasts(args.data, args.models)
    elif args.section == "rl":
        report = evaluate_rl_logs(args.models)
    elif args.section == "rag":
        report = evaluate_rag(args.database, judge=args.gemini_judge)
    else:
        raise SystemExit("physics evaluation is not configured yet")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
