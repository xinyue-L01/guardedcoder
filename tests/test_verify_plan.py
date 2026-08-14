from __future__ import annotations

import inspect

from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.sensors.plan import build_verify_plan
import guardedcoder.sensors.plan as plan_module


def _envelope() -> Envelope:
    return Envelope(
        read_paths=(".",),
        write_paths=("src",),
        profiles=(
            CommandProfile(
                profile_id="unit",
                argv_template=("pytest",),
                cwd=".",
                timeout_seconds=30,
                max_output_bytes=1024,
                sensor="junit_xml",
            ),
            CommandProfile(
                profile_id="lint",
                argv_template=("ruff", "check", "."),
                cwd=".",
                timeout_seconds=30,
                max_output_bytes=1024,
                sensor="exit_code",
            ),
        ),
        verify_profiles=("lint", "unit"),
        max_steps=4,
        max_total_seconds=60,
        allow_delete=False,
        allow_network=False,
        config_digest="cfg",
    )


def test_verify_plan_is_deterministic_data_only() -> None:
    plan = build_verify_plan(_envelope())

    assert plan.verify_profile_ids == ("lint", "unit")
    assert "run_profile" not in inspect.getsource(plan_module)


def test_verify_plan_rejects_missing_or_duplicate_profile_ids() -> None:
    envelope = _envelope()
    duplicate = envelope.model_copy(update={"verify_profiles": ("unit", "unit")})
    missing = envelope.model_copy(update={"verify_profiles": ("missing",)})

    for invalid in (duplicate, missing):
        try:
            build_verify_plan(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid verify profile list was accepted")

