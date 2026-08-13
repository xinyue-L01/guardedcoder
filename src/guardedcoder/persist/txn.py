from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

import sqlite3


@contextmanager
def write_txn(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
