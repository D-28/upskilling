#!/usr/bin/env python3
"""Deterministic pytest / JUnit XML JSON summary wrapper.

Runs pytest with a temporary --junitxml file (or parses an existing JUnit XML
report) and emits a compact, bounded JSON summary so agents get deterministic
counts and capped failure excerpts instead of noisy terminal logs. Preserves
pytest's exit code so callers fail closed on test failures.

Usage:
  python3 scripts/test_summary.py --junit-xml report.xml --json
  python3 scripts/test_summary.py --json -- -q tests/test_wrappers.py
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path


class TestSummaryError(RuntimeError):
    """Raised when JUnit XML input is missing or malformed."""

    __test__ = False


@dataclass(frozen=True)
class FailureRecord:
    nodeid: str
    kind: str  # "failure" | "error"
    message: str
    excerpt: str


def truncate_text(text: str, max_chars: int) -> str:
    """Deterministically cap text to at most max_chars characters."""
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 3:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 3] + "..."


def _iter_testsuites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        return list(root.findall("testsuite"))
    raise TestSummaryError(f"Unexpected JUnit XML root tag: <{root.tag}>")


def _format_nodeid(testcase: ET.Element) -> str:
    classname = (testcase.attrib.get("classname") or "").strip()
    name = (testcase.attrib.get("name") or "").strip()
    if classname and name:
        return f"{classname}::{name}"
    return name or classname or "<unknown>"


def parse_junit_xml(
    xml_path: Path,
    *,
    max_failures: int = 10,
    max_excerpt_chars: int = 400,
    exit_code: int | None = None,
) -> dict[str, object]:
    """Parse a JUnit XML file into a bounded summary dictionary."""
    if max_failures < 0:
        raise ValueError("max_failures must be >= 0")
    if max_excerpt_chars < 1:
        raise ValueError("max_excerpt_chars must be >= 1")
    if not xml_path.is_file():
        raise TestSummaryError(f"JUnit XML file not found: {xml_path}")
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        raise TestSummaryError(f"Malformed JUnit XML in {xml_path}: {exc}") from exc

    suites = _iter_testsuites(tree.getroot())

    total = 0
    passed = 0
    failed = 0
    errors = 0
    skipped = 0
    duration_s = 0.0
    all_failures: list[FailureRecord] = []

    for suite in suites:
        suite_time = suite.attrib.get("time")
        has_suite_time = suite_time is not None
        if has_suite_time:
            try:
                duration_s += float(suite_time)
            except ValueError:
                has_suite_time = False

        for tc in suite.findall("testcase"):
            total += 1
            if not has_suite_time:
                with contextlib.suppress(ValueError):
                    duration_s += float(tc.attrib.get("time", "0"))

            failure_el = tc.find("failure")
            error_el = tc.find("error")
            skipped_el = tc.find("skipped")

            if failure_el is not None:
                failed += 1
                all_failures.append(
                    FailureRecord(
                        nodeid=_format_nodeid(tc),
                        kind="failure",
                        message=truncate_text(
                            failure_el.attrib.get("message", ""), max_excerpt_chars
                        ),
                        excerpt=truncate_text(failure_el.text or "", max_excerpt_chars),
                    )
                )
            elif error_el is not None:
                errors += 1
                all_failures.append(
                    FailureRecord(
                        nodeid=_format_nodeid(tc),
                        kind="error",
                        message=truncate_text(
                            error_el.attrib.get("message", ""), max_excerpt_chars
                        ),
                        excerpt=truncate_text(error_el.text or "", max_excerpt_chars),
                    )
                )
            elif skipped_el is not None:
                skipped += 1
            else:
                passed += 1

    capped_failures = all_failures[:max_failures]
    failures_truncated = max(0, len(all_failures) - max_failures)
    derived_exit = 0 if (failed == 0 and errors == 0) else 1

    return {
        "exit_code": derived_exit if exit_code is None else exit_code,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "duration_s": round(duration_s, 3),
        "failures_truncated": failures_truncated,
        "failures": [asdict(f) for f in capped_failures],
    }


def _combine_runner_output(stderr: str, stdout: str) -> str:
    parts = [p.strip() for p in (stderr, stdout) if p and p.strip()]
    return "\n".join(parts)


def run_pytest_summary(
    pytest_args: list[str],
    *,
    max_failures: int = 10,
    max_excerpt_chars: int = 400,
) -> dict[str, object]:
    """Run pytest with a temporary JUnit XML file and return bounded summary."""
    with tempfile.TemporaryDirectory(prefix="test-summary-") as tmp_dir:
        xml_path = Path(tmp_dir) / "junit.xml"
        cmd = [sys.executable, "-m", "pytest", f"--junitxml={xml_path}", *pytest_args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        combined_output = _combine_runner_output(proc.stderr, proc.stdout)

        if xml_path.is_file():
            payload = parse_junit_xml(
                xml_path,
                max_failures=max_failures,
                max_excerpt_chars=max_excerpt_chars,
                exit_code=proc.returncode,
            )
            if proc.returncode != 0 and not payload["failures"] and combined_output:
                payload["runner_excerpt"] = truncate_text(combined_output, max_excerpt_chars)
            return payload

        return {
            "exit_code": proc.returncode,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1 if proc.returncode != 0 else 0,
            "skipped": 0,
            "duration_s": 0.0,
            "failures_truncated": 0,
            "failures": [],
            "runner_excerpt": truncate_text(
                combined_output or "pytest exited without JUnit XML",
                max_excerpt_chars,
            ),
        }


def _format_text(payload: dict[str, object]) -> str:
    lines = [
        f"Test Summary (exit={payload['exit_code']}): "
        f"{payload['passed']} passed, {payload['failed']} failed, "
        f"{payload['errors']} errors, {payload['skipped']} skipped "
        f"(total={payload['total']}, {payload['duration_s']}s)",
    ]
    failures = payload["failures"]
    assert isinstance(failures, list)
    for item in failures:
        lines.append(f"  - [{item['kind']}] {item['nodeid']}: {item['message']}")
    truncated = payload["failures_truncated"]
    assert isinstance(truncated, int)
    if truncated > 0:
        lines.append(f"  ... ({truncated} additional failure(s) truncated)")
    if "runner_excerpt" in payload:
        lines.append(f"  Runner output: {payload['runner_excerpt']}")
    return "\n".join(lines)


def _split_argv(argv: list[str]) -> tuple[list[str], list[str] | None]:
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1 :]
    return argv, None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run pytest or parse JUnit XML and emit a bounded JSON test summary."
        )
    )
    parser.add_argument(
        "--junit-xml",
        type=Path,
        default=None,
        help="Path to an existing JUnit XML file to parse instead of running pytest.",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=10,
        help="Maximum number of failure records to include (default: 10).",
    )
    parser.add_argument(
        "--max-excerpt-chars",
        type=int,
        default=400,
        help="Maximum character length per failure message/excerpt (default: 400).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit compact machine-readable JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    own_args, pytest_args = _split_argv(raw_argv)

    parser = build_parser()
    args = parser.parse_args(own_args)

    if args.max_failures < 0:
        print("error: --max-failures must be >= 0", file=sys.stderr)
        return 2
    if args.max_excerpt_chars < 1:
        print("error: --max-excerpt-chars must be >= 1", file=sys.stderr)
        return 2
    if args.junit_xml is not None and pytest_args is not None:
        print(
            "error: --junit-xml cannot be combined with '-- <pytest args>'",
            file=sys.stderr,
        )
        return 2

    try:
        if args.junit_xml is not None:
            payload = parse_junit_xml(
                args.junit_xml,
                max_failures=args.max_failures,
                max_excerpt_chars=args.max_excerpt_chars,
            )
        else:
            payload = run_pytest_summary(
                pytest_args or [],
                max_failures=args.max_failures,
                max_excerpt_chars=args.max_excerpt_chars,
            )
    except TestSummaryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_format_text(payload))

    exit_code = payload["exit_code"]
    assert isinstance(exit_code, int)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
