from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from guardedcoder.persist.txn import write_txn

_KEY_SHAPED = re.compile(r"sk-[A-Za-z0-9_-]+")


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _KEY_SHAPED.sub("[redacted]", value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def append_audit(conn: sqlite3.Connection, task_id: str, event: dict) -> None:
    payload = json.dumps(_redact(event), ensure_ascii=False)
    with write_txn(conn):
        conn.execute(
            "INSERT INTO audit_events (event_id, task_id, payload_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                task_id,
                payload,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
