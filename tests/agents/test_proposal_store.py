"""Proposal lifecycle is durable, grid scoped, expiring and one way."""

from modules.ai_agents.proposal_store import create_pending, get_proposal, transition


def test_pending_approval_execution_survives_store_reopen(tmp_path):
    database = tmp_path / "agent.sqlite"
    proposal = create_pending("39", {"version": 1}, {"action_type": "SHED_LOAD"}, path=database, now=100)
    proposal_id = proposal["proposal_id"]
    assert get_proposal(proposal_id, path=database, now=101)["status"] == "pending"
    assert transition(proposal_id, "pending", "approved", path=database, now=102)
    assert get_proposal(proposal_id, path=database, now=103)["status"] == "approved"
    assert transition(proposal_id, "approved", "executing", path=database, now=104, idempotency_key="once")
    assert transition(proposal_id, "executing", "executed", path=database, now=105)
    assert get_proposal(proposal_id, path=database, now=106)["status"] == "executed"
    assert not transition(proposal_id, "approved", "executing", path=database, now=106)


def test_rejected_expired_and_grid_isolation(tmp_path):
    database = tmp_path / "agent.sqlite"
    rejected = create_pending("39", {}, {"action_type": "NO_ACTION"}, path=database, now=100)
    other_grid = create_pending("118", {}, {"action_type": "NO_ACTION"}, path=database, now=100)
    expires = create_pending("39", {}, {"action_type": "NO_ACTION"}, path=database, now=100, ttl_seconds=5)
    assert transition(rejected["proposal_id"], "pending", "rejected", path=database, now=101)
    assert get_proposal(rejected["proposal_id"], path=database, now=102)["status"] == "rejected"
    assert get_proposal(other_grid["proposal_id"], path=database, now=102)["grid_id"] == "118"
    assert get_proposal(expires["proposal_id"], path=database, now=106)["status"] == "expired"
    assert not transition(expires["proposal_id"], "pending", "approved", path=database, now=106)
