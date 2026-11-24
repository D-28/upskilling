"""Tests for rolling weekly branch selection and PR reconciliation helpers."""

from __future__ import annotations

from scripts.radar.reconcile_prs import choose_weekly_branch


def test_choose_weekly_branch_creates_fresh_when_none_exist() -> None:
    branch, is_open = choose_weekly_branch("2026-W47", set(), set())
    assert branch == "radar/weekly-2026-W47"
    assert is_open is False


def test_choose_weekly_branch_reuses_open_weekly_pr() -> None:
    branch, is_open = choose_weekly_branch(
        "2026-W47",
        open_branches={"radar/weekly-2026-W47"},
        closed_branches=set(),
    )
    assert branch == "radar/weekly-2026-W47"
    assert is_open is True


def test_choose_weekly_branch_advances_suffix_after_midweek_merge_or_close() -> None:
    branch, is_open = choose_weekly_branch(
        "2026-W47",
        open_branches=set(),
        closed_branches={"radar/weekly-2026-W47"},
    )
    assert branch == "radar/weekly-2026-W47-2"
    assert is_open is False

    branch2, is_open2 = choose_weekly_branch(
        "2026-W47",
        open_branches={"radar/weekly-2026-W47-2"},
        closed_branches={"radar/weekly-2026-W47"},
    )
    assert branch2 == "radar/weekly-2026-W47-2"
    assert is_open2 is True


def test_choose_weekly_branch_stays_within_harness_wall_regex_past_20_branches() -> None:
    import re

    closed = {"radar/weekly-2026-W47"} | {f"radar/weekly-2026-W47-{i}" for i in range(2, 25)}
    branch, is_open = choose_weekly_branch("2026-W47", open_branches=set(), closed_branches=closed)
    assert branch == "radar/weekly-2026-W47-25"
    assert is_open is False
    assert re.match(r"^radar/weekly-20[0-9]{2}-W[0-5][0-9](-[0-9]+)?$", branch)


def test_reconcile_prs_handles_transient_gh_errors_and_choose_branch_output_file(
    tmp_path,
    monkeypatch,
) -> None:
    import json
    import subprocess
    from pathlib import Path

    from scripts.radar import reconcile_prs as rec_mod
    from scripts.radar.state import load_feed_health

    repo_root = Path(__file__).resolve().parents[2]
    health_path = tmp_path / "feed-health.json"
    report_path = tmp_path / "feed-health-report.md"

    # 1. Transient `gh pr diff` failure must leave PR unreconciled for retry (not silently drop telemetry)
    def _fake_gh_transient_diff(args: list[str]) -> str:
        if args[:2] == ["pr", "list"]:
            return json.dumps(
                [
                    {"number": 41, "mergedAt": "2026-11-20T00:00:00Z", "headRefName": "radar/weekly-2026-W47"},
                    {"number": 42, "mergedAt": None, "headRefName": "radar/weekly-2026-W47-2"},
                ]
            )
        if args[:3] == ["pr", "diff", "41"]:
            raise subprocess.CalledProcessError(1, ["gh", "pr", "diff", "41"])
        if args[:3] == ["pr", "diff", "42"]:
            return "+No radar markers in this diff\n"
        raise AssertionError(f"Unexpected gh args: {args}")

    monkeypatch.setattr(rec_mod, "_run_gh", _fake_gh_transient_diff)
    count = rec_mod.reconcile_closed_weekly_prs(
        repo_root=repo_root,
        health_path=health_path,
        report_path=report_path,
    )
    assert count == 0
    health = load_feed_health(health_path)
    assert 41 not in health.reconciled_prs  # transient diff error -> retry later
    assert 42 in health.reconciled_prs  # valid empty diff -> marked reconciled
    assert report_path.is_file()

    # 2. allow_gh_failure=True preserves health & writes report even when `gh pr list` fails or returns bad JSON
    monkeypatch.setattr(rec_mod, "_run_gh", lambda _args: "{not-a-json-array}")
    count_fallback = rec_mod.reconcile_closed_weekly_prs(
        repo_root=repo_root,
        health_path=health_path,
        report_path=report_path,
        allow_gh_failure=True,
    )
    assert count_fallback == 0
    assert 42 in load_feed_health(health_path).reconciled_prs

    # 3. choose-branch --output-file writes clean JSON without relying on stdout parsing
    def _fake_gh_choose(args: list[str]) -> str:
        if "--state" in args and "open" in args:
            return json.dumps([{"headRefName": "radar/weekly-2026-W47-2"}])
        return json.dumps([{"headRefName": "radar/weekly-2026-W47"}])

    monkeypatch.setattr(rec_mod, "_run_gh", _fake_gh_choose)
    out_file = tmp_path / "branch-info.json"
    rc = rec_mod.main(["choose-branch", "--iso-week", "2026-W47", "--output-file", str(out_file)])
    assert rc == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload == {"branch": "radar/weekly-2026-W47-2", "has_open_pr": True}

