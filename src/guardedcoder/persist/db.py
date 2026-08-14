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

CREATE UNIQUE INDEX IF NOT EXISTS idx_permit_pending
    ON permits(pending_action_id) WHERE pending_action_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS execution_windows (
    window_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    permit_id TEXT REFERENCES permits(permit_id),
    action_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    preimage_json TEXT,
    postimage_json TEXT,
    opened_revision INTEGER NOT NULL,
    source_run_state TEXT NOT NULL,
    fingerprint TEXT,
    execution_started INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_window_active
    ON execution_windows(task_id)
    WHERE status IN ('executing_action', 'applying');

CREATE TABLE IF NOT EXISTS recovered_attempt_claims (
    claim_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    window_id TEXT NOT NULL REFERENCES execution_windows(window_id),
    state_revision INTEGER NOT NULL,
    attempt_id TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_recovered_claim_exclusive
    ON recovered_attempt_claims(task_id, window_id, state_revision);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_records (
    record_id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    content TEXT NOT NULL,
    rationale TEXT,
    paths_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    trust_label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supersedes_id TEXT REFERENCES memory_records(record_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_repo_status_type
    ON memory_records(repo_id, status, record_type);

CREATE INDEX IF NOT EXISTS idx_memory_repo_created
    ON memory_records(repo_id, created_at, record_id);

CREATE TABLE IF NOT EXISTS task_runtime (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    task_description TEXT NOT NULL DEFAULT '',
    observations_json TEXT NOT NULL DEFAULT '[]',
    memories_json TEXT NOT NULL DEFAULT '[]'
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30.0)
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migrate_execution_windows(conn)
    _migrate_recovered_claims(conn)
    return conn


def _migrate_execution_windows(conn: sqlite3.Connection) -> None:
    info = list(conn.execute("PRAGMA table_info(execution_windows)"))
    if not info:
        return
    cols = {row[1]: row for row in info}
    if "opened_revision" not in cols:
        conn.execute(
            "ALTER TABLE execution_windows ADD COLUMN opened_revision INTEGER"
        )
    if "source_run_state" not in cols:
        conn.execute(
            "ALTER TABLE execution_windows ADD COLUMN source_run_state TEXT"
        )
    if "fingerprint" not in cols:
        conn.execute("ALTER TABLE execution_windows ADD COLUMN fingerprint TEXT")
    if "execution_started" not in cols:
        conn.execute(
            "ALTER TABLE execution_windows ADD COLUMN execution_started INTEGER "
            "NOT NULL DEFAULT 0"
        )
    info = list(conn.execute("PRAGMA table_info(execution_windows)"))
    cols = {row[1]: row for row in info}
    permit = cols.get("permit_id")
    if permit is not None and permit[3]:
        _rebuild_execution_windows_permit_nullable(conn)


def _rebuild_execution_windows_permit_nullable(conn: sqlite3.Connection) -> None:
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_window_active")
        conn.execute(
            """
            CREATE TABLE execution_windows_new (
                window_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                permit_id TEXT REFERENCES permits(permit_id),
                action_kind TEXT NOT NULL,
                status TEXT NOT NULL,
                preimage_json TEXT,
                postimage_json TEXT,
                opened_revision INTEGER NOT NULL,
                source_run_state TEXT NOT NULL,
                fingerprint TEXT,
                execution_started INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        legacy = {
            row[1] for row in conn.execute("PRAGMA table_info(execution_windows)")
        }
        dest = (
            "window_id",
            "task_id",
            "permit_id",
            "action_kind",
            "status",
            "preimage_json",
            "postimage_json",
            "opened_revision",
            "source_run_state",
            "fingerprint",
            "execution_started",
        )
        copied: list[str] = []
        selected: list[str] = []
        for name in dest:
            if name not in legacy:
                continue
            copied.append(name)
            if name == "opened_revision":
                selected.append("COALESCE(opened_revision, 0)")
            elif name == "source_run_state":
                selected.append("COALESCE(source_run_state, '')")
            else:
                selected.append(name)
        conn.execute(
            f"INSERT INTO execution_windows_new ({', '.join(copied)}) "
            f"SELECT {', '.join(selected)} FROM execution_windows"
        )
        conn.execute("DROP TABLE execution_windows")
        conn.execute("ALTER TABLE execution_windows_new RENAME TO execution_windows")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_window_active "
            "ON execution_windows(task_id) "
            "WHERE status IN ('executing_action', 'applying')"
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        if foreign_keys_enabled:
            conn.execute("PRAGMA foreign_keys = ON")
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    if violations:
        raise sqlite3.IntegrityError("execution window migration broke foreign keys")


def _migrate_recovered_claims(conn: sqlite3.Connection) -> None:
    columns = [
        row[2] for row in conn.execute("PRAGMA index_info(idx_recovered_claim_exclusive)")
    ]
    if columns == ["task_id", "window_id", "state_revision"]:
        return
    conn.execute("DROP INDEX IF EXISTS idx_recovered_claim_exclusive")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_recovered_claim_exclusive "
        "ON recovered_attempt_claims(task_id, window_id, state_revision)"
    )
