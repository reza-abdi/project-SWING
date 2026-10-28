"""Two local services can write and read one WAL-backed SQLite file."""

import multiprocessing
import sqlite3

from modules.ai_agents.proposal_store import create_pending, get_proposal
from modules.event_store import _connect, get_events, log_event


def _write_events(database, source):
    for index in range(12):
        log_event(source, "39", "TEST", {"index": index}, db_path=database)


def _write_proposal(database, output):
    record = create_pending("118", {"version": 1}, {"action_type": "NO_ACTION"}, path=database)
    output.put(record["proposal_id"])


def test_event_and_proposal_services_share_wal_database(tmp_path):
    database = str(tmp_path / "shared.sqlite")
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    writer = context.Process(target=_write_events, args=(database, "digital_twin"))
    proposal_writer = context.Process(target=_write_proposal, args=(database, output))
    writer.start()
    proposal_writer.start()
    writer.join(timeout=20)
    proposal_writer.join(timeout=20)
    assert writer.exitcode == 0
    assert proposal_writer.exitcode == 0
    proposal_id = output.get(timeout=2)
    assert get_proposal(proposal_id, path=database)["grid_id"] == "118"
    events = get_events(grid_id="39", source="digital_twin", limit=20, db_path=database)
    assert len(events) == 12
    assert [event["payload"]["index"] for event in events] == list(reversed(range(12)))
    connection = sqlite3.connect(database)
    event_connection = _connect(database)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert event_connection.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
    finally:
        connection.close()
        event_connection.close()
