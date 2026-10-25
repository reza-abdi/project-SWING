"""SQLite storage primitives for the shared simulation event timeline."""

import sqlite3
import json
import logging
import math
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from modules.config import runtime_paths


DEFAULT_DB_PATH = runtime_paths().event_db
LATEST_SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


def _get_db_path(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    return sqlite3.connect(str(_get_db_path(db_path)), timeout=10.0)


def _migrate_to_v1(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            source TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_events_grid ON events(grid_id)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
    )


_MIGRATIONS = {1: _migrate_to_v1}


def migrate_database(db_path: str | Path | None = None) -> int:
    """Apply each missing schema migration once, preserving existing event rows."""
    connection = sqlite3.connect(str(_get_db_path(db_path)), timeout=10.0)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than supported version "
                f"{LATEST_SCHEMA_VERSION}"
            )
        while version < LATEST_SCHEMA_VERSION:
            next_version = version + 1
            migration = _MIGRATIONS[next_version]
            connection.execute("BEGIN IMMEDIATE")
            try:
                migration(connection)
                connection.execute(f"PRAGMA user_version = {next_version}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            version = next_version
        return version
    finally:
        connection.close()


def initialize_database(db_path: str | Path | None = None) -> None:
    """Create or upgrade the event database to the latest supported schema."""
    migrate_database(db_path)


def log_event(
    source: str,
    grid_id: str,
    event_type: str,
    payload: dict[str, Any],
    db_path: str | Path | None = None,
) -> None:
    """Append one JSON event; keep event-store outages from stopping simulation."""
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary")
    try:
        serialized_payload = json.dumps(payload, default=str, allow_nan=False)
        initialize_database(db_path)
        with closing(_connect(db_path)) as connection, connection:
            connection.execute(
                """INSERT INTO events (timestamp, source, grid_id, event_type, payload)
                   VALUES (?, ?, ?, ?, ?)""",
                (time.time(), source, grid_id, event_type, serialized_payload),
            )
    except sqlite3.Error:
        logger.exception("Could not persist event for source %s", source)


def get_events(
    grid_id: str | None = None,
    source: str | None = None,
    limit: int = 100,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return newest events first, optionally filtered by grid and source."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    initialize_database(db_path)
    query = "SELECT timestamp, source, grid_id, event_type, payload FROM events WHERE 1=1"
    parameters: list[Any] = []
    if grid_id is not None:
        query += " AND grid_id = ?"
        parameters.append(grid_id)
    if source is not None:
        query += " AND source = ?"
        parameters.append(source)
    query += " ORDER BY timestamp DESC, id DESC LIMIT ?"
    parameters.append(limit)

    with closing(_connect(db_path)) as connection:
        rows = connection.execute(query, parameters).fetchall()
    events = []
    for timestamp, event_source, event_grid, event_type, payload in rows:
        decoded_payload = json.loads(payload)
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("stored event timestamp is invalid")
        events.append(
            {
                "timestamp": timestamp,
                "source": event_source,
                "grid_id": event_grid,
                "event_type": event_type,
                "payload": decoded_payload,
            }
        )
    return events
