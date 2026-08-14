from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from defusedxml.common import (
    DTDForbidden,
    EntitiesForbidden,
    ExternalReferenceForbidden,
)

from guardedcoder.models.command_result import CommandResult
from guardedcoder.models.verdict import FailureEntry, Verdict, VerdictStatus
from guardedcoder.sensors.common import bounded_summary, output_digest

_MAX_FAILURES = 20


def _error(result: CommandResult, profile_id: str, message: str) -> Verdict:
    return Verdict(
        profile_id=profile_id,
        sensor="junit_xml",
        status=VerdictStatus.ERROR,
        exit_code=result.exit_code,
        summary=bounded_summary(message),
        output_truncated=result.truncated,
        output_sha256=output_digest(result),
        duration_seconds=result.duration_seconds,
    )


def _integer(element: Element, name: str) -> int:
    value = int(element.attrib.get(name, "0"))
    if value < 0:
        raise ValueError(f"negative {name}")
    return value


def _counts(root: Element) -> tuple[int, int, int, int]:
    names = ("tests", "failures", "errors", "skipped")
    own = [_integer(root, name) for name in names]
    if root.tag != "testsuites":
        return own[0], own[1], own[2], own[3]
    suites = list(root.findall("./testsuite"))
    children = [sum(_integer(suite, name) for suite in suites) for name in names]
    return tuple(max(left, right) for left, right in zip(own, children, strict=True))


def _failure_entries(root: Element) -> tuple[FailureEntry, ...]:
    entries: list[FailureEntry] = []
    for case in root.iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        classname = case.attrib.get("classname", "").strip()
        name = case.attrib.get("name", "unknown").strip()
        test_id = f"{classname}.{name}" if classname else name
        message = problem.attrib.get("message") or problem.text or problem.tag
        entries.append(
            FailureEntry(
                test_id=bounded_summary(test_id, limit=512),
                message=bounded_summary(message.strip(), limit=1024),
            )
        )
        if len(entries) >= _MAX_FAILURES:
            break
    return tuple(entries)


def junit_xml_verdict(
    result: CommandResult,
    *,
    profile_id: str,
    expected_junit_path: str | Path,
) -> Verdict:
    expected = Path(expected_junit_path).resolve(strict=False)
    if not result.started:
        return _error(result, profile_id, "command did not start")
    if result.timed_out:
        return Verdict(
            profile_id=profile_id,
            sensor="junit_xml",
            status=VerdictStatus.TIMEOUT,
            exit_code=result.exit_code,
            summary=bounded_summary("command timed out"),
            output_truncated=result.truncated,
            output_sha256=output_digest(result),
            duration_seconds=result.duration_seconds,
        )
    if result.junit_path is None:
        return _error(result, profile_id, "command result has no JUnit path")
    actual = Path(result.junit_path).resolve(strict=False)
    if actual != expected:
        return _error(result, profile_id, "JUnit path does not belong to this run")
    if not actual.is_file():
        return _error(result, profile_id, "JUnit artifact is missing")
    try:
        if actual.stat().st_size == 0:
            return _error(result, profile_id, "JUnit artifact is empty")
        root = ElementTree.parse(actual, forbid_dtd=True).getroot()
        if root.tag not in {"testsuite", "testsuites"}:
            return _error(result, profile_id, "unsupported JUnit root element")
        tests, failures, errors, skipped = _counts(root)
        entries = _failure_entries(root)
    except (
        OSError,
        ValueError,
        ElementTree.ParseError,
        DTDForbidden,
        EntitiesForbidden,
        ExternalReferenceForbidden,
    ) as exc:
        return _error(result, profile_id, f"invalid JUnit artifact: {type(exc).__name__}")

    status = (
        VerdictStatus.FAIL
        if failures or errors or entries
        else VerdictStatus.PASS
    )
    return Verdict(
        profile_id=profile_id,
        sensor="junit_xml",
        status=status,
        exit_code=result.exit_code,
        summary=bounded_summary(
            f"JUnit tests={tests} failures={failures} errors={errors} "
            f"skipped={skipped}"
        ),
        failures=entries,
        output_truncated=result.truncated,
        output_sha256=output_digest(result),
        duration_seconds=result.duration_seconds,
        tests_total=tests,
        failures_count=failures,
        errors_count=errors,
        skipped_count=skipped,
    )

