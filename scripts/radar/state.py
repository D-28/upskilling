"""Backward-compatible state persistence, PR outcome reconciliation, and feed health reporting.

State files (`seen.json`, `feed-health.json`) live on the dedicated orphan branch
`radar-state` so `main` remains clean and branch-protected.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.radar.fetcher import extract_domain
from scripts.radar.models import (
    DomainHitRecord,
    FeedHealthState,
    FeedRegistry,
    FeedStats,
    RunResult,
    SeenState,
)


def load_seen_state(path: Path) -> SeenState:
    """Load seen.json safely with backward-compatible defaults when absent."""
    if not path.is_file():
        return SeenState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SeenState.model_validate(raw or {})


def save_seen_state(path: Path, state: SeenState) -> None:
    """Persist seen.json with stable sorted keys for clean git diffs on radar-state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_feed_health(path: Path) -> FeedHealthState:
    """Load feed-health.json safely with backward-compatible defaults when absent."""
    if not path.is_file():
        return FeedHealthState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return FeedHealthState.model_validate(raw or {})


def save_feed_health(path: Path, state: FeedHealthState) -> None:
    """Persist feed-health.json with stable sorted keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def apply_run_result_to_state(
    seen: SeenState,
    health: FeedHealthState,
    result: RunResult,
) -> tuple[SeenState, FeedHealthState]:
    """Deterministically apply a validated Job 1 RunResult into seen & feed-health state."""
    updated_seen = seen.model_copy(deep=True)
    updated_health = health.model_copy(deep=True)

    updated_seen.updated_at = result.run_at
    for item_id, rec in result.new_seen_records.items():
        updated_seen.items[item_id] = rec

    updated_health.updated_at = result.run_at
    for fs in result.feed_summaries:
        stats = updated_health.feeds.setdefault(fs.feed_id, FeedStats())
        if fs.ok:
            stats.items_fetched += fs.new_count
            stats.consecutive_fetch_errors = 0
            stats.last_error = ""
            stats.last_success_at = result.run_at
        else:
            stats.consecutive_fetch_errors += 1
            stats.last_error = fs.error

    # Track Stage 1 survivors & Stage 2 staged counts per feed
    survivor_ids = {v.item_id for v in result.stage1_verdicts if v.verdict == "SURVIVOR"}
    for item_id in survivor_ids:
        rec = result.new_seen_records.get(item_id)
        if rec and rec.feed_id:
            stats = updated_health.feeds.setdefault(rec.feed_id, FeedStats())
            stats.stage1_survivors += 1

    for staged in result.staged_items:
        stats = updated_health.feeds.setdefault(staged.item.feed_id, FeedStats())
        stats.stage2_staged += 1

    return updated_seen, updated_health


def reconcile_pr_outcome(
    health: FeedHealthState,
    registry: FeedRegistry,
    *,
    pr_number: int,
    merged: bool,
    staged_markers: list[tuple[str, str, str]],
    landed_item_ids: set[str],
    reconciled_at: str | None = None,
) -> FeedHealthState:
    """Update per-feed human merge/reject counts and unsubscribed domain promotion hits.

    Args:
        health: Current FeedHealthState.
        registry: Current FeedRegistry (used to identify already-subscribed domains).
        pr_number: GitHub PR number being reconciled (idempotent via reconciled_prs).
        merged: Whether the PR was merged (True) or closed without merging (False).
        staged_markers: All `(item_id, feed_id, domain)` entries that were in the PR.
        landed_item_ids: Set of `item_id`s that actually landed on `main` after merge.
        reconciled_at: ISO timestamp for merge date tracking.
    """
    updated = health.model_copy(deep=True)
    if pr_number in updated.reconciled_prs:
        return updated

    now_iso = reconciled_at or datetime.now(UTC).isoformat()
    subscribed_domains = {extract_domain(f.url) for f in registry.feeds}

    for item_id, feed_id, domain in staged_markers:
        stats = updated.feeds.setdefault(feed_id, FeedStats())
        if merged and item_id in landed_item_ids:
            stats.human_merged += 1
            stats.last_merged_at = now_iso
            if domain and domain not in subscribed_domains:
                hit = updated.unsubscribed_domain_hits.setdefault(domain, DomainHitRecord())
                if item_id not in hit.merged_item_ids:
                    hit.merged_item_ids.append(item_id)
                    hit.merged_dates.append(now_iso)
        else:
            stats.human_closed_rejected += 1

    updated.reconciled_prs.append(pr_number)
    updated.updated_at = now_iso
    return updated


def generate_feed_health_report(
    health: FeedHealthState,
    registry: FeedRegistry,
    *,
    now: datetime | None = None,
    window_days: int = 90,
) -> str:
    """Emit a quarterly Markdown report flagging prune & manual promotion candidates."""
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=window_days)

    prune_candidates: list[str] = []
    healthy_rows: list[str] = []

    for feed in registry.feeds:
        s = health.feeds.get(feed.id, FeedStats())
        reviewed = s.human_merged + s.human_closed_rejected
        reject_rate = (s.human_closed_rejected / reviewed) if reviewed > 0 else 0.0

        reasons: list[str] = []
        if s.consecutive_fetch_errors >= 3:
            reasons.append(f"{s.consecutive_fetch_errors} consecutive fetch errors")
        if reviewed >= 3 and reject_rate > 0.90:
            reasons.append(f"{reject_rate:.0%} human rejection rate ({s.human_closed_rejected}/{reviewed})")
        if s.items_fetched > 0 and s.human_merged == 0 and s.last_success_at:
            reasons.append("0 human-merged items in window")

        if reasons:
            prune_candidates.append(f"- **`{feed.id}`** ({feed.name}): {'; '.join(reasons)}")

        healthy_rows.append(
            f"| `{feed.id}` | {s.items_fetched} | {s.stage1_survivors} | {s.stage2_staged} | "
            f"{s.human_merged} | {s.human_closed_rejected} | {s.consecutive_fetch_errors} |"
        )

    promote_candidates: list[str] = []
    for domain, rec in sorted(health.unsubscribed_domain_hits.items()):
        recent_count = 0
        for raw_dt in rec.merged_dates:
            try:
                dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                if dt >= cutoff:
                    recent_count += 1
            except ValueError:
                recent_count += 1
        if recent_count >= 2:
            promote_candidates.append(
                f"- **`{domain}`**: {recent_count} human-merged items in last {window_days}d — consider adding RSS/Atom feed to `radar/feeds.yaml`."
            )

    lines = [
        "# Radar Feed Health & Pruning Report",
        "",
        f"- **Generated:** `{current.isoformat()}`",
        f"- **Evaluation Window:** Last `{window_days}` days",
        "",
        "## Per-Feed Telemetry",
        "",
        "| Feed ID | Fetched | Stage 1 Survivors | Stage 2 Staged | Human Merged | Rejected | Consecutive Errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *healthy_rows,
        "",
        "## Prune Candidates (Review Manually)",
        *(prune_candidates or ["- None flagged."]),
        "",
        "## Promotion Candidates (>= 2 Human-Merged Items from Unsubscribed Domains)",
        *(promote_candidates or ["- None yet."]),
        "",
    ]
    return "\n".join(lines)
