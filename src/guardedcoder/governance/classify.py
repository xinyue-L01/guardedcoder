from __future__ import annotations

from pathlib import Path

from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.envelope import Envelope
from guardedcoder.models.permit import Classification, RiskDecision
from guardedcoder.tools.paths import is_inside_worktree, resolve_under_worktree


def _under_allowed_paths(
    worktree: Path, allowed_paths: tuple[str, ...], user_path: str
) -> bool:
    resolved = resolve_under_worktree(worktree, user_path)
    for allowed_path in allowed_paths:
        allowed = resolve_under_worktree(worktree, allowed_path)
        if not is_inside_worktree(worktree, allowed):
            continue
        if resolved == allowed or resolved.is_relative_to(allowed):
            return True
    return False


def _fence_deny(worktree: Path, user_path: str) -> Classification | None:
    fence = check_path(worktree, user_path)
    if fence == FenceCode.WORKSPACE_ESCAPE:
        return Classification(decision=RiskDecision.Deny, code=FenceCode.WORKSPACE_ESCAPE)
    if fence == FenceCode.SENSITIVE_PATH:
        return Classification(decision=RiskDecision.Deny, code=FenceCode.SENSITIVE_PATH)
    return None


def classify_write(worktree: Path, envelope: Envelope, user_path: str) -> Classification:
    denied = _fence_deny(worktree, user_path)
    if denied is not None:
        return denied
    if _under_allowed_paths(worktree, envelope.write_paths, user_path):
        return Classification(decision=RiskDecision.Allow, code=None)
    return Classification(decision=RiskDecision.NeedApproval, code=None)


def classify_read(worktree: Path, envelope: Envelope, user_path: str) -> Classification:
    denied = _fence_deny(worktree, user_path)
    if denied is not None:
        return denied
    if _under_allowed_paths(worktree, envelope.read_paths, user_path):
        return Classification(decision=RiskDecision.Allow, code=None)
    return Classification(decision=RiskDecision.Deny, code=None)
