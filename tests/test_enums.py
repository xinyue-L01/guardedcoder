from guardedcoder.models.enums import ArtifactState, RunState


def test_run_state_members() -> None:
    assert set(RunState) == {
        "awaiting_envelope",
        "running",
        "awaiting_approval",
        "awaiting_envelope_revision",
        "executing_action",
        "verifying",
        "succeeded",
        "failed",
        "blocked",
        "unverified",
        "exhausted",
        "error",
    }
    assert "applied" not in RunState


def test_artifact_state_members() -> None:
    assert set(ArtifactState) == {
        "worktree_present",
        "patch_ready",
        "applying",
        "applied",
        "discarded",
        "cleanup_error",
    }
