"""Small lazy Gemini adapter with an environment-configured fallback chain."""

from __future__ import annotations

import os
from typing import Callable, Iterable


class LLMUnavailableError(RuntimeError):
    """No configured model completed a request."""


def configured_models(environ=None) -> tuple[str, ...]:
    env = os.environ if environ is None else environ
    models = tuple(env.get(key, "").strip() for key in (
        "SWING_GEMINI_MODEL_PRIMARY",
        "SWING_GEMINI_MODEL_SECONDARY",
        "SWING_GEMINI_MODEL_TERTIARY",
    ))
    configured = tuple(model for model in models if model)
    if not configured:
        raise LLMUnavailableError("No Gemini model names are configured")
    if len(set(configured)) != len(configured):
        raise ValueError("Configured Gemini fallback model names must be distinct")
    return configured


def generate_with_fallback(prompt: str, *, models: Iterable[str] | None = None,
                           invoke: Callable[[str, str], str] | None = None) -> str:
    """Try configured model names in order; inject invoke for deterministic tests."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be non-empty text")
    candidates = tuple(models) if models is not None else configured_models()
    if not candidates or any(not isinstance(name, str) or not name.strip() for name in candidates):
        raise ValueError("at least one non-empty model name is required")

    if invoke is None:
        def invoke(model: str, text: str) -> str:
            from langchain_google_genai import ChatGoogleGenerativeAI
            response = ChatGoogleGenerativeAI(model=model, temperature=0).invoke(text)
            return str(response.content)

    failures = []
    for model in candidates:
        try:
            response = invoke(model, prompt)
            if not isinstance(response, str) or not response.strip():
                raise ValueError("model returned an empty response")
            return response
        except Exception as exc:  # Provider failures vary by SDK and quota class.
            failures.append(f"{model}:{type(exc).__name__}")
    raise LLMUnavailableError("All configured models failed (" + ", ".join(failures) + ")")
