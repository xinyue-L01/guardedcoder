from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    run_state TEXT NOT NULL,
    artifact_state TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    worktree_identity TEXT NOT NULL,
    envelope_hash TEXT NOT NULL,
    state_revision INTEGER NOT NULL,
    remaining_steps INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS envelope_versions (
    envelope_hash TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    snapshot_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    pending_action_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    fingerprint TEXT NOT NULL,
    normalized_action_json TEXT NOT NULL,
    state_revision INTEGER NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_unconsumed
    ON pending_actions(task_id) WHERE consumed = 0;

CREATE TABLE IF NOT EXISTS permits (
    permit_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    action_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    envelope_hash TEXT NOT NULL,
    state_revision INTEGER NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,
    pending_action_id TEXT REFERENCES pending_actions(pending_action_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_permit_unconsumed
    ON permits(task_id) WHERE consumed = 0;

CREATE TABLE IF NOT EXISTS execution_windows (
    window_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    permit_id TEXT NOT NULL REFERENCES permits(permit_id),
    action_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    preimage_json TEXT,
    postimage_json TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_window_active
    ON execution_windows(task_id)
    WHERE status IN ('executing_action', 'applying');

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30.0)
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn
