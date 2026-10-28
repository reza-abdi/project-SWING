"""HTTP-only client for the independently hosted Digital Twin service."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import requests

from modules.config import runtime_settings


class TwinClientError(RuntimeError):
    """The Twin service could not provide a valid response."""


class TwinClient:
    """Typed route methods over requests; this module has no physics imports."""

    def __init__(self, base_url: str | None = None, *, timeout_seconds: float = 10.0, session=None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        target = (base_url or runtime_settings().twin_api_url).rstrip("/")
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("base_url must be a valid HTTP(S) URL without credentials")
        self.base_url = target
        self.timeout_seconds = float(timeout_seconds)
        self.session = session or requests.Session()

    def _request(self, method: str, path: str, *, params=None, json_body=None) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json_body,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise TwinClientError(f"Twin {method} {path} request failed") from exc
        except ValueError as exc:
            raise TwinClientError(f"Twin {method} {path} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TwinClientError(f"Twin {method} {path} returned a non-object response")
        return payload

    @staticmethod
    def _grid(grid: str) -> str:
        if grid not in {"39", "118"}:
            raise ValueError("grid must be '39' or '118'")
        return grid

    def grid_status(self, grid: str) -> dict[str, Any]:
        return self._request("GET", "/grid_status", params={"grid": self._grid(grid)})

    def topology(self, grid: str) -> dict[str, Any]:
        return self._request("GET", "/topology", params={"grid": self._grid(grid)})

    def contingency(self, grid: str) -> dict[str, Any]:
        return self._request("GET", f"/contingency/{self._grid(grid)}")

    def optimize(self, grid: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/optimize_action/{self._grid(grid)}", json_body=payload)

    def validate(self, grid: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/validate_action/{self._grid(grid)}", json_body=payload)

    def change_load(self, grid: str, bus_id: int, new_mw: float) -> dict[str, Any]:
        return self._request("POST", f"/change_load/{bus_id}", params={"new_mw": new_mw, "grid": self._grid(grid)})

    def redispatch_gen(self, grid: str, bus_id: int, delta_mw: float) -> dict[str, Any]:
        return self._request("POST", f"/redispatch_gen/{bus_id}", params={"delta_mw": delta_mw, "grid": self._grid(grid)})

    def redistribute_load(self, grid: str, source_bus: int, destination_bus: int, mw_amount: float) -> dict[str, Any]:
        return self._request("POST", f"/redistribute_load/{self._grid(grid)}", params={
            "source_bus": source_bus, "destination_bus": destination_bus, "mw_amount": mw_amount,
        })

    def inject_fault(self, grid: str, line_id: int) -> dict[str, Any]:
        return self._request("POST", f"/inject_fault/{line_id}", params={"grid": self._grid(grid)})

    def restore_line(self, grid: str, line_id: int) -> dict[str, Any]:
        return self._request("POST", f"/restore_line/{self._grid(grid)}/{line_id}")
