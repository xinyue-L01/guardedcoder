from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from guardedcoder.models.envelope import Envelope


class VerifyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    verify_profile_ids: tuple[str, ...]


def build_verify_plan(envelope: Envelope) -> VerifyPlan:
    profile_ids = envelope.verify_profiles
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("verify profile ids must be unique")
    known = {profile.profile_id for profile in envelope.profiles}
    if set(profile_ids) - known:
        raise ValueError("verify profile is not present in the envelope")
    return VerifyPlan(verify_profile_ids=profile_ids)

