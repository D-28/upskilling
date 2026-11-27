"""Deterministic Job 2 helpers for rolling weekly Draft PR branch selection and PR telemetry reconciliation.

Runs strictly in Job 2 (zero LLM calls, zero untrusted web fetches, GitHub API only via `gh`).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.radar.fetcher import load_feed_registry
from scripts.radar.rubric import parse_radar_markers
from scripts.radar.security import redact_secrets
from scripts.radar.state import (
    format_active_health_summary,
    generate_feed_health_report,
    load_feed_health,
    reconcile_pr_outcome,
    save_feed_health,
)


def choose_weekly_branch(
    iso_week: str,
    open_branches: set[str],
    closed_branches: set[str],
) -> tuple[str, bool]:
    """Select the active rolling weekly branch name and whether it already has an open PR.

    - Reuses `radar/weekly-{iso_week}` (or suffixed `-2`, `-3`, ...) if currently open.
    - If `radar/weekly-{iso_week}` was already merged/closed mid-week, advances to
      `radar/weekly-{iso_week}-2` (etc.) so we never push onto a dead PR.
    - Always emits a numeric suffix matching Harness Wall 1 (`^radar/weekly-YYYY-Www(-N)?$`).
    """
    base = f"radar/weekly-{iso_week}"
    for idx in range(1, 1000):
        candidate = base if idx == 1 else f"{base}-{idx}"
        if candidate in open_branches:
            return candidate, True
        if candidate not in closed_branches:
            return candidate, False
    return f"{base}-1000", False


def _run_gh(args: list[str]) -> str:
    proc = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _parse_gh_json_list(raw_json: str, *, context: str) -> list[dict[str, object]]:
    text = (raw_json or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from `gh {context}`: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError(
            f"Expected JSON array from `gh {context}`, got {type(parsed).__name__}"
        )
    return [item for item in parsed if isinstance(item, dict)]


def _extract_markers_from_pr_diff(pr_number: int) -> list[tuple[str, str, str]] | None:
    """Extract all radar-id markers added by a weekly radar PR from its diff.

    Returns `None` on transient `gh` errors so callers can retry on a later run instead
    of permanently marking the PR reconciled with zero telemetry.
    """
    try:
        diff_text = _run_gh(["pr", "diff", str(pr_number)])
    except (subprocess.CalledProcessError, OSError):
        return None
    added_lines = "\n".join(
        line[1:] for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    return parse_radar_markers(added_lines)


def _extract_landed_ids_on_main(repo_root: Path) -> set[str]:
    """Collect all radar-id hashes currently present under `radar/*.md` on main."""
    landed: set[str] = set()
    radar_dir = repo_root / "radar"
    if not radar_dir.is_dir():
        return landed
    for md_file in radar_dir.glob("*.md"):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        for item_id, _, _ in parse_radar_markers(text):
            landed.add(item_id)
    return landed


def reconcile_closed_weekly_prs(
    *,
    repo_root: Path,
    health_path: Path,
    report_path: Path | None = None,
    summary_path: Path | None = None,
    allow_gh_failure: bool = False,
) -> int:
    """Reconcile recently merged/closed `radar/weekly-*` PRs into feed-health.json."""
    registry = load_feed_registry(repo_root / "radar" / "feeds.yaml")
    health = load_feed_health(health_path)

    try:
        raw_json = _run_gh(
            [
                "pr",
                "list",
                "--state",
                "closed",
                "--search",
                "head:radar/weekly-",
                "--limit",
                "25",
                "--json",
                "number,mergedAt,headRefName",
            ]
        )
        prs = _parse_gh_json_list(raw_json, context="pr list (closed)")
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        if not allow_gh_failure:
            raise
        raw_detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            raw_detail = f"{raw_detail}: {exc.stderr.strip()}"
        safe_err = redact_secrets(raw_detail).replace("\r", " ").replace("\n", " ")[:240]
        print(
            f"::warning title=Radar PR reconciliation skipped::"
            f"Transient gh error during PR reconciliation (state preserved): {safe_err}",
            file=sys.stderr,
        )
        prs = []

    landed_ids = _extract_landed_ids_on_main(repo_root)

    reconciled_count = 0
    for pr in prs:
        raw_num = pr.get("number")
        if raw_num is None:
            continue
        try:
            number = int(str(raw_num))
        except ValueError:
            continue
        if number in health.reconciled_prs:
            continue
        merged = bool(pr.get("mergedAt"))
        staged_markers = _extract_markers_from_pr_diff(number)
        if staged_markers is None:
            # Transient diff fetch error: leave unreconciled so next run retries cleanly
            print(
                f"::warning title=Radar PR diff unavailable::"
                f"Could not fetch diff for PR #{number}; will retry reconciliation next run.",
                file=sys.stderr,
            )
            continue
        if not staged_markers:
            # Valid diff with zero radar markers: mark reconciled to avoid endless retries
            health.reconciled_prs.append(number)
            continue
        merged_at = pr.get("mergedAt")
        health = reconcile_pr_outcome(
            health,
            registry,
            pr_number=number,
            merged=merged,
            staged_markers=staged_markers,
            landed_item_ids=landed_ids,
            reconciled_at=str(merged_at) if merged_at else None,
        )
        reconciled_count += 1

    save_feed_health(health_path, health)
    if report_path is not None:
        report = generate_feed_health_report(health, registry)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
    if summary_path is not None:
        active_alerts = format_active_health_summary(health, registry)
        if active_alerts:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("a", encoding="utf-8") as fh:
                fh.write(active_alerts.rstrip() + "\n")
    return reconciled_count


def _cmd_choose_branch(args: argparse.Namespace) -> int:
    open_prs = _parse_gh_json_list(
        _run_gh(
            [
                "pr",
                "list",
                "--state",
                "open",
                "--search",
                f"head:radar/weekly-{args.iso_week}",
                "--json",
                "headRefName",
            ]
        ),
        context="pr list (open)",
    )
    closed_prs = _parse_gh_json_list(
        _run_gh(
            [
                "pr",
                "list",
                "--state",
                "closed",
                "--search",
                f"head:radar/weekly-{args.iso_week}",
                "--json",
                "headRefName",
            ]
        ),
        context="pr list (closed)",
    )
    branch, is_open = choose_weekly_branch(
        args.iso_week,
        open_branches={str(p["headRefName"]) for p in open_prs if p.get("headRefName")},
        closed_branches={str(p["headRefName"]) for p in closed_prs if p.get("headRefName")},
    )
    payload = {"branch": branch, "has_open_pr": is_open}
    if args.output_file:
        out_path = Path(args.output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    count = reconcile_closed_weekly_prs(
        repo_root=Path(args.repo_root).resolve(),
        health_path=Path(args.health_path),
        report_path=Path(args.report_out) if args.report_out else None,
        summary_path=Path(args.summary_out) if args.summary_out else None,
        allow_gh_failure=bool(args.allow_gh_failure),
    )
    print(json.dumps({"reconciled_prs": count}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reconcile_prs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_choose = sub.add_parser("choose-branch")
    p_choose.add_argument("--iso-week", required=True)
    p_choose.add_argument("--output-file", default="", help="Optional JSON file path to write branch info.")
    p_choose.set_defaults(func=_cmd_choose_branch)

    p_rec = sub.add_parser("reconcile")
    p_rec.add_argument("--repo-root", default=".")
    p_rec.add_argument("--health-path", required=True)
    p_rec.add_argument("--report-out", default="")
    p_rec.add_argument(
        "--summary-out",
        default="",
        help="Optional $GITHUB_STEP_SUMMARY path; appends alerts only when >= 1 candidate is flagged.",
    )
    p_rec.add_argument(
        "--allow-gh-failure",
        action="store_true",
        help="Warn and preserve state on transient gh API errors instead of aborting Job 2.",
    )
    p_rec.set_defaults(func=_cmd_reconcile)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
