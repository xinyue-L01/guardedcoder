from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RiskDecision(StrEnum):
    Allow = "Allow"
    NeedApproval = "NeedApproval"
    Deny = "Deny"


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    decision: RiskDecision
    code: str | None
