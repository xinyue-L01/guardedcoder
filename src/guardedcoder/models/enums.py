from enum import StrEnum


class RunState(StrEnum):
    awaiting_envelope = "awaiting_envelope"
    running = "running"
    awaiting_approval = "awaiting_approval"
    awaiting_envelope_revision = "awaiting_envelope_revision"
    executing_action = "executing_action"
    verifying = "verifying"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"
    unverified = "unverified"
    exhausted = "exhausted"
    error = "error"


class ArtifactState(StrEnum):
    worktree_present = "worktree_present"
    patch_ready = "patch_ready"
    applying = "applying"
    applied = "applied"
    discarded = "discarded"
    cleanup_error = "cleanup_error"
