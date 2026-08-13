import httpx
import pytest

from guardedcoder.errors import RemoteKeyHttpError
from guardedcoder.llm.openai_compat import OpenAICompatibleLLM
from guardedcoder.llm.port import LLMPort

_FAKE_KEY = "sk" + "-test"
_COMPLETION = "ok-from-mock"


def _completion_body(text: str = _COMPLETION) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _recording_client(
    seen: list[httpx.Request],
    *,
    follow_redirects: bool = False,
    redirect: bool = False,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "evil" in str(request.url):
            return httpx.Response(200, json=_completion_body("stolen"))
        if redirect:
            return httpx.Response(
                302,
                headers={"Location": "http://evil.test/v1/chat/completions"},
            )
        return httpx.Response(200, json=_completion_body())

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=follow_redirects,
    )


def _llm(base_url: str, client: httpx.Client) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        base_url=base_url,
        model="test-model",
        key_provider=lambda: _FAKE_KEY,
        http_client=client,
    )


def test_openai_compat_llm_is_llm_port() -> None:
    assert issubclass(OpenAICompatibleLLM, LLMPort)


def test_remote_http_with_key_refuses_without_sending_request() -> None:
    seen: list[httpx.Request] = []
    client = _recording_client(seen)
    llm = _llm("http://remote.example/v1", client)
    with pytest.raises(RemoteKeyHttpError):
        llm.complete([{"role": "user", "content": "hi"}])
    assert seen == []


def test_remote_http_uppercase_scheme_with_key_refuses_without_sending_request() -> None:
    seen: list[httpx.Request] = []
    client = _recording_client(seen)
    llm = _llm("HTTP://remote.example/v1", client)
    with pytest.raises(RemoteKeyHttpError):
        llm.complete([{"role": "user", "content": "hi"}])
    assert seen == []


def test_loopback_ipv4_http_with_key_completes() -> None:
    seen: list[httpx.Request] = []
    client = _recording_client(seen)
    llm = _llm("http://127.0.0.1:8000/v1", client)
    assert llm.complete([{"role": "user", "content": "hi"}]) == _COMPLETION
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://127.0.0.1:8000/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {_FAKE_KEY}"


def test_loopback_localhost_http_with_key_completes() -> None:
    seen: list[httpx.Request] = []
    client = _recording_client(seen)
    llm = _llm("http://localhost:8000/v1", client)
    assert llm.complete([{"role": "user", "content": "hi"}]) == _COMPLETION
    assert len(seen) == 1


def test_loopback_ipv6_http_with_key_completes() -> None:
    seen: list[httpx.Request] = []
    client = _recording_client(seen)
    llm = _llm("http://[::1]:8000/v1", client)
    assert llm.complete([{"role": "user", "content": "hi"}]) == _COMPLETION
    assert len(seen) == 1


def test_https_remote_with_key_sends_request() -> None:
    seen: list[httpx.Request] = []
    client = _recording_client(seen)
    llm = _llm("https://api.example/v1", client)
    assert llm.complete([{"role": "user", "content": "hi"}]) == _COMPLETION
    assert len(seen) == 1
    assert seen[0].headers["Authorization"] == f"Bearer {_FAKE_KEY}"


def test_does_not_follow_3xx_even_if_client_would() -> None:
    seen: list[httpx.Request] = []
    client = _recording_client(seen, follow_redirects=True, redirect=True)
    llm = _llm("http://127.0.0.1:8000/v1", client)
    with pytest.raises(httpx.HTTPStatusError):
        llm.complete([{"role": "user", "content": "hi"}])
    assert len(seen) == 1
    assert "evil" not in str(seen[0].url)
