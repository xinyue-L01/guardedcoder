from guardedcoder.errors import SecretLeakError
from guardedcoder.llm.port import LLMPort

_FAKE_KEY = "sk" + "-test"


class MockLLMExhaustedError(Exception):
    """Raised when MockLLM has no remaining preset responses."""


class MockLLM(LLMPort):
    def __init__(self, responses: list[str]) -> None:
        self._remaining = list(responses)

    def complete(self, messages: list[dict[str, str]]) -> str:
        for message in messages:
            if _FAKE_KEY in message.get("content", ""):
                raise SecretLeakError
        if not self._remaining:
            raise MockLLMExhaustedError
        return self._remaining.pop(0)
