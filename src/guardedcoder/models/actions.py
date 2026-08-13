from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from guardedcoder.errors import ActionParseError

_MAX_RAW_LEN = 1_000_000


class _StrictAction(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListDirAction(_StrictAction):
    action: Literal["list_dir"]
    path: str


class ReadFileAction(_StrictAction):
    action: Literal["read_file"]
    path: str


class SearchTextAction(_StrictAction):
    action: Literal["search_text"]
    query: str


class ApplyPatchAction(_StrictAction):
    action: Literal["apply_patch"]
    diff: str


class RunCommandAction(_StrictAction):
    action: Literal["run_command"]
    profile_id: str


class FinishAction(_StrictAction):
    action: Literal["finish"]
    outcome: str


Action = (
    ListDirAction
    | ReadFileAction
    | SearchTextAction
    | ApplyPatchAction
    | RunCommandAction
    | FinishAction
)

_ACTION_ADAPTER = TypeAdapter(Annotated[Action, Field(discriminator="action")])


def parse_llm_response(raw: str) -> Action:
    if len(raw) > _MAX_RAW_LEN:
        raise ActionParseError("oversized payload")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ActionParseError("invalid JSON") from exc
    try:
        return _ACTION_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise ActionParseError("invalid action") from exc
