import pytest

from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.errors import ConfigError
from guardedcoder.governance.hard_rules import (
    ProfileKind,
    argv_is_hard_forbidden,
    classify_profile,
)
from guardedcoder.models.config import AppConfig
from guardedcoder.models.envelope import CommandProfile, Envelope


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


def _profile(
    profile_id: str = "pytest",
    argv_template: list[str] | None = None,
) -> CommandProfile:
    return CommandProfile(
        profile_id=profile_id,
        argv_template=argv_template or ["pytest", "--junitxml", "{junit_out}"],
        cwd=".",
        timeout_seconds=60,
        max_output_bytes=65536,
    )


def _envelope(*profiles: CommandProfile) -> Envelope:
    if not profiles:
        profiles = (_profile(),)
    return Envelope(
        read_paths=("src",),
        write_paths=("src",),
        profiles=profiles,
        verify_profiles=tuple(p.profile_id for p in profiles),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )


def test_profile_kind_values() -> None:
    assert set(ProfileKind) == {"unknown", "hard_forbidden", "allowed"}


def test_pip3_install_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["pip3", "install", "pkg"])


def test_pip3_12_install_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["pip3.12", "install", "pkg"])


def test_pip_exe_install_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["pip.exe", "install", "pkg"])


def test_windows_path_pip_install_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden([r"C:\Python\Scripts\pip.exe", "install", "pkg"])


def test_unix_path_pip3_install_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["/usr/bin/pip3", "install", "pkg"])


def test_mixed_case_path_pip_install_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden([r"C:\Python\Scripts\PIP.EXE", "INSTALL", "pkg"])


def test_sudo_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["sudo", "pytest"])


def test_push_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["git", "push"])


def test_publish_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["twine", "publish"])


def test_deploy_is_hard_forbidden() -> None:
    assert argv_is_hard_forbidden(["deploy", "prod"])


def test_legal_pytest_is_not_hard_forbidden() -> None:
    assert not argv_is_hard_forbidden(["pytest", "--junitxml", "{junit_out}"])


def test_pip_without_install_is_not_hard_forbidden() -> None:
    assert not argv_is_hard_forbidden(["pip", "list"])


def test_missing_profile_is_unknown() -> None:
    result = classify_profile(_envelope(), "missing")
    assert result == ProfileKind.unknown
    assert result == "unknown"


def test_missing_profile_named_like_pip_is_unknown() -> None:
    result = classify_profile(_envelope(), "pip")
    assert result == ProfileKind.unknown


def test_hard_forbidden_profile_in_envelope_is_hard_forbidden() -> None:
    env = _envelope(_profile("pip_install", ["pip3", "install", "pkg"]))
    result = classify_profile(env, "pip_install")
    assert result == ProfileKind.hard_forbidden
    assert result == "hard_forbidden"


def test_legal_profile_is_allowed() -> None:
    result = classify_profile(_envelope(), "pytest")
    assert result == ProfileKind.allowed
    assert result == "allowed"


def test_synthesize_rejects_pip3_install() -> None:
    with pytest.raises(ConfigError):
        synthesize_envelope(_config_with_argv(["pip3", "install", "pkg"]))


def test_synthesize_rejects_pip_exe_install() -> None:
    with pytest.raises(ConfigError):
        synthesize_envelope(_config_with_argv(["pip.exe", "install", "pkg"]))


def test_synthesize_rejects_path_pip_install() -> None:
    with pytest.raises(ConfigError):
        synthesize_envelope(
            _config_with_argv([r"C:\Python\Scripts\pip.exe", "install", "pkg"])
        )


def test_synthesize_rejects_unix_path_pip3_install() -> None:
    with pytest.raises(ConfigError):
        synthesize_envelope(_config_with_argv(["/usr/bin/pip3", "install", "pkg"]))


def test_synthesize_rejects_sudo() -> None:
    with pytest.raises(ConfigError):
        synthesize_envelope(_config_with_argv(["sudo", "ls"]))


def test_synthesize_rejects_deploy() -> None:
    with pytest.raises(ConfigError):
        synthesize_envelope(_config_with_argv(["deploy"]))
