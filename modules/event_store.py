"""SQLite storage primitives for the shared simulation event timeline."""

import sqlite3
from pathlib import Path

from modules.config import runtime_paths


DEFAULT_DB_PATH = runtime_paths().event_db


def _get_db_path(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    return sqlite3.connect(str(_get_db_path(db_path)), timeout=10.0)


def initialize_database(db_path: str | Path | None = None) -> None:
    """Create the initial event table and its grid/time lookup indexes."""
    with _connect(db_path) as connection:
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
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_grid ON events(grid_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
        )
