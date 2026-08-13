import pytest
from pydantic import ValidationError

from guardedcoder.models.envelope import CommandProfile, Envelope


def _profile() -> CommandProfile:
    return CommandProfile(
        profile_id="pytest",
        argv_template=["pytest", "--junitxml", "{junit_out}"],
        cwd=".",
        timeout_seconds=60,
        max_output_bytes=65536,
    )


def _envelope_kwargs() -> dict:
    return {
        "read_paths": ("src",),
        "write_paths": ("src",),
        "profiles": (_profile(),),
        "verify_profiles": ("pytest",),
        "max_steps": 10,
        "max_total_seconds": 300,
        "allow_delete": False,
        "allow_network": False,
        "config_digest": "abc",
    }


def test_identical_envelopes_have_equal_hash() -> None:
    a = Envelope(**_envelope_kwargs())
    b = Envelope(**_envelope_kwargs())
    assert a.envelope_hash == b.envelope_hash
    assert a.envelope_hash


def test_unknown_field_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        Envelope(**_envelope_kwargs(), extra=True)


def test_explicit_envelope_hash_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        Envelope(**_envelope_kwargs(), envelope_hash="deadbeef")


# Canonical JSON of Envelope fields excluding envelope_hash (sort_keys=True,
# separators=(",", ":")), then SHA-256. Computed independently of Envelope.
_PINNED_ENVELOPE_HASH = (
    "06694b4f73d148902ba8baa28be3110ed98a3b32a8ef22761b707a9829ba6f45"
)


def test_envelope_hash_matches_pinned_digest() -> None:
    env = Envelope(**_envelope_kwargs())
    assert env.envelope_hash == _PINNED_ENVELOPE_HASH


def test_argv_template_is_frozen_tuple() -> None:
    src = ["pytest", "--junitxml", "{junit_out}"]
    profile = CommandProfile(
        profile_id="pytest",
        argv_template=src,
        cwd=".",
        timeout_seconds=60,
        max_output_bytes=65536,
    )
    assert profile.argv_template == ("pytest", "--junitxml", "{junit_out}")
    assert isinstance(profile.argv_template, tuple)
    src.append("--extra")
    assert profile.argv_template == ("pytest", "--junitxml", "{junit_out}")
    with pytest.raises(TypeError):
        profile.argv_template[0] = "hacked"  # type: ignore[index]
