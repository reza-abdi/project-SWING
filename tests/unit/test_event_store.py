"""Durability and filtering tests for SQLite simulation events."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.event_store import get_events, initialize_database, log_event


def test_schema_and_empty_queries(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    initialize_database(database)

    assert get_events(db_path=database) == []
    assert get_events(grid_id="39", source="digital_twin", db_path=database) == []


def test_source_and_grid_filters_and_persistent_reopen(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    log_event("digital_twin", "39", "BASELINE", {"converged": True}, database)
    log_event("ai_agent", "39", "PROPOSAL", {"proposal_id": "p1"}, database)
    log_event("digital_twin", "118", "FAULT", {"line": 3}, database)

    assert len(get_events(grid_id="39", db_path=database)) == 2
    twin_events = get_events(source="digital_twin", db_path=database)
    assert {event["grid_id"] for event in twin_events} == {"39", "118"}
    assert get_events(grid_id="39", source="missing", db_path=database) == []
    assert get_events(limit=1, db_path=database)[0]["event_type"] == "FAULT"

    reopened = get_events(db_path=database)
    assert len(reopened) == 3
    assert reopened[0]["payload"] == {"line": 3}


def test_concurrent_writes_are_all_persisted(tmp_path) -> None:
    database = tmp_path / "events.sqlite"

    def write_event(index: int) -> None:
        log_event("digital_twin", "39", "CONCURRENT", {"index": index}, database)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write_event, range(32)))

    events = get_events(source="digital_twin", grid_id="39", limit=40, db_path=database)
    assert len(events) == 32
    assert {event["payload"]["index"] for event in events} == set(range(32))


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_limits_are_rejected(limit, tmp_path) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        get_events(limit=limit, db_path=tmp_path / "events.sqlite")


def test_payload_must_be_json_object(tmp_path) -> None:
    with pytest.raises(TypeError, match="dictionary"):
        log_event("digital_twin", "39", "BAD", [], tmp_path / "events.sqlite")
