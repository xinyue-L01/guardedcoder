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
