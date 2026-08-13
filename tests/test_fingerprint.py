from guardedcoder.fingerprint import SCHEMA_VERSION, compute_fingerprint


def _kwargs(**overrides: object) -> dict:
    base = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-a",
        "envelope_hash": "abc",
        "base_commit": "def",
        "worktree_identity": "wt-1",
        "normalized_action": {"action": "list_dir", "path": "."},
    }
    base.update(overrides)
    return base


def test_same_inputs_yield_same_fingerprint() -> None:
    assert SCHEMA_VERSION == "1"
    a = compute_fingerprint(**_kwargs())
    b = compute_fingerprint(**_kwargs())
    assert a == b
    assert a == a.lower()


def test_different_task_id_yields_different_fingerprint() -> None:
    a = compute_fingerprint(**_kwargs())
    b = compute_fingerprint(**_kwargs(task_id="task-b"))
    assert a != b
