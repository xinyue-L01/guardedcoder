from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from guardedcoder.auth.keyring_store import KeyringStore
from guardedcoder.cli import main, parse_args
from guardedcoder.config.load import load_app_config
from guardedcoder.errors import KeyringError, RemoteKeyHttpError
from guardedcoder.llm.openai_compat import OpenAICompatibleLLM


def _fake_key() -> str:
    return "sk" + "-test"


def _other_key() -> str:
    return "sk" + "-other"


_LEGAL_TOML = """\
config_schema_version = "1"
read_paths = ["src"]
write_paths = ["src"]
verify_profiles = ["pytest"]
max_steps = 10
max_total_seconds = 300
command_timeout_seconds = 60
max_output_bytes = 65536
max_patch_bytes = 1000000
allow_delete = false
allow_network = false

[provider]
provider_id = "openai-compat"
base_url = "http://127.0.0.1:8080/v1"
model = "local"
timeout_seconds = 30

[[profiles]]
profile_id = "pytest"
argv_template = ["pytest", "--junitxml", "{junit_out}"]
cwd = "."
timeout_seconds = 60
max_output_bytes = 65536
"""


class FakeKeyring:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._require()
        self.data[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        self._require()
        return self.data.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self._require()
        key = (service, username)
        if key not in self.data:
            raise KeyError("not found")
        del self.data[key]

    def _require(self) -> None:
        if not self.available:
            raise RuntimeError("keyring backend unavailable")


def _config_path(tmp_path: Path) -> Path:
    return tmp_path / "guardedcoder" / "config.toml"


def _run(
    argv: list[str],
    tmp_path: Path,
    *,
    backend: FakeKeyring | None = None,
    getpass_fn: object | None = None,
) -> tuple[int, KeyringStore, FakeKeyring]:
    fake = backend if backend is not None else FakeKeyring()
    store = KeyringStore(backend=fake)
    code = main(
        argv,
        getpass_fn=getpass_fn,
        key_store=store,
        config_path=_config_path(tmp_path),
    )
    return code, store, fake


def _init(tmp_path: Path, backend: FakeKeyring | None = None) -> KeyringStore:
    code, store, _fake = _run(["config", "init"], tmp_path, backend=backend)
    assert code == 0
    return store


def test_parse_nested_config_and_auth_commands() -> None:
    cfg = parse_args(["config", "init"])
    assert cfg.command == "config"
    assert cfg.config_command == "init"
    auth = parse_args(["auth", "status"])
    assert auth.command == "auth"
    assert auth.auth_command == "status"


def test_config_and_auth_without_subcommand_are_nonzero() -> None:
    assert main(["config"]) != 0
    assert main(["auth"]) != 0


def test_unknown_nested_subcommand_is_nonzero() -> None:
    assert main(["config", "explode"]) != 0
    assert main(["auth", "explode"]) != 0


def test_config_init_writes_versioned_toml_without_api_key(tmp_path: Path) -> None:
    code, _store, _fake = _run(["config", "init"], tmp_path)
    assert code == 0
    path = _config_path(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "config_schema_version" in text
    assert "api_key" not in text.lower()
    assert "token" not in text.lower()
    assert "password" not in text.lower()
    assert _fake_key() not in text
    cfg = load_app_config(path)
    assert cfg.config_schema_version == "1"
    assert cfg.provider.provider_id == "openai-compat"


def test_config_validate_and_show_reuse_load_app_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init(tmp_path)
    code, _store, _fake = _run(["config", "validate"], tmp_path)
    assert code == 0
    code, _store, _fake = _run(["config", "show"], tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "openai-compat" in out
    assert "http://127.0.0.1:8080/v1" in out
    assert _fake_key() not in out


@pytest.mark.parametrize(
    "mutator",
    [
        lambda body: body + "\nunknown = true\n",
        lambda body: body.replace("max_output_bytes = 65536\n", "max_output_bytes = 65536\nshell = true\n", 1),
        lambda body: body + "\napi_key = \"" + "sk" + "-test\"\n",
        lambda body: body.replace(
            'argv_template = ["pytest", "--junitxml", "{junit_out}"]',
            'argv_template = ["pip", "install", "pkg"]',
        ),
    ],
)
def test_validate_and_show_fail_closed(
    tmp_path: Path, mutator: object, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(mutator(_LEGAL_TOML), encoding="utf-8")
    for command in ("validate", "show"):
        code, _store, _fake = _run(["config", command], tmp_path)
        err = capsys.readouterr().err
        assert code != 0
        assert _fake_key() not in err


def test_show_never_prints_keyring_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _init(tmp_path)
    store.set("openai-compat", _fake_key())
    code, _store, _fake = _run(["config", "show"], tmp_path)
    captured = capsys.readouterr()
    assert code == 0
    assert _fake_key() not in captured.out
    assert _fake_key() not in captured.err


def test_config_does_not_read_dotenv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init(tmp_path)
    env_body = "api_key=" + _fake_key() + "\nmax_steps=999\n"
    (tmp_path / ".env").write_text(env_body, encoding="utf-8")
    (_config_path(tmp_path).parent / ".env").write_text(env_body, encoding="utf-8")
    code, _store, _fake = _run(["config", "show"], tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert _fake_key() not in out
    assert "999" not in out


def test_auth_set_uses_injectable_getpass_and_isolates_providers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = FakeKeyring()
    _init(tmp_path, backend=backend)
    backend.set_password("guardedcoder", "other-provider", _other_key())
    prompts: list[str] = []

    def hidden(prompt: str = "") -> str:
        prompts.append(prompt)
        return _fake_key()

    code, store, _fake = _run(
        ["auth", "set"], tmp_path, backend=backend, getpass_fn=hidden
    )
    captured = capsys.readouterr()
    assert code == 0
    assert prompts
    assert _fake_key() not in "".join(prompts)
    assert store.get("openai-compat") == _fake_key()
    assert store.get("other-provider") == _other_key()
    assert store.get("openai-compat") != store.get("other-provider")
    assert _fake_key() not in captured.out
    assert _fake_key() not in captured.err


def test_auth_set_rejects_key_as_cli_argument(tmp_path: Path) -> None:
    backend = FakeKeyring()
    _init(tmp_path, backend=backend)
    code, store, _fake = _run(["auth", "set", _fake_key()], tmp_path, backend=backend)
    assert code != 0
    assert store.get("openai-compat") is None


def test_auth_status_omits_plaintext_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = FakeKeyring()
    _init(tmp_path, backend=backend)
    _run(
        ["auth", "set"],
        tmp_path,
        backend=backend,
        getpass_fn=lambda prompt="": _fake_key(),
    )
    capsys.readouterr()
    code, _store, _fake = _run(["auth", "status"], tmp_path, backend=backend)
    captured = capsys.readouterr()
    assert code == 0
    assert "openai-compat" in captured.out
    assert "configured" in captured.out.lower()
    assert _fake_key() not in captured.out
    assert _fake_key() not in captured.err
    assert _other_key() not in captured.out


def test_auth_update_overwrites_current_provider_only(tmp_path: Path) -> None:
    backend = FakeKeyring()
    _init(tmp_path, backend=backend)
    backend.set_password("guardedcoder", "other-provider", _other_key())
    _run(
        ["auth", "set"],
        tmp_path,
        backend=backend,
        getpass_fn=lambda prompt="": _fake_key(),
    )
    code, store, _fake = _run(
        ["auth", "update"],
        tmp_path,
        backend=backend,
        getpass_fn=lambda prompt="": "sk" + "-upd",
    )
    assert code == 0
    assert store.get("openai-compat") == "sk" + "-upd"
    assert store.get("other-provider") == _other_key()


def test_auth_clear_removes_current_provider_only(tmp_path: Path) -> None:
    backend = FakeKeyring()
    _init(tmp_path, backend=backend)
    backend.set_password("guardedcoder", "other-provider", _other_key())
    _run(
        ["auth", "set"],
        tmp_path,
        backend=backend,
        getpass_fn=lambda prompt="": _fake_key(),
    )
    code, store, _fake = _run(["auth", "clear"], tmp_path, backend=backend)
    assert code == 0
    assert store.get("openai-compat") is None
    assert store.get("other-provider") == _other_key()


def test_keyring_unavailable_fails_without_plaintext_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = FakeKeyring()
    _init(tmp_path, backend=good)
    dead = FakeKeyring(available=False)
    dead.data = dict(good.data)
    code, store, _fake = _run(
        ["auth", "set"],
        tmp_path,
        backend=dead,
        getpass_fn=lambda prompt="": _fake_key(),
    )
    err = capsys.readouterr().err
    assert code != 0
    assert _fake_key() not in err
    with pytest.raises(KeyringError):
        store.set("openai-compat", _fake_key())
    for path in tmp_path.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert _fake_key() not in text
            assert "OPENAI_API_KEY" not in text


def test_auth_does_not_fallback_to_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _fake_key())
    monkeypatch.setenv("API_KEY", _fake_key())
    _init(tmp_path)
    code, store, _fake = _run(["auth", "status"], tmp_path)
    captured = capsys.readouterr()
    assert code == 0
    assert store.get("openai-compat") is None
    assert _fake_key() not in captured.out
    assert "no" in captured.out.lower() or "false" in captured.out.lower() or "not" in captured.out.lower()


def test_keyring_store_does_not_read_another_provider() -> None:
    backend = FakeKeyring()
    store = KeyringStore(backend=backend)
    store.set("other-provider", _other_key())
    assert store.get("openai-compat") is None
    assert store.get("other-provider") == _other_key()


def _leaky_backend() -> object:
    class Leaky:
        def set_password(self, service: str, username: str, password: str) -> None:
            raise RuntimeError("store failed for " + password)

        def get_password(self, service: str, username: str) -> str | None:
            raise RuntimeError("read failed for stored secret")

        def delete_password(self, service: str, username: str) -> None:
            raise RuntimeError("delete failed for stored secret")

    return Leaky()


def test_keyring_error_does_not_chain_backend_exception() -> None:
    store = KeyringStore(backend=_leaky_backend())
    with pytest.raises(KeyringError) as caught:
        store.set("openai-compat", _fake_key())
    assert caught.value.__cause__ is None
    assert _fake_key() not in str(caught.value)
    assert _fake_key() not in repr(caught.value)


def test_keyring_error_redacts_secret_from_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init(tmp_path)
    store = KeyringStore(backend=_leaky_backend())
    code = main(
        ["auth", "set"],
        getpass_fn=lambda prompt="": _fake_key(),
        key_store=store,
        config_path=_config_path(tmp_path),
    )
    err = capsys.readouterr().err
    assert code != 0
    assert _fake_key() not in err
    with pytest.raises(KeyringError) as caught:
        store.set("openai-compat", _fake_key())
    assert caught.value.__cause__ is None


def test_auth_set_cli_argument_not_echoed_for_nonsk_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "plain" + "Secret99"
    _init(tmp_path)
    capsys.readouterr()
    code, store, _fake = _run(["auth", "set", secret], tmp_path)
    err = capsys.readouterr().err
    assert code != 0
    assert secret not in err
    assert store.get("openai-compat") is None


class PasswordDeleteError(Exception):
    """Stand-in for keyring.errors.PasswordDeleteError."""


def test_auth_clear_delete_failure_is_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailDelete:
        def set_password(self, service: str, username: str, password: str) -> None:
            return None

        def get_password(self, service: str, username: str) -> str | None:
            return None

        def delete_password(self, service: str, username: str) -> None:
            raise PasswordDeleteError("delete failed")

    _init(tmp_path)
    store = KeyringStore(backend=FailDelete())
    code = main(
        ["auth", "clear"],
        key_store=store,
        config_path=_config_path(tmp_path),
    )
    err = capsys.readouterr().err
    assert code != 0
    with pytest.raises(KeyringError) as caught:
        store.clear("openai-compat")
    assert caught.value.__cause__ is None
    assert "delete failed" not in err


def test_auth_clear_missing_entry_still_succeeds(tmp_path: Path) -> None:
    class Missing:
        def set_password(self, service: str, username: str, password: str) -> None:
            return None

        def get_password(self, service: str, username: str) -> str | None:
            return None

        def delete_password(self, service: str, username: str) -> None:
            raise PasswordDeleteError("Password not found")

    _init(tmp_path)
    code = main(
        ["auth", "clear"],
        key_store=KeyringStore(backend=Missing()),
        config_path=_config_path(tmp_path),
    )
    assert code == 0


def _recording_client(seen: list[httpx.Request], *, redirect: bool = False) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "evil" in str(request.url):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "stolen"}}]}
            )
        if redirect:
            return httpx.Response(
                302, headers={"Location": "http://evil.test/v1/chat/completions"}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )


