"""Cross-service proposal flow with isolated proposal storage and stubbed providers."""

from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from modules.ai_agents import agent_api, proposal_store
from modules.ai_agents.twin_client import TwinClient
from modules.physics_engine import api as twin_api


class TestClientSession:
    """Adapt Twin's in-process ASGI test client to the requests.Session interface."""

    def __init__(self, client):
        self.client = client

    def request(self, method, url, *, params=None, json=None, timeout=None):
        headers = {"Authorization": "Bearer integration-admin"}
        return self.client.request(method, urlsplit(url).path, params=params, json=json, headers=headers)


def test_propose_validate_approve_execute_across_services(monkeypatch, tmp_path):
    monkeypatch.setenv("SWING_AUTH_MODE", "reverse_proxy")
    monkeypatch.setenv("SWING_OPERATOR_TOKEN", "integration-operator")
    monkeypatch.setenv("SWING_ADMIN_TOKEN", "integration-admin")
    monkeypatch.setenv("SWING_ALLOWED_ORIGINS", "https://integration.example")
    monkeypatch.setattr(proposal_store, "runtime_paths", lambda: SimpleNamespace(event_db=tmp_path / "proposals.sqlite"))
    monkeypatch.setattr(agent_api, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(twin_api, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent_api, "generate_with_fallback", lambda _prompt: '{"action_type":"NO_ACTION","justification":"stub"}')

    with TestClient(twin_api.app) as twin_http:
        twin = TwinClient("http://twin.test", session=TestClientSession(twin_http))
        status = twin.grid_status("39")
        topology = twin.topology("39")
        bus = int(next(key for key, value in status["bus_loads"].items() if value > 0))
        amount = 0.1
        snapshot = {
            "capacity_max_mw": float(status["capacity_max_mw"]),
            "situation": {
                "available": True,
                "capacity_max_mw": float(status["capacity_max_mw"]),
                "resilience": status["resilience"], "security": status["security"],
                "bus_loads": status["bus_loads"],
            },
            "forecast_bounds": {}, "topology": topology,
        }
        monkeypatch.setattr(agent_api, "TwinClient", lambda: twin)
        monkeypatch.setattr(agent_api, "_graph_runner", lambda grid, payload: {
            "decision": "PENDING_OPERATOR_APPROVAL", "operator_brief": "validated proposal",
            "proposed_action": {"action_type": "SHED_LOAD", "target_bus": bus, "mw_amount": amount,
                                "justification": "integration fixture"},
            "validation": {"valid": True}, "snapshot": snapshot,
        })
        agent = TestClient(agent_api.app)
        headers = {"Authorization": "Bearer integration-operator"}
        proposed = agent.post("/propose/39", json={}, headers=headers)
        assert proposed.status_code == 200, proposed.text
        proposal_id = proposed.json()["proposal_id"]

        validated = twin.validate("39", {"action_type": "SHED_LOAD", "target_bus": bus, "mw_amount": amount})
        assert validated["valid"] is True
        approved = agent.post("/execute/39", json={"proposal_id": proposal_id},
                              headers={**headers, "Idempotency-Key": "integration-flow-0001"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "executed"
        assert twin_http.get("/grid_status", params={"grid": "39"}).json()["total_demand_mw"] < status["total_demand_mw"]
