"""Backward-compatible state persistence, PR outcome reconciliation, and feed health reporting.

State files (`seen.json`, `feed-health.json`, `pending-candidates.json`) live on the dedicated
orphan branch `radar-state` so `main` remains clean and branch-protected.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.radar.config import MAX_SEEN_ITEMS
from scripts.radar.fetcher import extract_domain
from scripts.radar.models import (
    PENDING_BUFFER_MIN_SCORE,
    DomainHitRecord,
    FeedHealthState,
    FeedRegistry,
    FeedStats,
    PendingCandidate,
    PendingCandidatesState,
    RunResult,
    SeenState,
)
from scripts.radar.security import redact_secrets


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


def load_pending_candidates(path: Path) -> PendingCandidatesState:
    """Load pending-candidates.json safely with backward-compatible empty defaults when absent."""
    if not path.is_file():
        return PendingCandidatesState()
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return PendingCandidatesState()
    raw = json.loads(text)
    return PendingCandidatesState.model_validate(raw or {})


def save_pending_candidates(path: Path, state: PendingCandidatesState) -> None:
    """Persist pending-candidates.json with stable sorted keys for clean git diffs on radar-state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def apply_run_result_to_pending(
    pending: PendingCandidatesState,
    result: RunResult,
) -> PendingCandidatesState:
    """Buffer Mon-Sat survivors (`>= 7/10`) or clear the buffer after a weekly Coherence Gate run."""
    updated = pending.model_copy(deep=True)
    if result.status == "FETCH_INCOMPLETE" or result.mode == "bootstrap":
        return updated
    if bool(result.fast_lane_url) and result.mode == "observe":
        return updated

    if result.run_coherence_gate:
        updated.items.clear()
        updated.updated_at = result.run_at
        return updated

    for scored in result.buffered_items:
        if (
            scored.disposition in ("STAGE", "HIGH_SIGNAL")
            and scored.score >= PENDING_BUFFER_MIN_SCORE
        ):
            updated.items[scored.item.item_id] = PendingCandidate(
                item=scored.item,
                analysis=scored.analysis,
                score=scored.score,
                disposition=scored.disposition,
                gate_failure_reason=scored.gate_failure_reason,
                buffered_at=result.run_at,
                iso_week=result.iso_week,
            )
    if result.buffered_items:
        updated.updated_at = result.run_at
    return updated


def apply_run_result_to_state(
    seen: SeenState,
    health: FeedHealthState,
    result: RunResult,
    *,
    max_seen_items: int = MAX_SEEN_ITEMS,
) -> tuple[SeenState, FeedHealthState]:
    """Deterministically apply a validated Job 1 RunResult into seen & feed-health state."""
    updated_seen = seen.model_copy(deep=True)
    updated_health = health.model_copy(deep=True)

    skip_seen_burn = result.status == "FETCH_INCOMPLETE" or (
        bool(result.fast_lane_url) and result.mode == "observe"
    )
    if not skip_seen_burn:
        updated_seen.updated_at = result.run_at
        for item_id, rec in result.new_seen_records.items():
            if rec.verdict == "FETCH_INCOMPLETE":
                continue
            if rec.feed_id == "fast-lane" and result.mode == "observe":
                continue
            updated_seen.items[item_id] = rec

        if len(updated_seen.items) > max_seen_items:
            sorted_pairs = sorted(
                updated_seen.items.items(),
                key=lambda kv: (kv[1].first_seen_at or "", kv[0]),
                reverse=True,
            )[:max_seen_items]
            updated_seen.items = dict(sorted_pairs)

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
            stats.last_error = redact_secrets(fs.error)[:240]

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
        if (
            s.human_merged == 0
            and s.last_success_at
            and (len(health.reconciled_prs) >= 4 or s.items_fetched >= 30)
        ):
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
