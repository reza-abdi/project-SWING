"""SQLite persistence for individual, expiring operator proposals."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from modules.config import runtime_paths


def _database(path: str | Path | None = None) -> Path:
    result = Path(path) if path is not None else runtime_paths().event_db
    result.parent.mkdir(parents=True, exist_ok=True)
    return result


def _connect(path: str | Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(str(_database(path)), timeout=10.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def _connection(path: str | Path | None = None):
    connection = _connect(path)
    try:
        yield connection
    finally:
        connection.close()


def initialize(path: str | Path | None = None) -> None:
    with _connection(path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS agent_proposals (
                proposal_id TEXT PRIMARY KEY,
                grid_id TEXT NOT NULL CHECK (grid_id IN ('39', '118')),
                snapshot_hash TEXT NOT NULL,
                action_json TEXT NOT NULL,
                creator TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','expired','executing','executed','stale')),
                idempotency_key TEXT
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_agent_proposals_expiry ON agent_proposals(expires_at)")


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_pending(grid_id: str, snapshot: dict[str, Any], action: dict[str, Any], *,
                   creator: str = "local", ttl_seconds: int = 300,
                   now: float | None = None, path: str | Path | None = None) -> dict[str, Any]:
    if grid_id not in {"39", "118"}:
        raise ValueError("grid_id must be '39' or '118'")
    if not isinstance(action, dict) or not isinstance(snapshot, dict):
        raise TypeError("snapshot and action must be objects")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be a positive integer")
    created = time.time() if now is None else float(now)
    proposal_id = str(uuid.uuid4())
    digest = snapshot_digest(snapshot)
    initialize(path)
    with _connection(path) as connection:
        connection.execute("""
            INSERT INTO agent_proposals
            (proposal_id, grid_id, snapshot_hash, action_json, creator, created_at, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (proposal_id, grid_id, digest, json.dumps(action, sort_keys=True, allow_nan=False),
              str(creator)[:120], created, created + ttl_seconds))
    return get_proposal(proposal_id, now=created, path=path)


def get_proposal(proposal_id: str, *, now: float | None = None, path: str | Path | None = None) -> dict[str, Any] | None:
    current = time.time() if now is None else float(now)
    initialize(path)
    with _connection(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            UPDATE agent_proposals SET status='expired'
            WHERE proposal_id=? AND status IN ('pending','approved') AND expires_at<=?
        """, (proposal_id, current))
        row = connection.execute("SELECT * FROM agent_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        connection.commit()
    if row is None:
        return None
    result = dict(row)
    result["action"] = json.loads(result.pop("action_json"))
    return result


def transition(proposal_id: str, expected: str, target: str, *, now: float | None = None,
               idempotency_key: str | None = None, path: str | Path | None = None) -> bool:
    current = time.time() if now is None else float(now)
    if target not in {"approved", "rejected", "executing", "executed", "stale"}:
        raise ValueError("unsupported proposal transition")
    initialize(path)
    with _connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            UPDATE agent_proposals SET status='expired'
            WHERE proposal_id=? AND status=? AND expires_at<=?
        """, (proposal_id, expected, current))
        cursor = connection.execute("""
            UPDATE agent_proposals SET status=?, idempotency_key=COALESCE(?, idempotency_key)
            WHERE proposal_id=? AND status=? AND expires_at>?
        """, (target, idempotency_key, proposal_id, expected, current))
        connection.commit()
        return cursor.rowcount == 1
