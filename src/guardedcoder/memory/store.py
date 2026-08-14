from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from guardedcoder.persist.txn import write_txn

_MAX_REPO_ID_LENGTH = 512
_MAX_CONTENT_LENGTH = 16_384
_MAX_RATIONALE_LENGTH = 8_192
_MAX_SOURCE_LENGTH = 256
_MAX_PATH_LENGTH = 1_024
_MAX_TAG_LENGTH = 128

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9_./+=-]{12,}"
    ),
)

_SELECT_COLUMNS = (
    "record_id, repo_id, record_type, content, rationale, paths_json, "
    "tags_json, source, status, trust_label, created_at, supersedes_id"
)


class MemoryType(StrEnum):
    PROJECT_CONSTRAINT = "project_constraint"
    DECISION = "decision"
    TASK_SUMMARY = "task_summary"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class TrustLabel(StrEnum):
    USER_PROVIDED = "user_provided"
    HARNESS_GENERATED = "harness_generated"


class MemoryValidationError(ValueError):
    """Raised when a memory field is malformed or may contain a secret."""


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    record_id: str
    repo_id: str
    record_type: MemoryType
    content: str
    rationale: str | None
    paths: tuple[str, ...]
    tags: tuple[str, ...]
    source: str
    status: MemoryStatus
    trust_label: TrustLabel
    created_at: datetime
    supersedes_id: str | None


def _contains_suspected_secret(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _SECRET_PATTERNS)


def _validated_text(
    field: str,
    value: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise MemoryValidationError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise MemoryValidationError(f"{field} is too long")
    if _contains_suspected_secret(normalized):
        raise MemoryValidationError("memory field rejected: suspected secret")
    return normalized


def _validated_repo_id(repo_id: str) -> str:
    return _validated_text(
        "repo_id",
        repo_id,
        max_length=_MAX_REPO_ID_LENGTH,
    )


def _require_str_sequence(field: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be list[str] or tuple[str, ...]")
    if not all(isinstance(item, str) for item in value):
        raise TypeError(f"{field} items must be str")
    return value


def _is_absolute_memory_path(item: str) -> bool:
    if item.startswith("/") or item.startswith("//"):
        return True
    if len(item) >= 2 and item[1] == ":":
        return True
    return Path(item).is_absolute()


def normalize_paths(paths: object) -> tuple[str, ...]:
    normalized: set[str] = set()
    for path in _require_str_sequence("paths", paths):
        item = _validated_text("path", path, max_length=_MAX_PATH_LENGTH)
        item = item.replace("\\", "/")
        if item == ".":
            normalized.add(item)
            continue
        if _is_absolute_memory_path(item):
            raise MemoryValidationError("path must be a normalized repository-relative path")
        item = item.strip("/")
        parts = item.split("/")
        if not item or any(part in {"", ".", ".."} for part in parts):
            raise MemoryValidationError("path must be a normalized repository-relative path")
        normalized.add(item)
    return tuple(sorted(normalized))


def normalize_tags(tags: object) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _validated_text("tag", tag, max_length=_MAX_TAG_LENGTH).casefold()
                for tag in _require_str_sequence("tags", tags)
            }
        )
    )


