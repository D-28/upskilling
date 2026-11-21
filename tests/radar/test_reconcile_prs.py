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
