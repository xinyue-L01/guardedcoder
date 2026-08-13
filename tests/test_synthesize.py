import hashlib
import json

from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.models.config import AppConfig
from guardedcoder.models.envelope import Envelope


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


def _config() -> AppConfig:
    return AppConfig.model_validate(_legal_config())


def test_cli_overrides_max_steps() -> None:
    env = synthesize_envelope(_config(), {"max_steps": 5})
    assert env.max_steps == 5


def test_unspecified_fields_equal_config_defaults() -> None:
    cfg = _config()
    env = synthesize_envelope(cfg, {"max_steps": 5})
    assert env.read_paths == cfg.read_paths
    assert env.write_paths == cfg.write_paths
    assert env.profiles == cfg.profiles
    assert env.verify_profiles == cfg.verify_profiles
    assert env.max_total_seconds == cfg.max_total_seconds
    assert env.allow_delete == cfg.allow_delete
    assert env.allow_network == cfg.allow_network


def test_returns_final_effective_values_not_diff() -> None:
    env = synthesize_envelope(_config(), {"max_steps": 5})
    assert isinstance(env, Envelope)
    dumped = env.model_dump(mode="json", exclude={"envelope_hash"})
    assert dumped == {
        "read_paths": ["src"],
        "write_paths": ["src"],
        "profiles": [
            {
                "profile_id": "pytest",
                "argv_template": ["pytest", "--junitxml", "{junit_out}"],
                "cwd": ".",
                "timeout_seconds": 60,
                "max_output_bytes": 65536,
                "sensor": None,
            }
        ],
        "verify_profiles": ["pytest"],
        "max_steps": 5,
        "max_total_seconds": 300,
        "allow_delete": False,
        "allow_network": False,
        "config_digest": env.config_digest,
    }
    assert env.config_digest
    assert env.envelope_hash
    assert set(dumped.keys()) != {"max_steps"}


def test_config_digest_is_sha256_of_canonical_appconfig() -> None:
    cfg = _config()
    env = synthesize_envelope(cfg, {"max_steps": 5})
    canonical = json.dumps(
        cfg.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert env.config_digest == expected
    unchanged = synthesize_envelope(cfg)
    assert unchanged.config_digest == expected
    assert unchanged.max_steps == cfg.max_steps
