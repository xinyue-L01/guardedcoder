from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from guardedcoder.governance.classify import classify_read, classify_write
from guardedcoder.governance.hard_rules import ProfileKind, classify_profile
from guardedcoder.models.actions import (
    Action,
    ApplyPatchAction,
    ListDirAction,
    ReadFileAction,
    RunCommandAction,
)
from guardedcoder.models.envelope import Envelope
from guardedcoder.models.permit import RiskDecision
from guardedcoder.models.task import TaskBudget
from guardedcoder.tools.apply_patch import patch_paths


class VerdictKind(StrEnum):
    Allow = "Allow"
    NeedApproval = "NeedApproval"
    NeedEnvelopeRevision = "NeedEnvelopeRevision"
    Deny = "Deny"


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: VerdictKind
    code: str | None


def evaluate(
    *,
    worktree: Path,
    envelope: Envelope,
    action: Action,
    budget: TaskBudget,
) -> Verdict:
    classification = None
    if isinstance(action, (ReadFileAction, ListDirAction)):
        classification = classify_read(worktree, envelope, action.path)
        if classification.decision == RiskDecision.Deny:
            return Verdict(kind=VerdictKind.Deny, code=classification.code)

    if isinstance(action, ApplyPatchAction):
        for rel in patch_paths(action.diff):
            item = classify_write(worktree, envelope, rel)
            if item.decision == RiskDecision.Deny:
                return Verdict(kind=VerdictKind.Deny, code=item.code)
            if item.decision == RiskDecision.NeedApproval:
                classification = item

    if isinstance(action, RunCommandAction):
        kind = classify_profile(envelope, action.profile_id)
        if kind is ProfileKind.unknown:
            return Verdict(
                kind=VerdictKind.NeedEnvelopeRevision,
                code="COMMAND_NOT_ALLOWED",
            )
        if kind is ProfileKind.hard_forbidden:
            return Verdict(
                kind=VerdictKind.Deny,
                code="HARD_FORBIDDEN_COMMAND",
            )

    if budget.remaining_steps <= 0:
        return Verdict(kind=VerdictKind.Deny, code="BUDGET_EXHAUSTED")

    if (
        classification is not None
        and classification.decision == RiskDecision.NeedApproval
    ):
        return Verdict(kind=VerdictKind.NeedApproval, code=None)

    return Verdict(kind=VerdictKind.Allow, code=None)
