from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from guardedcoder.memory.store import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    TrustLabel,
    list_records,
    normalize_paths,
    normalize_tags,
)

_TERMS = re.compile(r"\w+", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    record: MemoryRecord
    score: int
    content: str
    trust_label: TrustLabel


def _terms(value: str) -> frozenset[str]:
    return frozenset(_TERMS.findall(value.casefold()))


def _paths_related(left: str, right: str) -> bool:
    if left == "." or right == ".":
        return True
    return (
        left == right
        or left.startswith(right + "/")
        or right.startswith(left + "/")
    )


def _applies_to_paths(record: MemoryRecord, paths: tuple[str, ...]) -> bool:
    if not paths or not record.paths:
        return True
    return any(
        _paths_related(record_path, query_path)
        for record_path in record.paths
        for query_path in paths
    )


def _score(
    record: MemoryRecord,
    *,
    query_terms: frozenset[str],
    paths: tuple[str, ...],
    tags: tuple[str, ...],
) -> int:
    exact_paths = len(set(record.paths).intersection(paths))
    related_paths = sum(
        1
        for record_path in record.paths
        for query_path in paths
        if record_path != query_path and _paths_related(record_path, query_path)
    )
    tag_overlap = len(set(record.tags).intersection(tags))
    record_terms = _terms(
        " ".join(
            part
            for part in (record.content, record.rationale or "")
            if part
        )
    )
    keyword_overlap = len(record_terms.intersection(query_terms))
    return (
        (exact_paths * 100)
        + (related_paths * 20)
        + (tag_overlap * 10)
        + keyword_overlap
    )


def retrieve_records(
    conn: sqlite3.Connection,
    *,
    repo_id: str,
    query: str,
    record_types: Iterable[MemoryType | str] | None = None,
    paths: Iterable[str] = (),
    tags: Iterable[str] = (),
    top_n: int = 5,
    per_record_char_budget: int = 2_000,
    total_char_budget: int = 6_000,
) -> tuple[RetrievedMemory, ...]:
    if not isinstance(query, str):
        raise TypeError("query must be str")
    if not isinstance(top_n, int) or top_n < 0:
        raise ValueError("top_n must be a non-negative integer")
    if not isinstance(per_record_char_budget, int) or per_record_char_budget < 0:
        raise ValueError("per_record_char_budget must be a non-negative integer")
    if not isinstance(total_char_budget, int) or total_char_budget < 0:
        raise ValueError("total_char_budget must be a non-negative integer")
    if top_n == 0 or per_record_char_budget == 0 or total_char_budget == 0:
        return ()

    normalized_paths = normalize_paths(paths)
    normalized_tags = normalize_tags(tags)
    query_terms = _terms(query)
    candidates = [
        record
        for record in list_records(
            conn,
            repo_id,
            record_types=record_types,
            status=MemoryStatus.ACTIVE,
        )
        if _applies_to_paths(record, normalized_paths)
    ]
    ranked = sorted(
        (
            (
                _score(
                    record,
                    query_terms=query_terms,
                    paths=normalized_paths,
                    tags=normalized_tags,
                ),
                record,
            )
            for record in candidates
        ),
        key=lambda item: (
            -item[0],
            -item[1].created_at.timestamp(),
            item[1].record_id,
        ),
    )

    remaining = total_char_budget
    results: list[RetrievedMemory] = []
    for score, record in ranked[:top_n]:
        content = record.content[: min(per_record_char_budget, remaining)]
        if not content:
            break
        results.append(
            RetrievedMemory(
                record=record,
                score=score,
                content=content,
                trust_label=record.trust_label,
            )
        )
        remaining -= len(content)
        if remaining == 0:
            break
    return tuple(results)


retrieve = retrieve_records
