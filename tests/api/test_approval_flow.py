"""Approval endpoints validate freshness and execute each proposal at most once."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from modules.ai_agents import agent_api, proposal_store


class TwinStub:
    def __init__(self, *, changed=False, failure=False):
        self.changed = changed
        self.failure = failure
        self.mutations = []

    def grid_status(self, grid):
        return {
            "capacity_max_mw": 101.0 if self.changed else 100.0,
            "resilience": {"collapsed": False},
            "security": {"overloaded_line_count": 1},
            "bus_loads": {"1": 20.0},
        }

    def topology(self, grid):
        return {"nodes": [{"id": "1"}]}

    def validate(self, grid, payload):
        return {"valid": True}

    def change_load(self, grid, bus_id, new_mw):
        self.mutations.append((grid, bus_id, new_mw))
        if self.failure:
            raise RuntimeError("Twin unavailable")
        return {"status": "ok", "new_mw": new_mw}


def setup(monkeypatch, tmp_path, twin):
    monkeypatch.setattr(proposal_store, "runtime_paths", lambda: SimpleNamespace(event_db=tmp_path / "events.sqlite"))
    monkeypatch.setattr(agent_api, "runtime_settings", lambda: SimpleNamespace(proposal_ttl_seconds=300, agent_bind_host="127.0.0.1"))
    monkeypatch.setattr(agent_api, "TwinClient", lambda: twin)
    monkeypatch.setattr(agent_api, "log_event", lambda *args, **kwargs: None)
    snapshot = {
        "capacity_max_mw": 100.0,
        "situation": {
            "available": True,
            "capacity_max_mw": 100.0,
            "resilience": {"collapsed": False},
            "security": {"overloaded_line_count": 1},
            "bus_loads": {"1": 20.0},
        },
        "forecast_bounds": {"p90_1h": 98.0},
        "topology": {"nodes": [{"id": "1"}]},
    }
    monkeypatch.setattr(agent_api, "configure_graph_runner", lambda runner: None)
    monkeypatch.setattr(agent_api, "_graph_runner", lambda grid, payload: {
        "decision": "PENDING_OPERATOR_APPROVAL",
        "proposed_action": {"action_type": "SHED_LOAD", "target_bus": 1, "mw_amount": 3.0, "justification": "validated"},
        "validation": {"valid": True},
        "snapshot": snapshot,
    })
    return TestClient(agent_api.app)


def test_missing_rejected_stale_and_single_execution(monkeypatch, tmp_path):
    twin = TwinStub()
    client = setup(monkeypatch, tmp_path, twin)
    absent = client.post("/execute/118", json={"proposal_id": "00000000-0000-0000-0000-000000000000"}, headers={"Idempotency-Key": "request-000"})
    assert absent.status_code == 404

    proposal = client.post("/propose/118", json={}).json()
    proposal_id = proposal["proposal_id"]
    rejected = client.post(f"/reject/118/{proposal_id}")
    assert rejected.status_code == 200
    denied = client.post("/execute/118", json={"proposal_id": proposal_id}, headers={"Idempotency-Key": "request-001"})
    assert denied.status_code == 409
    assert twin.mutations == []

    fresh = client.post("/propose/118", json={}).json()
    body = {"proposal_id": fresh["proposal_id"]}
    headers = {"Idempotency-Key": "request-002"}
    executed = client.post("/execute/118", json=body, headers=headers)
    replay = client.post("/execute/118", json=body, headers=headers)
    assert executed.status_code == 200
    assert replay.json()["replayed"] is True
    assert twin.mutations == [("118", 1, 17.0)]


def test_stale_and_failed_twin_actions_never_repeat(monkeypatch, tmp_path):
    stale_twin = TwinStub(changed=True)
    client = setup(monkeypatch, tmp_path, stale_twin)
    proposal = client.post("/propose/118", json={}).json()
    response = client.post("/execute/118", json={"proposal_id": proposal["proposal_id"]}, headers={"Idempotency-Key": "request-003"})
    assert response.status_code == 409
    assert stale_twin.mutations == []

    failed_twin = TwinStub(failure=True)
    client = setup(monkeypatch, tmp_path / "failure", failed_twin)
    proposal = client.post("/propose/118", json={}).json()
    body = {"proposal_id": proposal["proposal_id"]}
    headers = {"Idempotency-Key": "request-004"}
    assert client.post("/execute/118", json=body, headers=headers).status_code == 502
    assert client.post("/execute/118", json=body, headers=headers).status_code == 409
    assert len(failed_twin.mutations) == 1