def test_remote_http_with_keyring_key_reuses_t11_refusal() -> None:
    store = KeyringStore(backend=FakeKeyring())
    store.set("openai-compat", _fake_key())
    seen: list[httpx.Request] = []
    llm = OpenAICompatibleLLM(
        base_url="http://remote.example/v1",
        model="local",
        key_provider=lambda: store.get("openai-compat"),
        http_client=_recording_client(seen),
    )
    with pytest.raises(RemoteKeyHttpError):
        llm.complete([{"role": "user", "content": "hi"}])
    assert seen == []


def test_loopback_without_key_does_not_read_other_provider() -> None:
    store = KeyringStore(backend=FakeKeyring())
    store.set("other-provider", _other_key())
    seen: list[httpx.Request] = []
    llm = OpenAICompatibleLLM(
        base_url="http://127.0.0.1:8080/v1",
        model="local",
        key_provider=lambda: store.get("openai-compat"),
        http_client=_recording_client(seen),
    )
    assert llm.complete([{"role": "user", "content": "hi"}]) == "ok"
    assert len(seen) == 1
    assert "Authorization" not in seen[0].headers
    assert _other_key() not in str(seen[0].headers)


def test_https_uses_current_provider_key_only() -> None:
    store = KeyringStore(backend=FakeKeyring())
    store.set("openai-compat", _fake_key())
    store.set("other-provider", _other_key())
    seen: list[httpx.Request] = []
    llm = OpenAICompatibleLLM(
        base_url="https://api.example/v1",
        model="local",
        key_provider=lambda: store.get("openai-compat"),
        http_client=_recording_client(seen),
    )
    assert llm.complete([{"role": "user", "content": "hi"}]) == "ok"
    assert seen[0].headers["Authorization"] == f"Bearer {_fake_key()}"
    assert _other_key() not in seen[0].headers["Authorization"]


def test_redirects_not_followed_with_keyring_key() -> None:
    store = KeyringStore(backend=FakeKeyring())
    store.set("openai-compat", _fake_key())
    seen: list[httpx.Request] = []
    llm = OpenAICompatibleLLM(
        base_url="http://127.0.0.1:8080/v1",
        model="local",
        key_provider=lambda: store.get("openai-compat"),
        http_client=_recording_client(seen, redirect=True),
    )
    with pytest.raises(httpx.HTTPStatusError):
        llm.complete([{"role": "user", "content": "hi"}])
    assert len(seen) == 1
    assert "evil" not in str(seen[0].url)
    assert seen[0].headers["Authorization"] == f"Bearer {_fake_key()}"
