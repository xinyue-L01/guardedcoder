from pathlib import Path

import pytest

from guardedcoder.config.load import load_app_config
from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.errors import ConfigError
from guardedcoder.governance.hard_rules import assert_hard_rules
from guardedcoder.models.config import AppConfig

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


def _legal_config() -> dict:
    return {
        "config_schema_version": "1",
        "provider": {
            "provider_id": "openai-compat",
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "local",
            "timeout_seconds": 30,
        },
        "read_paths": ("src",),
        "write_paths": ("src",),
        "profiles": (
            {
                "profile_id": "pytest",
                "argv_template": ["pytest", "--junitxml", "{junit_out}"],
                "cwd": ".",
                "timeout_seconds": 60,
                "max_output_bytes": 65536,
            },
        ),
        "verify_profiles": ("pytest",),
        "max_steps": 10,
        "max_total_seconds": 300,
        "command_timeout_seconds": 60,
        "max_output_bytes": 65536,
        "max_patch_bytes": 1_000_000,
        "allow_delete": False,
        "allow_network": False,
    }


def _config_with_argv(argv_template: list[str], profile_id: str = "bad") -> AppConfig:
    data = _legal_config()
    data["profiles"] = (
        {
            "profile_id": profile_id,
            "argv_template": argv_template,
            "cwd": ".",
            "timeout_seconds": 60,
            "max_output_bytes": 65536,
        },
    )
    data["verify_profiles"] = (profile_id,)
    return AppConfig.model_validate(data)


def test_legal_pytest_profile_passes() -> None:
    assert_hard_rules(AppConfig.model_validate(_legal_config()))


def test_pip_install_raises_config_error() -> None:
    cfg = _config_with_argv(["PIP", "Install", "pkg"])
    with pytest.raises(ConfigError):
        assert_hard_rules(cfg)


def test_push_raises_config_error() -> None:
    cfg = _config_with_argv(["git", "PUSH"])
    with pytest.raises(ConfigError):
        assert_hard_rules(cfg)


def test_publish_raises_config_error() -> None:
    cfg = _config_with_argv(["twine", "Publish"])
    with pytest.raises(ConfigError):
        assert_hard_rules(cfg)


def test_load_app_config_rejects_pip_install(tmp_path: Path) -> None:
    body = _LEGAL_TOML.replace(
        'argv_template = ["pytest", "--junitxml", "{junit_out}"]',
        'argv_template = ["pip", "install", "pkg"]',
    )
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_synthesize_envelope_rejects_push() -> None:
    cfg = _config_with_argv(["git", "push"])
    with pytest.raises(ConfigError):
        synthesize_envelope(cfg)


def test_synthesize_envelope_rejects_publish() -> None:
    cfg = _config_with_argv(["python", "-m", "build", "publish"])
    with pytest.raises(ConfigError):
        synthesize_envelope(cfg)
