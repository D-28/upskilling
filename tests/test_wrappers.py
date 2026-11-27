"""Unit and property tests for scripts/diff_context.py and scripts/test_summary.py."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scripts.diff_context import (
    DiffContextError,
    collect_diff_context,
    glob_match,
    parse_review_triggers,
)
from scripts.test_summary import TestSummaryError, parse_junit_xml, truncate_text

REPO_ROOT = Path(__file__).resolve().parent.parent

SAMPLE_REVIEW_MD = """\
# REVIEW.md

| # | Diff Trigger | Required Check |
|---|---|---|
| 1 | `scripts/radar/models.py`, `scripts/radar/state.py` | **Backward-compat load:** Safe defaults. |
| 2 | `.github/workflows/*.yml` | **NO UNDO:** Human sign-off required. |
| 3 | `tests/**` | **No fake green:** Reject newly added skips. |
| 4 | `skills/*/SKILL.md`, `REVIEW.md` | **STE-80:** Run ste_lint.py. |
"""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_repo(tmp_path: Path, *, with_review_md: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    if with_review_md:
        (repo / "REVIEW.md").write_text(SAMPLE_REVIEW_MD, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


# ---------------------------------------------------------------------------
# diff_context.py tests
# ---------------------------------------------------------------------------


def test_glob_match_patterns() -> None:
    assert glob_match("scripts/radar/models.py", "scripts/radar/models.py")
    assert not glob_match("scripts/radar/state.py", "scripts/radar/models.py")
    assert glob_match("tests/test_wrappers.py", "tests/**")
    assert glob_match("tests/radar/test_llm.py", "tests/**")
    assert not glob_match("tests_other/test_a.py", "tests/**")
    assert glob_match("skills/verify/SKILL.md", "skills/*/SKILL.md")
    assert not glob_match("skills/a/b/SKILL.md", "skills/*/SKILL.md")
    assert glob_match(".github/workflows/radar-ci.yml", ".github/workflows/*.yml")
    assert not glob_match(".github/workflows/sub/radar-ci.yml", ".github/workflows/*.yml")
    assert glob_match("a/b.py", "a/**/b.py")
    assert glob_match("a/x/y/b.py", "a/**/b.py")


def test_diff_context_base_branch_isolation_and_flags(tmp_path: Path) -> None:
    """PR branch and dirty working tree edits to REVIEW.md must never alter the rubric."""
    repo = _init_repo(tmp_path, with_review_md=True)
    _git(repo, "checkout", "-b", "feat/risky")

    # Attempt to erase all REVIEW.md rules in the PR branch.
    (repo / "REVIEW.md").write_text("# REVIEW.md\nNo checks!\n", encoding="utf-8")
    (repo / "scripts" / "radar").mkdir(parents=True)
    (repo / "scripts" / "radar" / "models.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_ok(): assert True\n", encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "pr changes")

    # Also dirty REVIEW.md in working tree to verify working tree is never read.
    (repo / "REVIEW.md").write_text("# Dirty working tree\n", encoding="utf-8")

    ctx = collect_diff_context(repo, base_ref="main", head_ref="HEAD", review_ref="main")
    assert ctx["review_md_present_on_ref"] is True
    assert ctx["review_md_source"] == "main:REVIEW.md"
    assert ctx["review_md_modified"] is True
    assert ctx["workflow_files_modified"] == [".github/workflows/ci.yml"]
    assert ctx["totals"]["files_changed"] == 4

    triggered_ids = [item["id"] for item in ctx["triggered_checks"]]
    # Rules 1, 2, 3, and 4 all come strictly from main:REVIEW.md.
    assert triggered_ids == ["1", "2", "3", "4"]
    by_id = {item["id"]: item for item in ctx["triggered_checks"]}
    assert by_id["1"]["matched_files"] == ["scripts/radar/models.py"]
    assert by_id["2"]["matched_files"] == [".github/workflows/ci.yml"]
    assert by_id["3"]["matched_files"] == ["tests/test_a.py"]
    assert by_id["4"]["matched_files"] == ["REVIEW.md"]


def test_diff_context_missing_review_md_degrades_gracefully(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, with_review_md=False)
    _git(repo, "checkout", "-b", "feat/add-file")
    (repo / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    _git(repo, "add", "hello.py")
    _git(repo, "commit", "-m", "add hello")

    ctx = collect_diff_context(repo, base_ref="main", head_ref="HEAD")
    assert ctx["review_md_present_on_ref"] is False
    assert ctx["review_md_source"] is None
    assert ctx["review_md_modified"] is False
    assert ctx["workflow_files_modified"] == []
    assert ctx["triggered_checks"] == []
    assert ctx["totals"] == {"files_changed": 1, "additions": 1, "deletions": 0}


def test_diff_context_invalid_ref_raises_and_cli_exits_nonzero(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    with pytest.raises(DiffContextError, match="no-such-ref"):
        collect_diff_context(repo, base_ref="no-such-ref", head_ref="HEAD")

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "diff_context.py"),
            "--repo-root",
            str(repo),
            "--base",
            "no-such-ref",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "no-such-ref" in proc.stderr


def test_parse_review_triggers_ignores_non_pattern_rows() -> None:
    md = "| # | Diff Trigger | Required Check |\n|---|---|---|\n| 1 | Plain prose | Check |\n"
    assert parse_review_triggers(md) == []


# ---------------------------------------------------------------------------
# test_summary.py tests
# ---------------------------------------------------------------------------


def _write_junit_xml(
    path: Path,
    cases: list[tuple[str, str, str | None, str, str]],
    *,
    wrap_testsuites: bool = True,
) -> Path:
    """Build a JUnit XML fixture from (classname, name, kind, message, body) tuples."""
    suite = ET.Element("testsuite", name="pytest", time="1.25")
    for classname, name, kind, message, body in cases:
        tc = ET.SubElement(suite, "testcase", classname=classname, name=name, time="0.1")
        if kind in {"failure", "error", "skipped"}:
            el = ET.SubElement(tc, kind, message=message)
            el.text = body

    if wrap_testsuites:
        root = ET.Element("testsuites")
        root.append(suite)
    else:
        root = suite

    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_parse_junit_xml_passing_failing_errored_skipped(tmp_path: Path) -> None:
    xml_path = _write_junit_xml(
        tmp_path / "junit.xml",
        [
            ("tests.test_a", "test_pass", None, "", ""),
            ("tests.test_a", "test_skip", "skipped", "not needed", ""),
            ("tests.test_b", "test_fail", "failure", "AssertionError: boom", "traceback line 1"),
            ("tests.test_b", "test_err", "error", "RuntimeError: setup", "setup trace"),
        ],
        wrap_testsuites=True,
    )
    summary = parse_junit_xml(xml_path, max_failures=10, max_excerpt_chars=200)
    assert summary["exit_code"] == 1
    assert summary["total"] == 4
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["errors"] == 1
    assert summary["skipped"] == 1
    assert summary["duration_s"] == 1.25
    assert summary["failures_truncated"] == 0
    assert [f["nodeid"] for f in summary["failures"]] == [
        "tests.test_b::test_fail",
        "tests.test_b::test_err",
    ]


def test_parse_junit_xml_single_testsuite_root_and_missing_file(tmp_path: Path) -> None:
    xml_path = _write_junit_xml(
        tmp_path / "passing.xml",
        [("tests.test_ok", "test_one", None, "", "")],
        wrap_testsuites=False,
    )
    summary = parse_junit_xml(xml_path)
    assert summary["exit_code"] == 0
    assert summary["passed"] == 1
    assert summary["failures"] == []

    with pytest.raises(TestSummaryError, match="not found"):
        parse_junit_xml(tmp_path / "does_not_exist.xml")


@given(
    outcomes=st.lists(
        st.sampled_from(["pass", "fail", "error", "skip"]),
        min_size=0,
        max_size=25,
    ),
    msg_len=st.integers(min_value=0, max_value=600),
    max_failures=st.integers(min_value=0, max_value=12),
    max_excerpt_chars=st.integers(min_value=1, max_value=120),
)
def test_parse_junit_xml_bounds_property(
    tmp_path_factory: pytest.TempPathFactory,
    outcomes: list[str],
    msg_len: int,
    max_failures: int,
    max_excerpt_chars: int,
) -> None:
    """Counts always balance and failure records/excerpts strictly obey caps."""
    tmp_dir = tmp_path_factory.mktemp("junit-prop")
    long_text = "x" * msg_len
    cases = []
    for idx, outcome in enumerate(outcomes):
        kind = None if outcome == "pass" else ("failure" if outcome == "fail" else outcome)
        cases.append(("tests.prop", f"test_{idx}", kind, long_text, long_text))

    xml_path = _write_junit_xml(tmp_dir / "prop.xml", cases)
    summary = parse_junit_xml(
        xml_path,
        max_failures=max_failures,
        max_excerpt_chars=max_excerpt_chars,
    )

    assert summary["total"] == (
        summary["passed"] + summary["failed"] + summary["errors"] + summary["skipped"]
    )
    expected_exit = 0 if (summary["failed"] == 0 and summary["errors"] == 0) else 1
    assert summary["exit_code"] == expected_exit

    failures = summary["failures"]
    assert len(failures) <= max_failures
    assert len(failures) + summary["failures_truncated"] == (
        summary["failed"] + summary["errors"]
    )
    for rec in failures:
        assert len(rec["message"]) <= max_excerpt_chars
        assert len(rec["excerpt"]) <= max_excerpt_chars


def test_truncate_text_bounds() -> None:
    assert truncate_text("hello", 10) == "hello"
    assert truncate_text("abcdef", 5) == "ab..."
    assert len(truncate_text("abcdef", 2)) == 2


def test_test_summary_cli_preserves_pytest_exit_code(tmp_path: Path) -> None:
    test_file = tmp_path / "test_mini.py"
    test_file.write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n\n"
        "def test_bad():\n    assert 1 == 2, 'mismatch'\n",
        encoding="utf-8",
    )

    # Failing run must return non-zero and valid bounded JSON.
    fail_proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "test_summary.py"),
            "--max-failures",
            "5",
            "--max-excerpt-chars",
            "80",
            "--json",
            "--",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fail_proc.returncode == 1
    data = json.loads(fail_proc.stdout)
    assert data["exit_code"] == 1
    assert data["total"] == 2
    assert data["passed"] == 1
    assert data["failed"] == 1
    assert len(data["failures"]) == 1
    assert len(data["failures"][0]["excerpt"]) <= 80

    # Passing subset must return 0.
    pass_proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "test_summary.py"),
            "--json",
            "--",
            "-k",
            "test_ok",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert pass_proc.returncode == 0
    pass_data = json.loads(pass_proc.stdout)
    assert pass_data["exit_code"] == 0
    assert pass_data["passed"] == 1
    assert pass_data["failed"] == 0
