from __future__ import annotations

from pathlib import Path

from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.envelope import Envelope
from guardedcoder.models.permit import Classification, RiskDecision
from guardedcoder.tools.paths import is_inside_worktree, resolve_under_worktree


def _under_write_paths(worktree: Path, envelope: Envelope, user_path: str) -> bool:
    resolved = resolve_under_worktree(worktree, user_path)
    for write_path in envelope.write_paths:
        allowed = resolve_under_worktree(worktree, write_path)
        if not is_inside_worktree(worktree, allowed):
            continue
        if resolved == allowed or resolved.is_relative_to(allowed):
            return True
    return False


def classify_write(worktree: Path, envelope: Envelope, user_path: str) -> Classification:
    fence = check_path(worktree, user_path)
    if fence == FenceCode.WORKSPACE_ESCAPE:
        return Classification(decision=RiskDecision.Deny, code=FenceCode.WORKSPACE_ESCAPE)
    if fence == FenceCode.SENSITIVE_PATH:
        return Classification(decision=RiskDecision.Deny, code=FenceCode.SENSITIVE_PATH)
    if _under_write_paths(worktree, envelope, user_path):
        return Classification(decision=RiskDecision.Allow, code=None)
    return Classification(decision=RiskDecision.NeedApproval, code=None)
