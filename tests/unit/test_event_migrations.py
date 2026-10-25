"""Schema migration tests for new and source-compatible event databases."""

import sqlite3

from modules.event_store import LATEST_SCHEMA_VERSION, initialize_database, migrate_database


def test_empty_database_migrates_idempotently(tmp_path) -> None:
    database = tmp_path / "new.sqlite"

    assert migrate_database(database) == LATEST_SCHEMA_VERSION
    assert migrate_database(database) == LATEST_SCHEMA_VERSION
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(events)")}
    assert {"idx_events_grid", "idx_events_timestamp"} <= indexes


def test_existing_source_schema_and_rows_are_preserved(tmp_path) -> None:
    database = tmp_path / "existing.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                source TEXT NOT NULL,
                grid_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO events (timestamp, source, grid_id, event_type, payload) "
            "VALUES (1.0, 'digital_twin', '39', 'BASELINE', '{}')"
        )

    assert migrate_database(database) == LATEST_SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT source, grid_id, event_type, payload FROM events"
        ).fetchone()
    assert row == ("digital_twin", "39", "BASELINE", "{}")
