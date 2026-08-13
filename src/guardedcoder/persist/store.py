from __future__ import annotations

import sqlite3

from guardedcoder.errors import StaleRevisionError

_TASK_FIELDS = frozenset(
    {
        "run_state",
        "artifact_state",
        "repo_path",
        "base_commit",
        "worktree_identity",
        "envelope_hash",
        "remaining_steps",
    }
)


def create_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    run_state: str,
    artifact_state: str,
    repo_path: str,
    base_commit: str,
    worktree_identity: str,
    envelope_hash: str,
    remaining_steps: int,
) -> None:
    conn.execute(
        "INSERT INTO tasks ("
        "task_id, run_state, artifact_state, repo_path, base_commit, "
        "worktree_identity, envelope_hash, state_revision, remaining_steps"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (
            task_id,
            run_state,
            artifact_state,
            repo_path,
            base_commit,
            worktree_identity,
            envelope_hash,
            remaining_steps,
        ),
    )


def update_task(
    conn: sqlite3.Connection,
    task_id: str,
    expected_revision: int,
    **fields: object,
) -> None:
    unknown = set(fields) - _TASK_FIELDS
    if unknown:
        raise TypeError(f"unknown task fields: {sorted(unknown)}")
    assignments = [f"{name} = ?" for name in fields]
    assignments.append("state_revision = state_revision + 1")
    sql = (
        f"UPDATE tasks SET {', '.join(assignments)} "
        "WHERE task_id = ? AND state_revision = ?"
    )
    cur = conn.execute(sql, [*fields.values(), task_id, expected_revision])
    if cur.rowcount == 0:
        raise StaleRevisionError(
            f"stale revision for task {task_id}: expected {expected_revision}"
        )
