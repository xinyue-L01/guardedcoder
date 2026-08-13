import pytest
from pydantic import ValidationError

from guardedcoder.models.config import AppConfig


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


def test_legal_dict_validates() -> None:
    cfg = AppConfig.model_validate(_legal_config())
    assert cfg.config_schema_version == "1"


def test_api_key_raises_validation_error() -> None:
    data = {**_legal_config(), "api_key": "sk-test"}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_unknown_key_raises_validation_error() -> None:
    data = {**_legal_config(), "unknown": True}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)
