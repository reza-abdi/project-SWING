"""SQLite storage primitives for the shared simulation event timeline."""

import sqlite3
from pathlib import Path

from modules.config import runtime_paths


DEFAULT_DB_PATH = runtime_paths().event_db
LATEST_SCHEMA_VERSION = 1


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
