from __future__ import annotations

from pathlib import Path

from guardedcoder.models.command_result import CommandResult
from guardedcoder.models.verdict import VerdictStatus
from guardedcoder.sensors.junit_xml import junit_xml_verdict


def _result(path: Path | None, **overrides: object) -> CommandResult:
    values: dict[str, object] = {
        "started": True,
        "exit_code": 0,
        "timed_out": False,
        "stdout": "",
        "stderr": "",
        "truncated": False,
        "duration_seconds": 0.5,
        "junit_path": None if path is None else str(path),
    }
    values.update(overrides)
    return CommandResult(**values)


def test_missing_empty_or_wrong_run_path_is_error(tmp_path: Path) -> None:
    expected = tmp_path / "this-run.xml"
    wrong = tmp_path / "old-run.xml"
    wrong.write_text('<testsuite tests="1"/>', encoding="utf-8")

    missing = junit_xml_verdict(
        _result(expected), profile_id="unit", expected_junit_path=expected
    )
    stale = junit_xml_verdict(
        _result(wrong), profile_id="unit", expected_junit_path=expected
    )
    expected.write_bytes(b"")
    empty = junit_xml_verdict(
        _result(expected), profile_id="unit", expected_junit_path=expected
    )

    assert {missing.status, stale.status, empty.status} == {VerdictStatus.ERROR}


def test_junit_failures_produce_structured_fail_verdict(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        """<?xml version="1.0"?>
        <testsuite tests="2" failures="1" errors="0" skipped="0">
          <testcase classname="pkg.Test" name="good" />
          <testcase classname="pkg.Test" name="bad">
            <failure message="expected true">trace details</failure>
          </testcase>
        </testsuite>""",
        encoding="utf-8",
    )

    verdict = junit_xml_verdict(
        _result(path, exit_code=1), profile_id="unit", expected_junit_path=path
    )

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.tests_total == 2
    assert verdict.failures_count == 1
    assert verdict.errors_count == 0
    assert verdict.failures[0].test_id == "pkg.Test.bad"


def test_valid_junit_passes_even_with_skips(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        '<testsuites tests="3" failures="0" errors="0" skipped="1">'
        '<testsuite tests="3" failures="0" errors="0" skipped="1" />'
        "</testsuites>",
        encoding="utf-8",
    )

    verdict = junit_xml_verdict(
        _result(path), profile_id="unit", expected_junit_path=path
    )

    assert verdict.status is VerdictStatus.PASS
    assert verdict.skipped_count == 1


def test_junit_errors_produce_fail_verdict(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        """<?xml version="1.0"?>
        <testsuite tests="1" failures="0" errors="1" skipped="0">
          <testcase classname="pkg.Test" name="boom">
            <error message="boom">stack</error>
          </testcase>
        </testsuite>""",
        encoding="utf-8",
    )

    verdict = junit_xml_verdict(
        _result(path, exit_code=1), profile_id="unit", expected_junit_path=path
    )

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.errors_count == 1
    assert verdict.failures[0].test_id == "pkg.Test.boom"


def test_junit_failure_child_without_count_attr_is_fail(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        '<testsuite tests="1"><testcase name="x"><failure message="boom"/></testcase></testsuite>',
        encoding="utf-8",
    )

    verdict = junit_xml_verdict(
        _result(path), profile_id="unit", expected_junit_path=path
    )

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.failures[0].test_id == "x"


def test_junit_pass_summary_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        f'<testsuite tests="{"9" * 3000}" failures="0" errors="0" skipped="0"/>',
        encoding="utf-8",
    )

    verdict = junit_xml_verdict(
        _result(path), profile_id="unit", expected_junit_path=path
    )

    assert len(verdict.summary.encode("utf-8")) <= 2048
    assert verdict.status is VerdictStatus.PASS


def test_testsuites_child_failure_count_is_fail(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        '<testsuites tests="1"><testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase name="x"/></testsuite></testsuites>',
        encoding="utf-8",
    )

    verdict = junit_xml_verdict(
        _result(path), profile_id="unit", expected_junit_path=path
    )

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.failures_count == 1


def test_dtd_without_entity_is_error(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        '<!DOCTYPE testsuite>\n'
        '<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
        encoding="utf-8",
    )

    verdict = junit_xml_verdict(
        _result(path), profile_id="unit", expected_junit_path=path
    )

    assert verdict.status is VerdictStatus.ERROR


def test_junit_timeout_and_not_started_ignore_xml(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
        encoding="utf-8",
    )

    timed_out = junit_xml_verdict(
        _result(path, timed_out=True, exit_code=None),
        profile_id="unit",
        expected_junit_path=path,
    )
    not_started = junit_xml_verdict(
        _result(path, started=False, exit_code=None),
        profile_id="unit",
        expected_junit_path=path,
    )

    assert timed_out.status is VerdictStatus.TIMEOUT
    assert not_started.status is VerdictStatus.ERROR


def test_malformed_or_dangerous_xml_is_error(tmp_path: Path) -> None:
    path = tmp_path / "this-run.xml"
    path.write_text("<testsuite>", encoding="utf-8")
    malformed = junit_xml_verdict(
        _result(path), profile_id="unit", expected_junit_path=path
    )
    path.write_text(
        '<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]>'
        '<testsuite tests="1"><testcase name="x">&ext;</testcase></testsuite>',
        encoding="utf-8",
    )
    dangerous = junit_xml_verdict(
        _result(path), profile_id="unit", expected_junit_path=path
    )

    assert malformed.status is VerdictStatus.ERROR
    assert dangerous.status is VerdictStatus.ERROR

