import json
import re

from guardedcoder.errors import SecretLeakError
from guardedcoder.llm.port import LLMPort

_FAKE_KEY = "sk" + "-test"
_BLOCKED = '{"action":"finish","outcome":"blocked"}'
_FAIL_STATUS_JSON = re.compile(r'"status"\s*:\s*"FAIL"')
_SENSOR_JSON = re.compile(r'"sensor"\s*:')
_PROFILE_JSON = re.compile(r'"profile_id"\s*:')
_FAIL_STATUS_KV = re.compile(r"\bstatus\s*[:=]\s*FAIL\b")
_SENSOR_FIELD = re.compile(r"\bsensor\b")
_PROFILE_FIELD = re.compile(r"\bprofile_id\b")


class MockLLMExhaustedError(Exception):
    """Raised when MockLLM has no remaining preset responses."""


def _has_fail_verdict(messages: list[dict[str, str]]) -> bool:
    text = "\n".join(message.get("content", "") for message in messages)
    json_fail = _FAIL_STATUS_JSON.search(text) is not None
    json_struct = (
        _SENSOR_JSON.search(text) is not None
        and _PROFILE_JSON.search(text) is not None
    )
    if json_fail and json_struct:
        return True
    kv_fail = _FAIL_STATUS_KV.search(text) is not None
    kv_struct = (
        _SENSOR_FIELD.search(text) is not None
        and _PROFILE_FIELD.search(text) is not None
    )
    return kv_fail and kv_struct


def _is_apply_patch(response: str) -> bool:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("action") == "apply_patch"


class MockLLM(LLMPort):
    def __init__(self, responses: list[str], *, gate_on_fail: bool = False) -> None:
        self._remaining = list(responses)
        self._gate_on_fail = gate_on_fail
        self._emitted = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        for message in messages:
            if _FAKE_KEY in message.get("content", ""):
                raise SecretLeakError
        if not self._remaining:
            raise MockLLMExhaustedError
        if self._gate_on_fail and self._emitted > 0:
            candidate = self._remaining[0]
            if _is_apply_patch(candidate) and not _has_fail_verdict(messages):
                return _BLOCKED
        response = self._remaining.pop(0)
        self._emitted += 1
        return response
