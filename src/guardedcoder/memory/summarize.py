from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable

from guardedcoder.memory.store import (
    MemoryType,
    MemoryValidationError,
    add_task_summary,
    list_records,
    normalize_paths,
    reject_secret_text,
)
from guardedcoder.persist.txn import write_txn

_MAX_TASK_SUMMARIES = 100
_MAX_SUMMARY_AGE = timedelta(days=90)


def _looks_like_diff(value: str) -> bool:
    return "diff --git" in value or "\n@@ " in value or value.startswith("@@ ")


def _checked_field(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str")
    text = value.strip()
    if not text:
        raise MemoryValidationError(f"{field} must not be empty")
    if _looks_like_diff(text):
        raise MemoryValidationError("task summary rejected: diff content")
    reject_secret_text(text)
    return text


def build_task_summary(
    *,
    task_id: str,
    base_commit: str,
    final_state: str,
    changed_paths: Iterable[str],
    verdict: str,
    failure_category: str | None = None,
    approval_summary: str | None = None,
) -> str:
    payload = {
        "approval_summary": _checked_field("approval_summary", approval_summary),
        "base_commit": _checked_field("base_commit", base_commit),
        "changed_paths": list(normalize_paths(changed_paths)),
        "failure_category": _checked_field("failure_category", failure_category),
        "final_state": _checked_field("final_state", final_state),
        "task_id": _checked_field("task_id", task_id),
        "verdict": _checked_field("verdict", verdict),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def gc_task_summaries(
    conn: sqlite3.Connection,
    repo_id: str,
    *,
    now: datetime | None = None,
) -> int:
    when = now or datetime.now(timezone.utc)
    if not isinstance(when, datetime):
        raise TypeError("now must be datetime")
    if when.tzinfo is None or when.utcoffset() is None:
        raise MemoryValidationError("now must be timezone-aware")
    when = when.astimezone(timezone.utc)
    cutoff = when - _MAX_SUMMARY_AGE
    with write_txn(conn):
        records = list_records(
            conn,
            repo_id,
            record_types=(MemoryType.TASK_SUMMARY,),
            status=None,
        )
        aged_in = [record for record in records if record.created_at >= cutoff]
        aged_in.sort(
            key=lambda record: (record.created_at, record.record_id), reverse=True
        )
        keep_ids = {record.record_id for record in aged_in[:_MAX_TASK_SUMMARIES]}
        drop_ids = [
            record.record_id for record in records if record.record_id not in keep_ids
        ]
        if not drop_ids:
            return 0
        normalized_repo = records[0].repo_id
        conn.execute(
            "DELETE FROM memory_records WHERE repo_id = ? AND record_id IN ("
            + ", ".join("?" for _ in drop_ids)
            + ")",
            (normalized_repo, *drop_ids),
        )
    return len(drop_ids)


__all__ = ["add_task_summary", "build_task_summary", "gc_task_summaries"]
