"""Pipeline orchestrator and CLI entrypoints for the Automated Signal Ingestion Pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from scripts.radar.config import PipelineConfig
from scripts.radar.fetcher import (
    build_fast_lane_candidate,
    enrich_survivor_body,
    fetch_candidates,
    load_feed_registry,
)
from scripts.radar.inventory import build_repo_inventory, load_target_repo_context
from scripts.radar.llm import BudgetExceededError, GeminiRadarClient, RadarLLMClient
from scripts.radar.models import (
    CandidateItem,
    FeedFetchSummary,
    RunResult,
    ScoredSurvivor,
    SeenRecord,
    SeenState,
    Stage1ItemVerdict,
)
from scripts.radar.rubric import merge_into_weekly_digest, score_stage2_analysis
from scripts.radar.security import (
    filter_allowed_repo_paths,
    redact_secrets,
    sanitize_single_line,
)
from scripts.radar.state import (
    apply_run_result_to_state,
    generate_feed_health_report,
    load_feed_health,
    load_seen_state,
    save_feed_health,
    save_seen_state,
)


def current_iso_week(now: datetime | None = None) -> str:
    """Return ISO week label like `2026-W47`."""
    dt = now or datetime.now(UTC)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def build_job_summary_markdown(result: RunResult) -> str:
    """Format a crisp, sanitized Markdown summary suitable for GitHub Actions & PR bodies."""
    lines = [
        f"## Radar Ingestion Summary — `{result.iso_week}` (`{result.mode}`)",
        "",
        f"- **Run timestamp:** `{sanitize_single_line(result.run_at, 64)}`",
        f"- **New candidates after Stage 0:** `{result.candidates_fetched}`",
        f"- **Stage 1 reviewed:** `{result.stage1_reviewed}`",
        f"- **Stage 2 evaluated:** `{len(result.stage2_results)}`",
        f"- **Staged (score ≥ 6/10):** `{len(result.staged_items)}` (High Signal ≥ 9/10: `{'yes' if result.has_high_signal else 'no'}`)",
        f"- **Estimated API cost:** `${result.total_estimated_cost_usd:.4f}`"
        + (" *(cost cap triggered)*" if result.cost_cap_triggered else ""),
    ]
    if result.traces:
        models_used = sorted(
            {
                f"{t.stage}:{t.requested_model}->{t.resolved_model_version or 'unreported'} ({t.api_version}/{t.thinking_level})"
                for t in result.traces
            }
        )
        lines.append(
            f"- **Models resolved:** {', '.join(f'`{sanitize_single_line(m, 90)}`' for m in models_used)}"
        )

    if result.staged_items:
        lines.extend(["", "### Survivors Crossing the Bar", ""])
        for s in result.staged_items:
            safe_title = sanitize_single_line(s.item.title, 180)
            safe_feed = sanitize_single_line(s.item.feed_id, 60)
            targets = ", ".join(filter_allowed_repo_paths(s.analysis.target_repo_files)) or "radar/"
            lines.append(
                f"- **[{s.score}/10 · {s.disposition}]** {safe_title} (`{safe_feed}`) -> {targets}"
            )
    else:
        lines.extend(["", "_Nothing crossed the bar this run._"])

    failed_feeds = [f for f in result.feed_summaries if not f.ok]
    if failed_feeds:
        lines.extend(["", "### Feed Fetch Errors", ""])
        for f in failed_feeds:
            safe_err = sanitize_single_line(redact_secrets(f.error), 200)
            lines.append(f"- `{sanitize_single_line(f.feed_id, 60)}`: {safe_err}")

    lines.append("")
    return "\n".join(lines)


def run_pipeline(
    config: PipelineConfig,
    *,
    seen: SeenState,
    mode: str = "observe",
    fast_lane_url: str | None = None,
    llm_client: RadarLLMClient | None = None,
    http_get: Callable[[str], tuple[str, bytes]] | None = None,
    offline_candidates: list[CandidateItem] | None = None,
    exclude_repo_files: list[str] | None = None,
    now: datetime | None = None,
) -> RunResult:
    """Execute Stage 0 -> Stage 1 -> Survivor Enricher -> Stage 2 -> Deterministic Scorer."""
    run_dt = now or datetime.now(UTC)
    run_at = run_dt.isoformat()
    iso_week = current_iso_week(run_dt)
    excluded = tuple(exclude_repo_files or ())

    feed_summaries: list[FeedFetchSummary] = []
    if offline_candidates is not None:
        candidates = list(offline_candidates)[: config.max_items_per_run]
    elif fast_lane_url:
        candidates = [
            build_fast_lane_candidate(fast_lane_url, config=config, http_get=http_get)
        ]
    else:
        registry = load_feed_registry(config.feeds_path)
        candidates, feed_summaries = fetch_candidates(
            registry, seen, config, now=run_dt, http_get=http_get
        )

    result = RunResult(
        run_at=run_at,
        iso_week=iso_week,
        mode=mode,  # type: ignore[arg-type]
        fast_lane_url=fast_lane_url,
        feed_summaries=feed_summaries,
        candidates_fetched=len(candidates),
    )

    # Bootstrap mode: mark all current feed items seen with $0 LLM spend
    if mode == "bootstrap":
        for item in candidates:
            result.new_seen_records[item.item_id] = SeenRecord(
                canonical_url=item.canonical_url,
                title_hash=item.title_hash,
                content_hash=item.content_hash,
                feed_id=item.feed_id,
                first_seen_at=run_at,
                verdict="BOOTSTRAP_SEEDED",
            )
        result.summary_markdown = build_job_summary_markdown(result)
        return result

    if not candidates:
        result.summary_markdown = build_job_summary_markdown(result)
        return result

    client = llm_client or GeminiRadarClient(config)
    repo_inventory = build_repo_inventory(config.repo_root, exclude_files=excluded)

    # Stage 1: batched zero-tool triage (up to 10 items per call)
    by_id = {c.item_id: c for c in candidates}
    verdicts_by_id: dict[str, Stage1ItemVerdict] = {}
    batch_size = max(1, config.max_stage1_batch_size)

    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        try:
            batch_resp, trace = client.triage_stage1_batch(batch, repo_inventory)
            result.traces.append(trace)
            result.total_estimated_cost_usd = round(
                result.total_estimated_cost_usd + trace.estimated_cost_usd, 6
            )
            for v in batch_resp.verdicts:
                if v.item_id in by_id:
                    verdicts_by_id[v.item_id] = v
                    result.stage1_verdicts.append(v)
        except BudgetExceededError:
            result.cost_cap_triggered = True
            break

    result.stage1_reviewed = len(verdicts_by_id)

    # Mark all reviewed candidates seen (even dropped ones) so future runs skip them
    for item_id, verdict in verdicts_by_id.items():
        item = by_id[item_id]
        result.new_seen_records[item_id] = SeenRecord(
            canonical_url=item.canonical_url,
            title_hash=item.title_hash,
            content_hash=item.content_hash,
            feed_id=item.feed_id,
            first_seen_at=run_at,
            verdict=verdict.verdict,
        )

    survivor_verdicts = [v for v in result.stage1_verdicts if v.verdict == "SURVIVOR"][
        : config.max_stage2_survivors
    ]

    # Stage 2: enrich short-body survivors deterministically, then deep rubric delta
    staged: list[ScoredSurvivor] = []
    for sv in survivor_verdicts:
        item = by_id[sv.item_id]
        if offline_candidates is None:
            item = enrich_survivor_body(item, config=config, http_get=http_get)
            if item.enrichment_status == "fetch_blocked":
                result.new_seen_records[item.item_id].verdict = "FETCH_BLOCKED"
                continue

        target_files = [sv.matched_repo_file] if sv.matched_repo_file else []
        target_context = load_target_repo_context(
            config.repo_root, target_files, exclude_files=excluded
        )
        try:
            analysis, trace = client.analyze_stage2_survivor(item, target_context)
            result.traces.append(trace)
            result.total_estimated_cost_usd = round(
                result.total_estimated_cost_usd + trace.estimated_cost_usd, 6
            )
        except BudgetExceededError:
            result.cost_cap_triggered = True
            break

        scored = score_stage2_analysis(
            item,
            analysis,
            stage_threshold=config.stage_score_threshold,
            high_signal_threshold=config.high_signal_threshold,
        )
        result.stage2_results.append(scored)
        result.new_seen_records[item.item_id].verdict = f"{scored.disposition}:{scored.score}"
        if scored.disposition in ("STAGE", "HIGH_SIGNAL"):
            staged.append(scored)

    staged.sort(key=lambda s: s.score, reverse=True)
    result.staged_items = staged
    result.has_high_signal = any(s.disposition == "HIGH_SIGNAL" for s in staged)
    result.summary_markdown = build_job_summary_markdown(result)
    return result


def apply_run_result_files(
    *,
    run_result_path: Path,
    seen_path: Path,
    health_path: Path,
    digest_dir: Path | None = None,
    summary_out_path: Path | None = None,
    update_state: bool = True,
) -> dict[str, object]:
    """Job 2 deterministic helper: validate run-result.json, update state, and render radar/ digest."""
    result = RunResult.model_validate_json(run_result_path.read_text(encoding="utf-8"))
    if update_state:
        seen = load_seen_state(seen_path)
        health = load_feed_health(health_path)
        updated_seen, updated_health = apply_run_result_to_state(seen, health, result)
        save_seen_state(seen_path, updated_seen)
        save_feed_health(health_path, updated_health)

    if summary_out_path is not None:
        summary_out_path.parent.mkdir(parents=True, exist_ok=True)
        summary_out_path.write_text(build_job_summary_markdown(result), encoding="utf-8")

    digest_path: Path | None = None
    added_count = 0
    if digest_dir is not None and result.mode == "enforce" and result.staged_items:
        digest_dir.mkdir(parents=True, exist_ok=True)
        digest_path = digest_dir / f"{result.iso_week}-digest.md"
        existing = digest_path.read_text(encoding="utf-8") if digest_path.is_file() else None
        merged_md, added_count = merge_into_weekly_digest(
            existing,
            result.iso_week,
            result.staged_items,
            updated_at=result.run_at[:10],
        )
        digest_path.write_text(merged_md, encoding="utf-8")

    return {
        "mode": result.mode,
        "iso_week": result.iso_week,
        "staged_count": len(result.staged_items),
        "added_to_digest": added_count,
        "has_high_signal": result.has_high_signal,
        "digest_path": str(digest_path) if digest_path else "",
    }


def _cmd_inventory(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    inv = build_repo_inventory(repo_root, exclude_files=args.exclude or [])
    print(inv)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_env(Path(args.repo_root))
    seen = load_seen_state(Path(args.seen_path)) if args.seen_path else SeenState()
    offline_candidates = None
    if args.offline_items:
        raw = json.loads(Path(args.offline_items).read_text(encoding="utf-8"))
        offline_candidates = [CandidateItem.model_validate(item) for item in raw]

    result = run_pipeline(
        config,
        seen=seen,
        mode=args.mode,
        fast_lane_url=args.url or None,
        offline_candidates=offline_candidates,
        exclude_repo_files=args.withhold or [],
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(result.summary_markdown, encoding="utf-8")
    print(result.summary_markdown)
    return 0


def _cmd_apply_state(args: argparse.Namespace) -> int:
    outcome = apply_run_result_files(
        run_result_path=Path(args.run_result),
        seen_path=Path(args.seen_path),
        health_path=Path(args.health_path),
        digest_dir=Path(args.digest_dir) if args.digest_dir else None,
        summary_out_path=Path(args.summary_out) if args.summary_out else None,
        update_state=not args.no_update_state,
    )
    print(json.dumps(outcome, indent=2))
    return 0


def _cmd_health_report(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = load_feed_registry(repo_root / "radar" / "feeds.yaml")
    health = load_feed_health(Path(args.health_path))
    report = generate_feed_health_report(health, registry)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    print(report)
    return 0


def _cmd_eval_fixture(args: argparse.Namespace) -> int:
    """Run the offline or live Phase 0 replay calibration fixture."""
    fixture_path = Path(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    candidates = [CandidateItem.model_validate(c) for c in fixture["items"]]
    config = PipelineConfig.from_env(Path(args.repo_root))

    if not args.live:
        print(
            f"Loaded calibration fixture '{fixture.get('name', fixture_path.name)}' "
            f"with {len(candidates)} items. Pass --live with GEMINI_API_KEY to benchmark live models."
        )
        return 0

    result = run_pipeline(
        config,
        seen=SeenState(),
        mode="observe",
        offline_candidates=candidates,
        exclude_repo_files=args.withhold or [],
    )
    print(result.summary_markdown)
    if args.output:
        Path(args.output).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Automated, repo-aware signal ingestion pipeline for D-28/upskilling.",
    )
    parser.add_argument("--repo-root", default=".", help="Path to repository root.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inv = sub.add_parser("inventory", help="Print deterministic REPO_INVENTORY.")
    p_inv.add_argument("--exclude", action="append", default=[], help="Relative repo paths to withhold.")
    p_inv.set_defaults(func=_cmd_inventory)

    p_run = sub.add_parser("run", help="Run Stage 0 -> Stage 1 -> Stage 2 pipeline (read-only Job 1).")
    p_run.add_argument("--mode", choices=["observe", "enforce", "bootstrap"], default="observe")
    p_run.add_argument("--seen-path", default="", help="Path to seen.json from radar-state.")
    p_run.add_argument("--output", required=True, help="Path to write validated run-result.json.")
    p_run.add_argument("--summary-out", default="", help="Optional path to write Job Summary markdown.")
    p_run.add_argument("--url", default="", help="Optional single URL for manual fast-lane triage.")
    p_run.add_argument("--offline-items", default="", help="Optional JSON list of CandidateItems for offline runs.")
    p_run.add_argument("--withhold", action="append", default=[], help="Withhold repo files (calibration testing).")
    p_run.set_defaults(func=_cmd_run)

    p_apply = sub.add_parser("apply-state", help="Apply validated run-result.json to state & digest (Job 2).")
    p_apply.add_argument("--run-result", required=True)
    p_apply.add_argument("--seen-path", required=True)
    p_apply.add_argument("--health-path", required=True)
    p_apply.add_argument("--digest-dir", default="", help="Directory for radar/YYYY-Www-digest.md (enforce mode).")
    p_apply.add_argument("--summary-out", default="", help="Regenerate sanitized summary markdown in Job 2.")
    p_apply.add_argument("--no-update-state", action="store_true", help="Render digest without re-applying state counters.")
    p_apply.set_defaults(func=_cmd_apply_state)

    p_health = sub.add_parser("health-report", help="Emit quarterly feed-health & promotion report.")
    p_health.add_argument("--health-path", required=True)
    p_health.add_argument("--output", default="")
    p_health.set_defaults(func=_cmd_health_report)

    p_eval = sub.add_parser("eval-fixture", help="Run Phase 0 replay calibration fixture.")
    p_eval.add_argument(
        "--fixture",
        default="tests/radar/fixtures/nov2026_replay.json",
        help="Path to replay fixture JSON.",
    )
    p_eval.add_argument("--live", action="store_true", help="Invoke live Gemini API (requires GEMINI_API_KEY).")
    p_eval.add_argument("--withhold", action="append", default=[], help="Withhold a playbook to test recall.")
    p_eval.add_argument("--output", default="")
    p_eval.set_defaults(func=_cmd_eval_fixture)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
