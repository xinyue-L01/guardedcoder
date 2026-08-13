from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from guardedcoder.errors import RemoteKeyHttpError
from guardedcoder.llm.port import LLMPort

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OpenAICompatibleLLM(LLMPort):
    def __init__(
        self,
        base_url: str,
        model: str,
        key_provider: Callable[[], str | None],
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._key_provider = key_provider
        self._http = http_client or httpx.Client(follow_redirects=False)

    def complete(self, messages: list[dict[str, str]]) -> str:
        key = self._key_provider()
        if key and self._is_remote_http():
            raise RemoteKeyHttpError
        headers: dict[str, str] = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        response = self._http.post(
            f"{self._base_url.rstrip('/')}/chat/completions",
            json={"model": self._model, "messages": messages},
            headers=headers,
            follow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise httpx.HTTPStatusError(
                f"redirect {response.status_code} not followed",
                request=response.request,
                response=response,
            )
        payload = response.json()
        return payload["choices"][0]["message"]["content"]

    def _is_remote_http(self) -> bool:
        parsed = urlparse(self._base_url)
        return parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS
