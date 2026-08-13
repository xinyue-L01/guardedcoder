from pathlib import Path

import pytest

from guardedcoder.config.load import load_app_config
from guardedcoder.config.paths import user_config_path
from guardedcoder.errors import ConfigError

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


def _write_toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_unknown_key_raises_config_error(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, _LEGAL_TOML + "\nunknown = true\n")
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_shell_true_raises_config_error(tmp_path: Path) -> None:
    head, tail = _LEGAL_TOML.rsplit("max_output_bytes = 65536\n", 1)
    body = head + "max_output_bytes = 65536\nshell = true\n" + tail
    path = _write_toml(tmp_path, body)
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_cmdline_string_raises_config_error(tmp_path: Path) -> None:
    body = _LEGAL_TOML.rstrip() + '\ncmdline = "pytest -q"\n'
    path = _write_toml(tmp_path, body)
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_secret_like_api_key_raises_config_error(tmp_path: Path) -> None:
    body = _LEGAL_TOML + "\napi_key = \"" + "sk" + "-test\"\n"
    path = _write_toml(tmp_path, body)
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_secret_like_token_raises_config_error(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, _LEGAL_TOML + '\ntoken = "t"\n')
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_secret_like_password_raises_config_error(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, _LEGAL_TOML + '\npassword = "p"\n')
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_pem_private_key_value_raises_config_error(tmp_path: Path) -> None:
    pem = "-----BEGIN PRIVATE KEY-----\\nMIIFAKE\\n-----END PRIVATE KEY-----"
    body = _LEGAL_TOML.replace('model = "local"', f'model = "{pem}"')
    path = _write_toml(tmp_path, body)
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_type_error_raises_config_error(tmp_path: Path) -> None:
    body = _LEGAL_TOML.replace("max_steps = 10", 'max_steps = "nope"')
    path = _write_toml(tmp_path, body)
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_non_utf8_toml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xff\xfe invalid utf-8")
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_legal_toml_loaded_twice_equal(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, _LEGAL_TOML)
    first = load_app_config(path)
    second = load_app_config(path)
    assert first == second
    assert first.read_paths == ("src",)
    assert first.profiles[0].argv_template == ("pytest", "--junitxml", "{junit_out}")


def test_load_does_not_read_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("api_key=" + "sk" + "-from-env\nmax_steps=999\n", encoding="utf-8")
    path = _write_toml(tmp_path, _LEGAL_TOML)
    cfg = load_app_config(path)
    assert cfg.max_steps == 10


def test_user_config_path_override_skips_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    got = user_config_path(tmp_path)
    assert got == tmp_path / "guardedcoder" / "config.toml"
