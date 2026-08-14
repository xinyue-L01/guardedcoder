from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from guardedcoder.memory.retrieve import retrieve_records
from guardedcoder.memory.store import (
    MemoryStatus,
    MemoryType,
    TrustLabel,
    add_constraint,
    add_decision,
    clear_repo,
    export_records,
    list_records,
)
from guardedcoder.persist.db import connect


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=timezone.utc)


def test_constraints_are_structured_and_repo_scoped(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    first = add_constraint(
        conn,
        repo_id="repo-a",
        content="Run pytest before committing.",
        paths=("tests",),
        tags=("python", "tests"),
        source="user-cli",
        created_at=_at(1),
    )
    add_constraint(
        conn,
        repo_id="repo-b",
        content="Use another repository convention.",
        created_at=_at(2),
    )

    assert first.record_type is MemoryType.PROJECT_CONSTRAINT
    assert first.status is MemoryStatus.ACTIVE
    assert first.trust_label is TrustLabel.USER_PROVIDED
    assert first.paths == ("tests",)
    assert first.tags == ("python", "tests")
    assert list_records(conn, "repo-a") == (first,)

    exported = json.loads(export_records(conn, "repo-a"))
    assert [item["record_id"] for item in exported["records"]] == [first.record_id]
    assert exported["repo_id"] == "repo-a"
    assert "repo-b" not in export_records(conn, "repo-a")


def test_add_decision_supersedes_only_an_active_decision(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    old = add_decision(
        conn,
        repo_id="repo-a",
        content="Use unittest.",
        rationale="Legacy convention.",
        created_at=_at(1),
    )
    new = add_decision(
        conn,
        repo_id="repo-a",
        content="Use pytest.",
        rationale="The project standard changed.",
        supersedes=old.record_id,
        created_at=_at(2),
    )

    assert list_records(conn, "repo-a") == (new,)
    all_records = list_records(conn, "repo-a", status=None)
    assert [record.status for record in all_records] == [
        MemoryStatus.SUPERSEDED,
        MemoryStatus.ACTIVE,
    ]
    assert new.supersedes_id == old.record_id

    with pytest.raises(ValueError, match="active decision"):
        add_decision(
            conn,
            repo_id="repo-a",
            content="Try to supersede it twice.",
            supersedes=old.record_id,
        )


def test_secret_like_memory_is_rejected_without_leaking_value(
    tmp_path, caplog
) -> None:
    conn = connect(tmp_path / "memory.db")
    fake_secret = "sk" + "-test_AbCdEf0123456789"

    with pytest.raises(ValueError) as caught:
        add_constraint(
            conn,
            repo_id="repo-a",
            content="Never store " + fake_secret,
        )

    assert fake_secret not in str(caught.value)
    assert fake_secret not in caplog.text
    assert list_records(conn, "repo-a") == ()


def test_clear_requires_repo_identity_and_cannot_clear_other_repo(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    add_constraint(conn, repo_id="repo-a", content="A")
    other = add_constraint(conn, repo_id="repo-b", content="B")

    with pytest.raises(ValueError, match="repo_id"):
        clear_repo(conn, "")

    assert clear_repo(conn, "repo-a") == 1
    assert list_records(conn, "repo-a", status=None) == ()
    assert list_records(conn, "repo-b", status=None) == (other,)


def test_retrieval_filters_scores_and_ranks_deterministically(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    exact = add_constraint(
        conn,
        repo_id="repo-a",
        content="Pytest tests must be deterministic.",
        paths=("tests/unit",),
        tags=("python", "pytest"),
        created_at=_at(1),
    )
    newer = add_constraint(
        conn,
        repo_id="repo-a",
        content="Pytest is the test runner.",
        paths=("tests",),
        tags=("python",),
        created_at=_at(3),
    )
    older = add_constraint(
        conn,
        repo_id="repo-a",
        content="Pytest is required for checks.",
        paths=("tests",),
        tags=("python",),
        created_at=_at(2),
    )
    add_decision(
        conn,
        repo_id="repo-a",
        content="Use pytest plugins.",
        paths=("tests/unit",),
        tags=("python", "pytest"),
        created_at=_at(4),
    )
    add_constraint(
        conn,
        repo_id="repo-b",
        content="Pytest from another repository.",
        paths=("tests/unit",),
        tags=("python", "pytest"),
        created_at=_at(5),
    )

    kwargs = {
        "repo_id": "repo-a",
        "query": "pytest deterministic",
        "record_types": (MemoryType.PROJECT_CONSTRAINT,),
        "paths": ("tests/unit",),
        "tags": ("python", "pytest"),
        "top_n": 3,
    }
    first = retrieve_records(conn, **kwargs)
    second = retrieve_records(conn, **kwargs)

    assert [hit.record.record_id for hit in first] == [
        exact.record_id,
        newer.record_id,
        older.record_id,
    ]
    assert first == second
    assert all(hit.trust_label is TrustLabel.USER_PROVIDED for hit in first)
    assert all(hit.record.repo_id == "repo-a" for hit in first)
    assert all(hit.record.record_type is MemoryType.PROJECT_CONSTRAINT for hit in first)


def test_retrieval_honors_top_n_and_character_budgets(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    for day in range(1, 4):
        add_constraint(
            conn,
            repo_id="repo-a",
            content="pytest-" + str(day) + "-" + ("x" * 30),
            created_at=_at(day),
        )

    hits = retrieve_records(
        conn,
        repo_id="repo-a",
        query="pytest",
        top_n=2,
        per_record_char_budget=12,
        total_char_budget=20,
    )

    assert len(hits) == 2
    assert len(hits[0].content) == 12
    assert len(hits[1].content) == 8
    assert sum(len(hit.content) for hit in hits) == 20


def test_connect_installs_memory_schema(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "memory_records" in names
    assert list_records(conn, "repo-a") == ()


def test_paths_and_tags_reject_bare_strings(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    with pytest.raises(TypeError, match="paths"):
        add_constraint(conn, repo_id="repo-a", content="A", paths="tests")
    with pytest.raises(TypeError, match="tags"):
        add_constraint(conn, repo_id="repo-a", content="A", tags="python")
    assert list_records(conn, "repo-a") == ()


def test_absolute_and_drive_paths_are_rejected(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    for path in ("C:/secrets", "/etc/passwd", "//server/share"):
        with pytest.raises(ValueError, match="repository-relative"):
            add_constraint(conn, repo_id="repo-a", content="A", paths=(path,))
    assert list_records(conn, "repo-a") == ()


def test_retrieve_excludes_superseded_and_unrelated_paths(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    old = add_decision(
        conn,
        repo_id="repo-a",
        content="Use unittest for pytest checks.",
        paths=("tests/unit",),
        tags=("python", "pytest"),
        created_at=_at(1),
    )
    add_decision(
        conn,
        repo_id="repo-a",
        content="Use pytest for checks.",
        paths=("tests/unit",),
        tags=("python", "pytest"),
        supersedes=old.record_id,
        created_at=_at(2),
    )
    add_constraint(
        conn,
        repo_id="repo-a",
        content="Pytest docs live elsewhere.",
        paths=("docs",),
        tags=("python", "pytest"),
        created_at=_at(3),
    )
    exact = add_constraint(
        conn,
        repo_id="repo-a",
        content="Keep fixtures local.",
        paths=("tests/unit",),
        tags=("python",),
        created_at=_at(4),
    )

    hits = retrieve_records(
        conn,
        repo_id="repo-a",
        query="pytest",
        paths=("tests/unit",),
        tags=("python", "pytest"),
        top_n=10,
    )
    ids = [hit.record.record_id for hit in hits]
    assert old.record_id not in ids
    assert exact.record_id in ids
    assert all(hit.record.status is MemoryStatus.ACTIVE for hit in hits)
    assert all(
        hit.record.paths == ("tests/unit",) or hit.record.record_type is MemoryType.DECISION
        for hit in hits
    )
    assert all("docs" not in hit.record.paths for hit in hits)


def test_path_backslash_and_tag_casefold(tmp_path) -> None:
    conn = connect(tmp_path / "memory.db")
    record = add_constraint(
        conn,
        repo_id="repo-a",
        content="Pytest layout.",
        paths=("tests\\unit",),
        tags=("Python", "Pytest"),
    )
    assert record.paths == ("tests/unit",)
    assert record.tags == ("pytest", "python")