def _normalized_time(created_at: datetime | None) -> datetime:
    value = created_at or datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("created_at must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryValidationError("created_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _time_to_text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _time_from_text(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _prepare_record(
    *,
    repo_id: str,
    record_type: MemoryType,
    content: str,
    rationale: str | None,
    paths: Iterable[str],
    tags: Iterable[str],
    source: str,
    trust_label: TrustLabel,
    created_at: datetime | None,
    supersedes_id: str | None = None,
) -> MemoryRecord:
    normalized_rationale = (
        None
        if rationale is None
        else _validated_text(
            "rationale",
            rationale,
            max_length=_MAX_RATIONALE_LENGTH,
            allow_empty=True,
        )
    )
    return MemoryRecord(
        record_id=str(uuid.uuid4()),
        repo_id=_validated_repo_id(repo_id),
        record_type=record_type,
        content=_validated_text(
            "content",
            content,
            max_length=_MAX_CONTENT_LENGTH,
        ),
        rationale=normalized_rationale,
        paths=normalize_paths(paths),
        tags=normalize_tags(tags),
        source=_validated_text(
            "source",
            source,
            max_length=_MAX_SOURCE_LENGTH,
        ),
        status=MemoryStatus.ACTIVE,
        trust_label=trust_label,
        created_at=_normalized_time(created_at),
        supersedes_id=supersedes_id,
    )


def _insert_record(conn: sqlite3.Connection, record: MemoryRecord) -> None:
    conn.execute(
        "INSERT INTO memory_records ("
        "record_id, repo_id, record_type, content, rationale, paths_json, "
        "tags_json, source, status, trust_label, created_at, supersedes_id"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.record_id,
            record.repo_id,
            record.record_type,
            record.content,
            record.rationale,
            json.dumps(record.paths, ensure_ascii=False, separators=(",", ":")),
            json.dumps(record.tags, ensure_ascii=False, separators=(",", ":")),
            record.source,
            record.status,
            record.trust_label,
            _time_to_text(record.created_at),
            record.supersedes_id,
        ),
    )


def add_constraint(
    conn: sqlite3.Connection,
    *,
    repo_id: str,
    content: str,
    paths: Iterable[str] = (),
    tags: Iterable[str] = (),
    source: str = "user-cli",
    created_at: datetime | None = None,
) -> MemoryRecord:
    record = _prepare_record(
        repo_id=repo_id,
        record_type=MemoryType.PROJECT_CONSTRAINT,
        content=content,
        rationale=None,
        paths=paths,
        tags=tags,
        source=source,
        trust_label=TrustLabel.USER_PROVIDED,
        created_at=created_at,
    )
    with write_txn(conn):
        _insert_record(conn, record)
    return record


def add_decision(
    conn: sqlite3.Connection,
    *,
    repo_id: str,
    content: str,
    rationale: str | None = None,
    paths: Iterable[str] = (),
    tags: Iterable[str] = (),
    source: str = "user-cli",
    supersedes: str | None = None,
    created_at: datetime | None = None,
) -> MemoryRecord:
    normalized_supersedes = (
        None
        if supersedes is None
        else _validated_text("supersedes", supersedes, max_length=128)
    )
    record = _prepare_record(
        repo_id=repo_id,
        record_type=MemoryType.DECISION,
        content=content,
        rationale=rationale,
        paths=paths,
        tags=tags,
        source=source,
        trust_label=TrustLabel.USER_PROVIDED,
        created_at=created_at,
        supersedes_id=normalized_supersedes,
    )
    with write_txn(conn):
        if normalized_supersedes is not None:
            old = conn.execute(
                "SELECT repo_id, record_type, status FROM memory_records "
                "WHERE record_id = ?",
                (normalized_supersedes,),
            ).fetchone()
            if old != (
                record.repo_id,
                MemoryType.DECISION,
                MemoryStatus.ACTIVE,
            ):
                raise MemoryValidationError(
                    "supersedes must reference an active decision in the same repo"
                )
            conn.execute(
                "UPDATE memory_records SET status = ? WHERE record_id = ?",
                (MemoryStatus.SUPERSEDED, normalized_supersedes),
            )
        _insert_record(conn, record)
    return record


def add_task_summary(
    conn: sqlite3.Connection,
    *,
    repo_id: str,
    content: str,
    paths: Iterable[str] = (),
    tags: Iterable[str] = (),
    source: str = "harness",
    created_at: datetime | None = None,
) -> MemoryRecord:
    record = _prepare_record(
        repo_id=repo_id,
        record_type=MemoryType.TASK_SUMMARY,
        content=content,
        rationale=None,
        paths=paths,
        tags=tags,
        source=source,
        trust_label=TrustLabel.HARNESS_GENERATED,
        created_at=created_at,
    )
    with write_txn(conn):
        _insert_record(conn, record)
    return record


def reject_secret_text(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("value must be str")
    if _contains_suspected_secret(value):
        raise MemoryValidationError("memory field rejected: suspected secret")


def _record_from_row(row: tuple[object, ...]) -> MemoryRecord:
    return MemoryRecord(
        record_id=str(row[0]),
        repo_id=str(row[1]),
        record_type=MemoryType(str(row[2])),
        content=str(row[3]),
        rationale=None if row[4] is None else str(row[4]),
        paths=tuple(json.loads(str(row[5]))),
        tags=tuple(json.loads(str(row[6]))),
        source=str(row[7]),
        status=MemoryStatus(str(row[8])),
        trust_label=TrustLabel(str(row[9])),
        created_at=_time_from_text(str(row[10])),
        supersedes_id=None if row[11] is None else str(row[11]),
    )


def list_records(
    conn: sqlite3.Connection,
    repo_id: str,
    *,
    record_types: Iterable[MemoryType | str] | None = None,
    status: MemoryStatus | str | None = MemoryStatus.ACTIVE,
) -> tuple[MemoryRecord, ...]:
    normalized_repo = _validated_repo_id(repo_id)
    clauses = ["repo_id = ?"]
    parameters: list[object] = [normalized_repo]
    if status is not None:
        normalized_status = MemoryStatus(status)
        clauses.append("status = ?")
        parameters.append(normalized_status)
    if record_types is not None:
        normalized_types = tuple(MemoryType(item) for item in record_types)
        if not normalized_types:
            return ()
        clauses.append(
            "record_type IN (" + ", ".join("?" for _ in normalized_types) + ")"
        )
        parameters.extend(normalized_types)
    rows = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM memory_records "
        f"WHERE {' AND '.join(clauses)} ORDER BY created_at, record_id",
        parameters,
    ).fetchall()
    return tuple(_record_from_row(row) for row in rows)


def export_records(conn: sqlite3.Connection, repo_id: str) -> str:
    normalized_repo = _validated_repo_id(repo_id)
    records = list_records(conn, normalized_repo, status=None)
    payload = {
        "repo_id": normalized_repo,
        "records": [
            {
                **asdict(record),
                "record_type": record.record_type.value,
                "status": record.status.value,
                "trust_label": record.trust_label.value,
                "created_at": _time_to_text(record.created_at),
            }
            for record in records
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def clear_repo(conn: sqlite3.Connection, repo_id: str) -> int:
    normalized_repo = _validated_repo_id(repo_id)
    with write_txn(conn):
        cursor = conn.execute(
            "DELETE FROM memory_records WHERE repo_id = ?",
            (normalized_repo,),
        )
    return cursor.rowcount
