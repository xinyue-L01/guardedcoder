import pytest

from guardedcoder.errors import SecretLeakError
from guardedcoder.llm.mock import MockLLM, MockLLMExhaustedError
from guardedcoder.llm.port import LLMPort


def test_mock_llm_is_llm_port() -> None:
    assert issubclass(MockLLM, LLMPort)


def test_complete_returns_responses_in_sequence() -> None:
    llm = MockLLM(responses=["first", "second"])
    assert llm.complete([{"role": "user", "content": "a"}]) == "first"
    assert llm.complete([{"role": "user", "content": "b"}]) == "second"


def test_complete_raises_when_responses_exhausted() -> None:
    llm = MockLLM(responses=["only"])
    llm.complete([{"role": "user", "content": "a"}])
    with pytest.raises(MockLLMExhaustedError):
        llm.complete([{"role": "user", "content": "b"}])


def test_complete_raises_secret_leak_and_does_not_consume() -> None:
    fake_key = "sk" + "-test"
    llm = MockLLM(responses=["should-not-return"])
    with pytest.raises(SecretLeakError):
        llm.complete([{"role": "user", "content": f"token {fake_key}"}])
    assert llm.complete([{"role": "user", "content": "ok"}]) == "should-not-return"
